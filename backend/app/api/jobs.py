import json
import asyncio
import re
import html
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal, get_db
from app.models.job import Job
from app.models.job_material import JobMaterial
from app.models.profile import UserProfile
from app.models.job_source import JobSource
from app.schemas.job import (
    BulkActionRequest,
    BulkActionResponse,
    CompanySiteDiscoverRequest,
    DashboardResponse,
    IngestRequest,
    JobRead,
    JobSearchRequest,
    JobUpdate,
    MaterialRequest,
    MaterialResponse,
    NationwideRecommendationRequest,
    RefreshScopeRead,
    RefreshStatusResponse,
    RescoreAllResponse,
)
from app.services import ingestion
from app.services.job_service import create_or_update_job, get_dashboard_metrics, list_jobs
from app.services.distance import ZIP_CITY_STATE, distance_from_base_zip, infer_zip_from_location
from app.services.extraction import extract_skills
from app.services.materials import generate_materials
from app.services.background_refresh import enqueue_refresh
from app.services.query_cache import invalidate_jobs_query_cache, jobs_query_cache
from app.services.refresh_state import (
    ACTIVE_REFRESH_STATUSES,
    REFRESH_SCOPE_LABELS,
    list_refresh_states,
    mark_refresh_finished,
    mark_refresh_queued,
    mark_refresh_started,
)
from app.services.constants import (
    AGGRESSIVE_GREENHOUSE_TOKENS,
    AGGRESSIVE_LEVER_SLUGS,
    AGGRESSIVE_MUSE_CATEGORIES,
    CONTIGUOUS_US_STATES,
    HOBBY_JOB_SIGNALS,
    SOURCE_TRUST,
    US_STATE_ABBREV_TO_NAME,
    US_STATE_NAME_TO_ABBREV,
)
from app.services.scoring import normalize_score_tuning_mode, score_job

router = APIRouter(prefix="/jobs", tags=["jobs"])
CITY_STATE_TO_ZIP = {(city, state): zip_code for zip_code, (city, state) in ZIP_CITY_STATE.items() if city and state}


def _to_utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _clean_description_text(text: str | None) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    value = html.unescape(raw)
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</(p|div|li|h1|h2|h3|h4|h5|h6)>", "\n", value)
    value = re.sub(r"(?i)<li[^>]*>", "- ", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    replacements = {
        "â€“": "-",
        "â€”": "-",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "\u00a0": " ",
        "\ufffd": "",
    }
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n\n", value)
    cleaned = value.strip()
    return cleaned or None


def _apply_applied_followup_rule(job: Job, old_status: str) -> None:
    new_status = (job.status or "").lower()
    if old_status != "applied" and new_status == "applied":
        applied_at = job.applied_date or datetime.utcnow()
        job.applied_date = applied_at
        if job.follow_up_date is None:
            job.follow_up_date = applied_at + timedelta(days=7)
            reminders = json.loads(job.reminders or "[]")
            reminders.append(f"Follow up by {job.follow_up_date.date().isoformat()} for application check-in")
            job.reminders = json.dumps(reminders)


def _default_search_locations(base_zip: str | None) -> list[str]:
    locations: list[str] = []
    if base_zip:
        base = ZIP_CITY_STATE.get(base_zip)
        if base:
            city, state = base
            if state == "oh":
                locations.extend(
                    [
                        f"{city.title()}, OH",
                        "Akron, OH",
                        "Cleveland, OH",
                        "Cuyahoga Falls, OH",
                        "Kent, OH",
                        "Hudson, OH",
                        "Twinsburg, OH",
                        "Aurora, OH",
                        "Tallmadge, OH",
                        "Canton, OH",
                        "Medina, OH",
                        "Strongsville, OH",
                        "Wooster, OH",
                        "Youngstown, OH",
                        "Columbus, OH",
                        "Ohio",
                    ]
                )
            else:
                locations.extend([f"{city.title()}, {state.upper()}", state.upper()])
    else:
        locations.extend(["Akron, OH", "Cleveland, OH", "Ohio"])

    deduped: list[str] = []
    for loc in locations:
        normalized = (loc or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _normalize_state_value(state_raw: str | None) -> tuple[str | None, str | None]:
    raw = (state_raw or "").strip()
    if not raw:
        return None, None
    upper = raw.upper()
    if upper in US_STATE_ABBREV_TO_NAME:
        return US_STATE_ABBREV_TO_NAME[upper], upper
    normalized_name_key = re.sub(r"\s+", " ", raw).strip().upper()
    state_code = US_STATE_NAME_TO_ABBREV.get(normalized_name_key)
    if state_code:
        return US_STATE_ABBREV_TO_NAME[state_code], state_code
    return raw.title(), None


def _extract_state_code_from_text(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    upper = text.upper()
    for match in re.findall(r"\b([A-Z]{2})\b", upper):
        if match in US_STATE_ABBREV_TO_NAME:
            return match
    lower = text.lower()
    for code, name in US_STATE_ABBREV_TO_NAME.items():
        if re.search(rf"\b{re.escape(name.lower())}\b", lower):
            return code
    return None


def _row_state_code(row: JobRead) -> str | None:
    direct = _extract_state_code_from_text(row.state)
    if direct:
        return direct
    return _extract_state_code_from_text(row.location_text)


def _row_matches_area(
    row: JobRead,
    city: str | None,
    state_name: str | None,
    state_code: str | None,
    zip_code: str | None,
    max_distance: float | None,
) -> bool:
    if not city and not state_name and not state_code and not zip_code:
        return True

    if zip_code:
        target = infer_zip_from_location(row.location_text, city=row.city, state=row.state)
        if not target:
            return False
        max_dist = max_distance if max_distance is not None else 50.0
        dist = distance_from_base_zip(zip_code, target)
        return dist is not None and dist <= max_dist

    if state_code:
        row_state = _row_state_code(row)
        if row_state != state_code:
            return False

    if state_name and not state_code:
        row_state = _row_state_code(row)
        if not row_state:
            return False
        if US_STATE_ABBREV_TO_NAME.get(row_state, "").lower() != state_name.lower():
            return False

    if city:
        city_norm = city.strip().lower()
        row_city = (row.city or "").strip().lower()
        location_text = (row.location_text or "").strip().lower()
        if city_norm and city_norm not in {row_city} and city_norm not in location_text:
            return False

    return True


def _raw_item_matches_query(item: dict[str, Any], query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    text = f"{item.get('title', '')} {item.get('company', '')} {item.get('location_text', '')} {item.get('description', '')}".lower()
    if q in text:
        return True
    tokens = [t for t in re.split(r"\s+", q) if t]
    if not tokens:
        return True
    return sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", text)) >= 1


def _raw_item_has_salary(item: dict[str, Any]) -> bool:
    if item.get("pay_min") not in (None, "") or item.get("pay_max") not in (None, ""):
        return True
    text = str(item.get("pay_text") or item.get("salary") or "").strip().lower()
    return bool(text) and "not listed" not in text


def _normalize_phrase(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _contains_phrase(haystack: str, phrase: str) -> bool:
    normalized = _normalize_phrase(phrase)
    if not normalized:
        return False
    pattern = r"\b" + re.escape(normalized).replace(r"\ ", r"\s+") + r"\b"
    return re.search(pattern, haystack) is not None


def _normalize_profile_skills(profile_skills: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in profile_skills or []:
        value = _normalize_phrase(raw)
        compact_len = len(re.sub(r"[^a-z0-9]+", "", value))
        if compact_len < 3 or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _normalize_profile_hobbies(profile_hobbies: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in profile_hobbies or []:
        value = _normalize_phrase(raw)
        compact_len = len(re.sub(r"[^a-z0-9]+", "", value))
        if compact_len < 3 or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _skill_token_set(values: list[str] | None) -> set[str]:
    tokens: set[str] = set()
    for value in values or []:
        normalized = _normalize_phrase(value)
        if not normalized:
            continue
        for token in normalized.split():
            if len(token) >= 4:
                tokens.add(token)
    return tokens


def _hobby_alignment_score(text: str, profile_hobbies: list[str] | None) -> float:
    hobbies = _normalize_profile_hobbies(profile_hobbies)
    if not hobbies:
        return 0.0
    matched = 0
    for hobby in hobbies:
        terms = list(HOBBY_JOB_SIGNALS.get(hobby, []))
        if hobby not in terms:
            terms.append(hobby)
        if any(_contains_phrase(text, term) for term in terms if term):
            matched += 1
    ratio = matched / max(1, len(hobbies))
    return round(0.4 + (0.6 * ratio), 4)


def _job_is_relevant_to_profile(
    *,
    title: str | None,
    description: str | None,
    extracted_skills: list[str] | None,
    profile_skills: list[str] | None,
    profile_hobbies: list[str] | None = None,
    potential_match_score: float | None = None,
    interview_score: float | None = None,
) -> bool:
    normalized_profile = _normalize_profile_skills(profile_skills)
    has_resume = bool(normalized_profile)
    has_hobbies = bool(_normalize_profile_hobbies(profile_hobbies))
    if not has_resume and not has_hobbies:
        return True

    text = _normalize_phrase(f"{title or ''} {description or ''}")
    hobby_alignment = _hobby_alignment_score(text, profile_hobbies)
    if has_hobbies and hobby_alignment >= 0.58:
        return True

    if not has_resume:
        return hobby_alignment >= 0.52

    extracted = _normalize_profile_skills(extracted_skills or [])
    direct_hits = 0
    for skill in normalized_profile:
        if _contains_phrase(text, skill):
            direct_hits += 1
            continue
        if any(skill in term or term in skill for term in extracted):
            direct_hits += 1
    extracted_overlap = len(set(extracted).intersection(set(normalized_profile)))
    if direct_hits >= 1 or extracted_overlap >= 1:
        return True

    profile_tokens = _skill_token_set(normalized_profile)
    job_tokens = set(re.findall(r"[a-z0-9+#]{4,}", text)).union(_skill_token_set(extracted))
    token_overlap = len(profile_tokens.intersection(job_tokens))
    if token_overlap >= 2:
        return True

    if potential_match_score is not None and float(potential_match_score) >= 48:
        return True
    if interview_score is not None and float(interview_score) >= 52:
        return True
    return False


def _raw_item_matches_profile(
    item: dict[str, Any],
    profile_skills: list[str] | None,
    profile_hobbies: list[str] | None,
) -> bool:
    description = str(item.get("description") or "")
    extracted = extract_skills(description)
    return _job_is_relevant_to_profile(
        title=str(item.get("title") or ""),
        description=description,
        extracted_skills=extracted,
        profile_skills=profile_skills,
        profile_hobbies=profile_hobbies,
    )


def _build_national_locations(city: str | None, state_name: str | None, state_code: str | None, zip_code: str | None) -> tuple[list[str], bool]:
    if zip_code:
        return [zip_code], False
    if city and state_code:
        return [f"{city}, {state_code}"], False
    if city and state_name:
        return [f"{city}, {state_name}"], False
    if state_name:
        return [state_name], False
    return list(CONTIGUOUS_US_STATES), True


def _refresh_queue_key(namespace: str, payload: dict[str, Any]) -> str:
    return f"{namespace}:{json.dumps(payload, sort_keys=True, default=str)}"


async def _refresh_search_pool_async(payload: dict[str, Any]) -> None:
    req = JobSearchRequest.model_validate(payload)
    db = SessionLocal()
    scope = "local_search"
    items_written = 0
    mark_refresh_started(scope)
    try:
        query = (req.query or "").strip()
        profile_skills = _load_profile_skills(db)
        profile_hobbies = _load_profile_hobbies(db)
        requested_zip = (req.base_zip or "").strip() or None
        aggressive_mode = bool(settings.aggressive_legal_mode)
        pages = min(max(req.pages, 1), 4 if aggressive_mode else 3)
        if not query:
            pages = min(pages, 2)
        limit = max(1, min(req.limit, 160))
        ingested: list[dict[str, Any]] = []
        remote_pref = (req.remote_type or "any").lower().strip()
        locations = _default_search_locations(requested_zip)
        enabled_sources = db.scalars(select(JobSource).where(JobSource.enabled.is_(True))).all()

        async def _safe_fetch(coro, timeout_seconds: float = 12.0) -> list[dict[str, Any]]:
            try:
                return await asyncio.wait_for(coro, timeout=timeout_seconds)
            except Exception:
                return []

        pending_fetches: list[tuple[Any, float]] = []

        def _queue(factory: Any, timeout_seconds: float) -> None:
            pending_fetches.append((factory, timeout_seconds))

        for src in enabled_sources:
            try:
                cfg = json.loads(src.config_json or "{}")
            except json.JSONDecodeError:
                cfg = {}
            try:
                st = (src.source_type or "").lower().strip()
                if st == "greenhouse" and cfg.get("board_token"):
                    token = cfg["board_token"]
                    _queue(lambda token=token: ingestion.fetch_greenhouse(token), 8.0)
                elif st == "lever" and cfg.get("company_slug"):
                    slug = cfg["company_slug"]
                    _queue(lambda slug=slug: ingestion.fetch_lever(slug), 8.0)
                elif st == "rss" and cfg.get("rss_url"):
                    rss_url = cfg["rss_url"]
                    _queue(lambda rss_url=rss_url: ingestion.fetch_rss(rss_url), 8.0)
                elif st == "adzuna":
                    app_id = cfg.get("app_id") or settings.adzuna_app_id
                    app_key = cfg.get("app_key") or settings.adzuna_app_key
                    if app_id and app_key:
                        for page in range(1, min(pages, 5 if aggressive_mode else 3) + 1):
                            where = cfg.get("where", requested_zip or "Akron, OH")
                            what = query or cfg.get("what", "jobs")
                            _queue(
                                lambda app_id=app_id, app_key=app_key, where=where, what=what, page=page: ingestion.fetch_adzuna(
                                    app_id,
                                    app_key,
                                    where=where,
                                    what=what,
                                    page=page,
                                ),
                                8.0,
                            )
                elif st == "themuse":
                    for page in range(1, min(pages, 8 if aggressive_mode else 5) + 1):
                        location = cfg.get("location", requested_zip or "Ohio")
                        category = cfg.get("category")
                        _queue(
                            lambda location=location, category=category, page=page: ingestion.fetch_themuse(
                                location=location,
                                category=category,
                                page=page,
                            ),
                            8.0,
                        )
            except Exception:
                continue

        fallback_locations = locations if query else locations[:3]
        for location in fallback_locations:
            for page in range(1, min(pages, 10 if aggressive_mode else 5) + 1):
                try:
                    _queue(lambda location=location, page=page: ingestion.fetch_themuse(location=location, page=page), 6.0)
                except Exception:
                    continue

        if aggressive_mode:
            local_focus_locations = locations[:6] if query else locations[:3]
            local_focus_locations = local_focus_locations if local_focus_locations else ["Akron, OH", "Cleveland, OH", "Ohio"]
            for location in local_focus_locations:
                for category in AGGRESSIVE_MUSE_CATEGORIES:
                    for page in range(1, min(pages, 4 if query else 2) + 1):
                        try:
                            _queue(
                                lambda location=location, category=category, page=page: ingestion.fetch_themuse(
                                    location=location,
                                    category=category,
                                    page=page,
                                ),
                                7.0,
                            )
                        except Exception:
                            continue

            if query:
                for token in AGGRESSIVE_GREENHOUSE_TOKENS:
                    try:
                        _queue(lambda token=token: ingestion.fetch_greenhouse(token), 6.0)
                    except Exception:
                        continue
                for slug in AGGRESSIVE_LEVER_SLUGS:
                    try:
                        _queue(lambda slug=slug: ingestion.fetch_lever(slug), 6.0)
                    except Exception:
                        continue

        if settings.adzuna_app_id and settings.adzuna_app_key:
            where = requested_zip or "United States"
            for page in range(1, min(4 if aggressive_mode else 2, pages) + 1):
                try:
                    what = query or "jobs"
                    _queue(
                        lambda where=where, what=what, page=page: ingestion.fetch_adzuna(
                            settings.adzuna_app_id,
                            settings.adzuna_app_key,
                            where=where,
                            what=what,
                            page=page,
                        ),
                        7.0,
                    )
                except Exception:
                    continue

        max_tasks = 72 if (aggressive_mode and query) else (48 if query else 24)
        if len(pending_fetches) > max_tasks:
            pending_fetches = pending_fetches[:max_tasks]

        if pending_fetches:
            batch_size = 8 if aggressive_mode else 6
            for i in range(0, len(pending_fetches), batch_size):
                batch = pending_fetches[i : i + batch_size]
                coros = [_safe_fetch(factory(), timeout_seconds=timeout_seconds) for factory, timeout_seconds in batch]
                fetched = await asyncio.gather(*coros, return_exceptions=True)
                for chunk in fetched:
                    if isinstance(chunk, list):
                        ingested.extend(chunk)

        query_tokens = [t for t in query.lower().split() if t] if query else []
        weak_tokens = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with", "role", "job", "jobs", "line", "worker"}
        significant_tokens = [t for t in query_tokens if len(t) >= 3 and t not in weak_tokens]
        expanded_tokens = set(significant_tokens)
        query_lower = query.lower()
        query_aliases = {
            "line cook": ["cook", "kitchen", "restaurant", "food", "catering", "chef", "prep"],
            "fast food": ["food", "restaurant", "crew", "cook", "catering", "cashier"],
            "factory worker": ["factory", "manufacturing", "production", "assembly", "warehouse", "laborer", "operator"],
            "warehouse": ["warehouse", "distribution", "shipping", "receiving", "fulfillment", "forklift"],
            "sales representative": ["sales", "representative", "account", "business development", "consultant"],
        }
        for phrase, aliases in query_aliases.items():
            if phrase in query_lower:
                expanded_tokens.update(aliases)

        def _matches_query(item: dict[str, Any]) -> bool:
            if not query_tokens:
                return True
            title_company = f"{item.get('title', '')} {item.get('company', '')}".lower()
            haystack = f"{title_company} {item.get('description', '')}".lower()
            if query.lower() in haystack:
                return True

            def _contains_word(text: str, token: str) -> bool:
                return re.search(rf"\b{re.escape(token)}\b", text) is not None

            if expanded_tokens:
                title_hits = sum(1 for token in expanded_tokens if _contains_word(title_company, token))
                if title_hits >= 1:
                    return True
                desc_hits = sum(1 for token in expanded_tokens if _contains_word(haystack, token))
                if desc_hits >= 1:
                    return True
            token_hits = sum(1 for token in query_tokens if _contains_word(title_company, token))
            return token_hits >= 1

        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for item in ingested:
            if not _matches_query(item):
                continue
            if not _raw_item_matches_profile(item, profile_skills, profile_hobbies):
                continue
            if req.salary_required and not _raw_item_has_salary(item):
                continue
            if req.exclude_confidential and _is_confidential_employer(item.get("company")):
                continue
            key = (item.get("canonical_url") or item.get("url") or "").strip()
            if key:
                if key in seen_urls:
                    continue
                seen_urls.add(key)
            candidates.append(item)

        if remote_pref == "local" and requested_zip:
            def _local_priority(item: dict[str, Any]) -> tuple[int, float]:
                remote_type = str(item.get("remote_type") or "unknown").lower().strip()
                if remote_type == "remote":
                    return (2, 9999.0)
                target = infer_zip_from_location(
                    item.get("location_text"),
                    city=item.get("city"),
                    state=item.get("state"),
                )
                dist = distance_from_base_zip(requested_zip, target)
                if dist is not None:
                    return (0, dist)
                if _location_looks_local(requested_zip, item.get("location_text")):
                    return (1, 0.0)
                return (2, 9999.0)

            candidates.sort(key=_local_priority)

        max_persist = _bounded_candidate_limit(
            limit,
            multiplier=2,
            minimum=60,
            maximum=180 if aggressive_mode else 120,
        )
        touched: dict[int, Job] = {}
        for item in candidates[:max_persist]:
            saved = create_or_update_job(db, item, profile_skills, commit=False)
            touched[saved.id] = saved
        if touched:
            db.commit()
            invalidate_jobs_query_cache()
            items_written = len(touched)
        mark_refresh_finished(scope, success=True, items_written=items_written)
    except Exception as exc:
        db.rollback()
        mark_refresh_finished(scope, success=False, items_written=items_written, error=f"Local refresh failed: {exc}")
    finally:
        db.close()


async def _refresh_national_pool_async(payload: dict[str, Any]) -> None:
    req = NationwideRecommendationRequest.model_validate(payload)
    if not req.refresh_pool:
        return

    db = SessionLocal()
    scope = "nationwide"
    items_written = 0
    mark_refresh_started(scope)
    try:
        query = (req.query or "").strip()
        city = (req.city or "").strip() or None
        zip_code = (req.zip_code or "").strip() or None
        state_name, state_code = _normalize_state_value(req.state)
        search_locations, nationwide_scope = _build_national_locations(city, state_name, state_code, zip_code)
        profile = _load_profile_record(db)
        profile_skills = _load_profile_skills(db, profile)
        profile_hobbies = _load_profile_hobbies(db, profile)
        ingested: list[dict[str, Any]] = []
        touched: dict[int, Job] = {}

        pending_fetches: list[tuple[Any, float]] = []

        def _queue(factory: Any, timeout_seconds: float) -> None:
            pending_fetches.append((factory, timeout_seconds))

        pages_per_region = max(1, min(req.pages_per_region, 2))
        muse_categories = AGGRESSIVE_MUSE_CATEGORIES[:4]

        for location in search_locations:
            for page in range(1, pages_per_region + 1):
                _queue(lambda location=location, page=page: ingestion.fetch_themuse(location=location, page=page), 8.0)
                if query and len(search_locations) <= 6:
                    for category in muse_categories:
                        _queue(
                            lambda location=location, category=category, page=page: ingestion.fetch_themuse(
                                location=location,
                                category=category,
                                page=page,
                            ),
                            8.0,
                        )
                elif nationwide_scope and page == 1:
                    for category in muse_categories[:2]:
                        _queue(
                            lambda location=location, category=category: ingestion.fetch_themuse(
                                location=location,
                                category=category,
                                page=1,
                            ),
                            8.0,
                        )
            if settings.adzuna_app_id and settings.adzuna_app_key:
                max_adzuna_pages = 1 if nationwide_scope else min(2, pages_per_region)
                for page in range(1, max_adzuna_pages + 1):
                    what = query or "jobs"
                    _queue(
                        lambda location=location, what=what, page=page: ingestion.fetch_adzuna(
                            settings.adzuna_app_id,
                            settings.adzuna_app_key,
                            where=location,
                            what=what,
                            page=page,
                        ),
                        9.0,
                    )

        for token in AGGRESSIVE_GREENHOUSE_TOKENS:
            _queue(lambda token=token: ingestion.fetch_greenhouse(token), 8.0)
        for slug in AGGRESSIVE_LEVER_SLUGS:
            _queue(lambda slug=slug: ingestion.fetch_lever(slug), 8.0)

        max_tasks = 60 if nationwide_scope else 40
        if len(pending_fetches) > max_tasks:
            pending_fetches = pending_fetches[:max_tasks]

        async def _safe_fetch(coro, timeout_seconds: float) -> list[dict[str, Any]]:
            try:
                return await asyncio.wait_for(coro, timeout=timeout_seconds)
            except Exception:
                return []

        batch_size = 8
        for i in range(0, len(pending_fetches), batch_size):
            batch = pending_fetches[i : i + batch_size]
            coros = [_safe_fetch(factory(), timeout_seconds=timeout) for factory, timeout in batch]
            fetched = await asyncio.gather(*coros, return_exceptions=True)
            for chunk in fetched:
                if isinstance(chunk, list):
                    ingested.extend(chunk)

        seen_keys: set[str] = set()
        candidates: list[dict[str, Any]] = []
        for item in ingested:
            if not _raw_item_matches_query(item, query):
                continue
            if not _raw_item_matches_profile(item, profile_skills, profile_hobbies):
                continue
            if req.salary_required and not _raw_item_has_salary(item):
                continue
            if req.exclude_confidential and _is_confidential_employer(item.get("company")):
                continue
            dedupe_key = (item.get("canonical_url") or item.get("url") or "").strip().lower()
            if dedupe_key and dedupe_key in seen_keys:
                continue
            if dedupe_key:
                seen_keys.add(dedupe_key)
            candidates.append(item)

        max_persist = _bounded_candidate_limit(
            req.limit,
            multiplier=8 if nationwide_scope else 6,
            minimum=80,
            maximum=250 if nationwide_scope else 160,
        )
        for item in candidates[:max_persist]:
            saved = create_or_update_job(db, item, profile_skills, commit=False)
            touched[saved.id] = saved
        if touched:
            db.commit()
            invalidate_jobs_query_cache()
            items_written = len(touched)
        mark_refresh_finished(scope, success=True, items_written=items_written)
    except Exception as exc:
        db.rollback()
        mark_refresh_finished(scope, success=False, items_written=items_written, error=f"Nationwide refresh failed: {exc}")
    finally:
        db.close()


async def warm_startup_caches() -> None:
    db = SessionLocal()
    try:
        profile = _load_profile_record(db)
        base_zip = _load_profile_zip(db, profile) or settings.base_zip or "44224"
        distance_miles = float(profile.distance_miles) if profile and profile.distance_miles else 35.0

        recommendations(
            limit=25,
            base_zip=base_zip,
            max_distance=distance_miles,
            min_salary=None,
            remote_type="local",
            salary_required=True,
            exclude_confidential=True,
            db=db,
        )

        await nationwide_recommendations(
            NationwideRecommendationRequest(
                base_zip=base_zip,
                max_distance=distance_miles,
                remote_type="any",
                salary_required=True,
                exclude_confidential=True,
                min_interview_score_10=5.5,
                min_compatibility_score_10=6.5,
                limit=25,
                pages_per_region=1,
                refresh_pool=False,
                adaptive_thresholds=True,
            ),
            db,
        )

    except Exception:
        pass
    finally:
        db.close()


def _serialize_refresh_state_rows(db: Session) -> RefreshStatusResponse:
    states = list_refresh_states(db)
    state_by_scope = {state.scope: state for state in states}
    scopes: list[RefreshScopeRead] = []
    last_source_refresh_at: datetime | None = None
    for scope in REFRESH_SCOPE_LABELS:
        state = state_by_scope.get(scope)
        if state is None:
            scopes.append(
                RefreshScopeRead(
                    scope=scope,
                    label=REFRESH_SCOPE_LABELS.get(scope, scope.replace("_", " ").title()),
                    status="idle",
                    active=False,
                    items_written=0,
                )
            )
            continue
        if state.last_success_at and (last_source_refresh_at is None or state.last_success_at > last_source_refresh_at):
            last_source_refresh_at = state.last_success_at
        scopes.append(
            RefreshScopeRead(
                scope=state.scope,
                label=REFRESH_SCOPE_LABELS.get(state.scope, state.scope.replace("_", " ").title()),
                status=state.status,
                active=state.status in ACTIVE_REFRESH_STATUSES,
                last_enqueued_at=state.last_enqueued_at,
                last_started_at=state.last_started_at,
                last_finished_at=state.last_finished_at,
                last_success_at=state.last_success_at,
                last_error=state.last_error,
                items_written=state.items_written or 0,
                updated_at=state.updated_at,
            )
        )
    return RefreshStatusResponse(last_source_refresh_at=last_source_refresh_at, scopes=scopes)


@router.get("", response_model=list[JobRead])
def get_jobs(
    q: str | None = None,
    status: str | None = None,
    remote_type: str | None = None,
    source: str | None = None,
    base_zip: str | None = Query(default=None),
    max_distance: float | None = Query(default=None),
    salary_present: bool = False,
    db: Session = Depends(get_db),
):
    profile_skills = _load_profile_skills(db)
    profile_hobbies = _load_profile_hobbies(db)
    rows = list_jobs(
        db,
        {
            "q": q,
            "status": status,
            "remote_type": remote_type,
            "source": source,
            "max_distance": max_distance if not base_zip else None,
            "salary_present": salary_present,
        },
    )
    serialized = _serialize_rows_with_dynamic_distance(rows=rows, db=db, base_zip=base_zip, max_distance=max_distance)
    remote_pref = (remote_type or "any").lower().strip()
    if remote_pref not in {"any", "local", "remote", "onsite", "hybrid"}:
        remote_pref = "any"
    return _filter_serialized_rows(
        rows=serialized,
        remote_pref=remote_pref,
        min_salary=None,
        salary_required=salary_present,
        exclude_confidential=False,
        profile_skills=profile_skills,
        profile_hobbies=profile_hobbies,
    )


@router.get("/refresh-status", response_model=RefreshStatusResponse)
def get_refresh_status(db: Session = Depends(get_db)):
    return _serialize_refresh_state_rows(db)


@router.post("/search", response_model=list[JobRead])
async def search_jobs(req: JobSearchRequest, db: Session = Depends(get_db)):
    try:
        query = (req.query or "").strip()
        profile_skills = _load_profile_skills(db)
        profile_hobbies = _load_profile_hobbies(db)
        requested_zip = (req.base_zip or "").strip() or None
        limit = max(1, min(req.limit, 1000))
        remote_pref = (req.remote_type or "any").lower().strip()
        if remote_pref not in {"any", "local", "remote", "onsite", "hybrid"}:
            raise HTTPException(status_code=400, detail="remote_type must be any/local/remote/onsite/hybrid")

        cache_params = req.model_dump()
        if not req.refresh_pool:
            cached_rows = jobs_query_cache.get("search", cache_params)
            if cached_rows is not None:
                return [JobRead.model_validate(row) for row in cached_rows]

        query_tokens = [t for t in query.lower().split() if t] if query else []
        weak_tokens = {
            "a",
            "an",
            "and",
            "for",
            "in",
            "of",
            "on",
            "the",
            "to",
            "with",
            "role",
            "job",
            "jobs",
            "line",
            "worker",
        }
        significant_tokens = [t for t in query_tokens if len(t) >= 3 and t not in weak_tokens]
        expanded_tokens = set(significant_tokens)
        query_lower = query.lower()
        query_aliases = {
            "line cook": ["cook", "kitchen", "restaurant", "food", "catering", "chef", "prep"],
            "fast food": ["food", "restaurant", "crew", "cook", "catering", "cashier"],
            "factory worker": ["factory", "manufacturing", "production", "assembly", "warehouse", "laborer", "operator"],
            "warehouse": ["warehouse", "distribution", "shipping", "receiving", "fulfillment", "forklift"],
            "sales representative": ["sales", "representative", "account", "business development", "consultant"],
        }
        for phrase, aliases in query_aliases.items():
            if phrase in query_lower:
                expanded_tokens.update(aliases)

        if req.refresh_pool:
            queued = enqueue_refresh(
                _refresh_queue_key("search", req.model_dump(mode="python")),
                _refresh_search_pool_async,
                req.model_dump(mode="python"),
            )
            if queued:
                mark_refresh_queued("local_search")

        db_row_limit = _bounded_candidate_limit(
            limit,
            multiplier=5 if query else 4,
            minimum=120,
            maximum=320,
        )
        rows = list_jobs(db, {"q": query or None, "limit": db_row_limit})
        serialized = _serialize_rows_with_dynamic_distance(
            rows=rows,
            db=db,
            base_zip=requested_zip,
            max_distance=req.max_distance,
        )
        if req.created_after is not None:
            cutoff = _to_utc_naive(req.created_after)
            serialized = [
                r
                for r in serialized
                if (
                    (_to_utc_naive(r.posted_date) and _to_utc_naive(r.posted_date) >= cutoff)
                    or (_to_utc_naive(r.created_at) and _to_utc_naive(r.created_at) >= cutoff)
                )
            ]
        filtered = _filter_serialized_rows(
            serialized,
            remote_pref,
            req.min_salary,
            req.salary_required,
            req.exclude_confidential,
            profile_skills=profile_skills,
            profile_hobbies=profile_hobbies,
        )

        if query and not filtered:
            fallback_rows = list_jobs(db, {"q": None, "limit": db_row_limit})
            fallback_serialized = _serialize_rows_with_dynamic_distance(
                rows=fallback_rows,
                db=db,
                base_zip=requested_zip,
                max_distance=req.max_distance,
            )
            filtered = _filter_serialized_rows(
                fallback_serialized,
                remote_pref,
                req.min_salary,
                req.salary_required,
                req.exclude_confidential,
                profile_skills=profile_skills,
                profile_hobbies=profile_hobbies,
            )
        if query:
            def _relevance(row: JobRead) -> int:
                text = f"{row.title or ''} {row.company or ''} {row.description or ''}".lower()
                return sum(1 for token in expanded_tokens if re.search(rf"\b{re.escape(token)}\b", text))

            filtered.sort(
                key=lambda r: (
                    -_relevance(r),
                    -_expected_value(r),
                    -_final_weighted(r),
                    -(r.interview_score or 0),
                    -(r.potential_match_score or 0),
                    -(r.posted_date.timestamp() if r.posted_date else 0),
                )
            )
        diversified = _diversify_rows_by_company(filtered, max_per_company_first_pass=3 if query else 2)
        result = diversified[:limit]
        if not req.refresh_pool:
            jobs_query_cache.set("search", cache_params, [row.model_dump(mode="json") for row in result])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Search failed: {exc.__class__.__name__}: {exc}") from exc


@router.post("/discover-company-sites", response_model=list[JobRead])
async def discover_company_sites(req: CompanySiteDiscoverRequest, db: Session = Depends(get_db)):
    if not req.company_urls:
        raise HTTPException(status_code=400, detail="company_urls is required")

    query = (req.query or "").strip().lower()
    remote_pref = (req.remote_type or "any").lower().strip()
    if remote_pref not in {"any", "local", "remote", "onsite", "hybrid"}:
        raise HTTPException(status_code=400, detail="remote_type must be any/local/remote/onsite/hybrid")

    profile_skills = _load_profile_skills(db)
    profile_hobbies = _load_profile_hobbies(db)
    touched: dict[int, Job] = {}

    for raw_url in req.company_urls:
        url = (raw_url or "").strip()
        if not url:
            continue
        try:
            sources = await ingestion.discover_company_board_sources(url)
        except Exception:
            continue

        for src in sources:
            try:
                if src["source_type"] == "greenhouse":
                    jobs = await ingestion.fetch_greenhouse(src["token"])
                elif src["source_type"] == "lever":
                    jobs = await ingestion.fetch_lever(src["token"])
                else:
                    jobs = []
            except Exception:
                continue

            for item in jobs:
                if query:
                    haystack = f"{item.get('title', '')} {item.get('company', '')} {item.get('description', '')}".lower()
                    if query not in haystack:
                        continue
                if not _raw_item_matches_profile(item, profile_skills, profile_hobbies):
                    continue
                saved = create_or_update_job(db, item, profile_skills, commit=False)
                touched[saved.id] = saved
    if touched:
        db.commit()

    serialized = _serialize_rows_with_dynamic_distance(
        rows=list(touched.values()),
        db=db,
        base_zip=(req.base_zip or "").strip() or None,
        max_distance=req.max_distance,
    )
    return _filter_serialized_rows(
        serialized,
        remote_pref,
        req.min_salary,
        req.salary_required,
        req.exclude_confidential,
        profile_skills=profile_skills,
        profile_hobbies=profile_hobbies,
    )


@router.get("/recommendations", response_model=list[JobRead])
def recommendations(
    limit: int = Query(default=50, ge=1, le=500),
    base_zip: str | None = Query(default="44224"),
    max_distance: float | None = Query(default=25),
    min_salary: float | None = Query(default=None),
    remote_type: str = Query(default="any"),
    salary_required: bool = Query(default=True),
    exclude_confidential: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    remote_pref = (remote_type or "any").lower().strip()
    if remote_pref not in {"any", "local", "remote", "onsite", "hybrid"}:
        raise HTTPException(status_code=400, detail="remote_type must be any/local/remote/onsite/hybrid")

    cache_params = {
        "limit": limit,
        "base_zip": base_zip,
        "max_distance": max_distance,
        "min_salary": min_salary,
        "remote_type": remote_pref,
        "salary_required": salary_required,
        "exclude_confidential": exclude_confidential,
    }
    cached_rows = jobs_query_cache.get("recommendations", cache_params)
    if cached_rows is not None:
        return [JobRead.model_validate(row) for row in cached_rows]

    profile_skills = _load_profile_skills(db)
    profile_hobbies = _load_profile_hobbies(db)
    candidate_limit = _bounded_candidate_limit(
        limit,
        multiplier=4 if remote_pref == "local" else 6,
        minimum=80 if remote_pref == "local" else 120,
        maximum=260 if remote_pref == "local" else 480,
    )
    list_filters: dict[str, Any] = {"limit": candidate_limit}
    if salary_required:
        list_filters["salary_present"] = True
    if remote_pref in {"remote", "onsite", "hybrid"}:
        list_filters["remote_type"] = remote_pref
    rows = list_jobs(db, list_filters)
    serialized = _serialize_rows_with_dynamic_distance(rows=rows, db=db, base_zip=base_zip, max_distance=max_distance)

    if remote_pref != "any":
        serialized = [r for r in serialized if _remote_type_matches(remote_pref, r.remote_type or "unknown")]
    serialized = _filter_serialized_rows(
        rows=serialized,
        remote_pref=remote_pref,
        min_salary=min_salary,
        salary_required=salary_required,
        exclude_confidential=exclude_confidential,
        profile_skills=profile_skills,
        profile_hobbies=profile_hobbies,
    )

    serialized.sort(
        key=lambda r: (
            -_expected_value(r),
            -_final_weighted(r),
            -(r.potential_match_score or 0),
            -(r.interview_score or 0),
            -(r.posted_date.timestamp() if r.posted_date else 0),
        )
    )
    diversified = _diversify_rows_by_company(serialized, max_per_company_first_pass=2)
    result = diversified[:limit]
    jobs_query_cache.set("recommendations", cache_params, [row.model_dump(mode="json") for row in result])
    return result


@router.post("/recommendations/national", response_model=list[JobRead])
async def nationwide_recommendations(req: NationwideRecommendationRequest, db: Session = Depends(get_db)):
    remote_pref = (req.remote_type or "any").lower().strip()
    if remote_pref not in {"any", "local", "remote", "onsite", "hybrid"}:
        raise HTTPException(status_code=400, detail="remote_type must be any/local/remote/onsite/hybrid")

    query = (req.query or "").strip()
    city = (req.city or "").strip() or None
    zip_code = (req.zip_code or "").strip() or None
    if zip_code and not re.fullmatch(r"\d{5}", zip_code):
        raise HTTPException(status_code=400, detail="zip_code must be a 5-digit ZIP")

    state_name, state_code = _normalize_state_value(req.state)
    cache_params = req.model_dump()
    if not req.refresh_pool:
        cached_rows = jobs_query_cache.get("recommendations_national", cache_params)
        if cached_rows is not None:
            return [JobRead.model_validate(row) for row in cached_rows]

    if req.refresh_pool:
        queued = enqueue_refresh(
            _refresh_queue_key("national", req.model_dump(mode="python")),
            _refresh_national_pool_async,
            req.model_dump(mode="python"),
        )
        if queued:
            mark_refresh_queued("nationwide")

    search_locations, nationwide_scope = _build_national_locations(city, state_name, state_code, zip_code)
    profile = _load_profile_record(db)
    profile_skills = _load_profile_skills(db, profile)
    profile_hobbies = _load_profile_hobbies(db, profile)
    base_zip = ((req.base_zip or _load_profile_zip(db, profile) or settings.base_zip) or "").strip() or None

    db_row_limit = _bounded_candidate_limit(req.limit, multiplier=12, minimum=220, maximum=900)
    rows = list_jobs(db, {"q": query or None, "limit": db_row_limit})

    serialized = _serialize_rows_with_dynamic_distance(rows=rows, db=db, base_zip=base_zip, max_distance=None)
    filtered = _filter_serialized_rows(
        rows=serialized,
        remote_pref=remote_pref,
        min_salary=req.min_salary,
        salary_required=req.salary_required,
        exclude_confidential=req.exclude_confidential,
        profile_skills=profile_skills,
        profile_hobbies=profile_hobbies,
    )

    if nationwide_scope:
        allowed_state_codes = {
            code
            for code, name in US_STATE_ABBREV_TO_NAME.items()
            if name in CONTIGUOUS_US_STATES
        }
        filtered = [
            row
            for row in filtered
            if (row.remote_type or "").lower() == "remote" or (_row_state_code(row) in allowed_state_codes)
        ]
    else:
        filtered = [
            row
            for row in filtered
            if _row_matches_area(
                row=row,
                city=city,
                state_name=state_name,
                state_code=state_code,
                zip_code=zip_code,
                max_distance=req.max_distance,
            )
        ]

    min_interview = max(0.0, min(10.0, req.min_interview_score_10))
    min_compatibility = max(0.0, min(10.0, req.min_compatibility_score_10))

    def _compatibility_10(row: JobRead) -> float:
        return float(row.compatibility_score_10 or row.potential_match_score_10 or 0)

    strict_ranked = [
        row
        for row in filtered
        if float(row.interview_score_10 or 0) >= min_interview and _compatibility_10(row) >= min_compatibility
    ]

    ranked = strict_ranked
    if req.adaptive_thresholds and len(ranked) < req.limit:
        by_id: dict[int, JobRead] = {row.id: row for row in ranked}
        relax_steps = [
            (max(7.5, min_interview - 0.5), max(6.5, min_compatibility - 0.5)),
            (max(7.0, min_interview - 1.0), max(6.0, min_compatibility - 1.0)),
            (max(6.0, min_interview - 1.5), max(5.5, min_compatibility - 1.5)),
            (max(5.0, min_interview - 2.5), max(4.5, min_compatibility - 2.5)),
        ]
        for step_interview, step_compat in relax_steps:
            for row in filtered:
                if row.id in by_id:
                    continue
                if float(row.interview_score_10 or 0) >= step_interview and _compatibility_10(row) >= step_compat:
                    by_id[row.id] = row
            if len(by_id) >= req.limit * 2:
                break
        ranked = list(by_id.values())

    if len(ranked) < req.limit and filtered:
        present = {row.id for row in ranked}
        fill_candidates = [row for row in filtered if row.id not in present]
        fill_candidates.sort(
            key=lambda r: (
                -_expected_value(r),
                -_final_weighted(r),
                -(_compatibility_10(r)),
                -(r.interview_score_10 or 0),
                -(r.pay_max or r.pay_min or 0),
                -(r.company_sentiment_score_10 or 0),
                -(r.posted_date.timestamp() if r.posted_date else 0),
            )
        )
        ranked.extend(fill_candidates[: max(0, req.limit - len(ranked))])

    ranked.sort(
        key=lambda r: (
            -_expected_value(r),
            -_final_weighted(r),
            -(_compatibility_10(r)),
            -(r.interview_score_10 or 0),
            -(r.pay_max or r.pay_min or 0),
            -(r.company_sentiment_score_10 or 0),
            -(r.posted_date.timestamp() if r.posted_date else 0),
        )
    )
    diversified = _diversify_rows_by_company(ranked, max_per_company_first_pass=1 if nationwide_scope else 2)
    result = diversified[: req.limit]
    if not req.refresh_pool:
        jobs_query_cache.set("recommendations_national", cache_params, [row.model_dump(mode="json") for row in result])
    return result


@router.get("/dashboard/metrics", response_model=DashboardResponse)
def dashboard(db: Session = Depends(get_db)):
    return DashboardResponse(**get_dashboard_metrics(db))


@router.get("/export/csv")
def export_csv(db: Session = Depends(get_db)):
    rows = [_serialize_job(r).model_dump() for r in list_jobs(db, {})]
    return {"csv": ingestion.to_csv(rows)}


@router.post("/ingest", response_model=list[JobRead])
async def ingest_jobs(request: IngestRequest, db: Session = Depends(get_db)):
    source = request.source.lower().strip()
    payload = request.payload

    profile_skills = payload.get("profile_skills", [])
    normalized: list[dict[str, Any]] = []

    if source == "manual":
        normalized = [ingestion.normalize_job(payload, "manual")]
    elif source == "csv":
        normalized = ingestion.parse_csv_content(payload.get("csv_content", ""))
    elif source == "greenhouse":
        normalized = await ingestion.fetch_greenhouse(payload["board_token"])
    elif source == "lever":
        normalized = await ingestion.fetch_lever(payload["company_slug"])
    elif source == "adzuna":
        normalized = await ingestion.fetch_adzuna(
            payload["app_id"],
            payload["app_key"],
            payload.get("where", "Akron"),
            payload.get("what", "data analyst"),
            payload.get("page", 1),
        )
    elif source == "rss":
        normalized = await ingestion.fetch_rss(payload["rss_url"])
    elif source == "themuse":
        normalized = await ingestion.fetch_themuse(
            payload.get("location", "Akron, OH"),
            payload.get("category"),
            payload.get("page", 1),
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported source")

    results = [create_or_update_job(db, item, profile_skills, commit=False) for item in normalized]
    if results:
        db.commit()
        invalidate_jobs_query_cache()
    return [_serialize_job(r) for r in results]


@router.post("/bulk-action", response_model=BulkActionResponse)
def bulk_action(req: BulkActionRequest, db: Session = Depends(get_db)):
    action = (req.action or "").lower().strip()
    updated = 0
    deleted = 0

    if action not in {"apply", "save", "delete", "not_interested"}:
        raise HTTPException(status_code=400, detail="Action must be apply/save/delete/not_interested")

    jobs = db.query(Job).filter(Job.id.in_(req.ids)).all() if req.ids else []

    for job in jobs:
        if action == "delete":
            material = db.query(JobMaterial).filter(JobMaterial.job_id == job.id).first()
            if material:
                db.delete(material)
            db.delete(job)
            deleted += 1
            continue

        old_status = (job.status or "").lower()
        if action == "apply":
            job.status = "applied"
        elif action == "save":
            job.status = "saved"
        else:
            job.status = "rejected"
        _apply_applied_followup_rule(job, old_status)
        job.updated_at = datetime.utcnow()
        db.add(job)
        updated += 1

    db.commit()
    if updated or deleted:
        invalidate_jobs_query_cache()
    return BulkActionResponse(updated=updated, deleted=deleted)


@router.post("/rescore-all", response_model=RescoreAllResponse)
def rescore_all_jobs(db: Session = Depends(get_db)):
    profile = _load_profile_record(db)
    if not profile:
        profile = UserProfile(
            skills_json=json.dumps([]),
            hobbies_json=json.dumps([]),
            distance_miles=30,
            score_tuning_mode="balanced",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    profile_skills = _load_profile_skills(db, profile)
    profile_hobbies = _load_profile_hobbies(db, profile)
    score_tuning_mode = _load_profile_score_tuning_mode(db, profile)
    base_zip = _load_profile_zip(db, profile) or settings.base_zip
    now = datetime.utcnow()

    rescored_count = 0
    jobs = db.scalars(select(Job)).all()
    for job in jobs:
        try:
            extracted_skills = json.loads(job.extracted_skills or "[]")
        except json.JSONDecodeError:
            extracted_skills = []
        if not extracted_skills:
            extracted_skills = extract_skills(job.description)
            job.extracted_skills = json.dumps(extracted_skills)

        distance_value = job.distance_miles
        if (job.remote_type or "").lower() != "remote":
            distance_value = _best_distance_from_location(
                base_zip=base_zip,
                location_text=job.location_text,
                city=job.city,
                state=job.state,
            )

        try:
            previous_breakdown = json.loads(job.score_breakdown or "{}")
        except json.JSONDecodeError:
            previous_breakdown = {}
        prev_interview = previous_breakdown.get("interview_chance_percent")
        prev_compatibility = previous_breakdown.get("potential_match_percent")
        prev_expected_value = previous_breakdown.get("expected_value_score")
        if prev_expected_value is None and isinstance(previous_breakdown.get("decision"), dict):
            prev_expected_value = previous_breakdown["decision"].get("expected_value_score")
        prev_final_weighted = previous_breakdown.get("total")
        if prev_final_weighted is None and isinstance(previous_breakdown.get("decision"), dict):
            prev_final_weighted = previous_breakdown["decision"].get("final_weighted_score")
        score, breakdown = score_job(
            title=job.title,
            description=job.description,
            job_skills=extracted_skills,
            profile_skills=profile_skills,
            distance_miles=distance_value,
            remote_type=job.remote_type or "unknown",
            pay_min=job.pay_min,
            pay_max=job.pay_max,
            posted_date=job.posted_date,
            source=job.source or "manual",
            score_tuning_mode=score_tuning_mode,
            profile_hobbies=profile_hobbies,
        )
        if prev_interview is not None:
            breakdown["previous_interview_chance_percent"] = prev_interview
        if prev_compatibility is not None:
            breakdown["previous_potential_match_percent"] = prev_compatibility
        if prev_expected_value is not None:
            breakdown["previous_expected_value_score"] = prev_expected_value
        if prev_final_weighted is not None:
            breakdown["previous_final_weighted_score"] = prev_final_weighted
        breakdown["last_rescored_at"] = now.isoformat()
        job.distance_miles = distance_value
        job.score = score
        job.score_breakdown = json.dumps(breakdown)
        job.updated_at = now
        db.add(job)
        rescored_count += 1

    profile.last_rescored_at = now
    profile.updated_at = now
    db.add(profile)
    db.commit()
    invalidate_jobs_query_cache()
    return RescoreAllResponse(
        rescored_count=rescored_count,
        score_tuning_mode=score_tuning_mode,
        base_zip=base_zip,
        last_rescored_at=now,
    )


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    profile = _load_profile_record(db)
    profile_skills = _load_profile_skills(db, profile)
    profile_hobbies = _load_profile_hobbies(db, profile)
    score_tuning_mode = _load_profile_score_tuning_mode(db, profile)
    try:
        extracted_skills = json.loads(job.extracted_skills or "[]")
    except json.JSONDecodeError:
        extracted_skills = []
    try:
        stored_breakdown = json.loads(job.score_breakdown or "{}")
    except json.JSONDecodeError:
        stored_breakdown = {}
    dynamic_score, dynamic_breakdown = score_job(
        title=job.title,
        description=job.description,
        job_skills=extracted_skills,
        profile_skills=profile_skills,
        distance_miles=job.distance_miles,
        remote_type=job.remote_type or "unknown",
        pay_min=job.pay_min,
        pay_max=job.pay_max,
        posted_date=job.posted_date,
        source=job.source or "manual",
        score_tuning_mode=score_tuning_mode,
        profile_hobbies=profile_hobbies,
    )
    dynamic_breakdown = _merge_rescore_metadata(dynamic_breakdown, stored_breakdown)
    return _serialize_job(job, score_override=dynamic_score, score_breakdown_override=dynamic_breakdown)


@router.patch("/{job_id}", response_model=JobRead)
def update_job(job_id: int, update: JobUpdate, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    old_status = (job.status or "").lower()
    values = update.model_dump(exclude_none=True)
    for key, value in values.items():
        if key in {"reminders", "attachments"}:
            setattr(job, key, json.dumps(value))
        else:
            setattr(job, key, value)

    _apply_applied_followup_rule(job, old_status)

    job.updated_at = datetime.utcnow()
    db.add(job)
    db.commit()
    db.refresh(job)
    invalidate_jobs_query_cache()
    return _serialize_job(job)


@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    material = db.query(JobMaterial).filter(JobMaterial.job_id == job_id).first()
    if material:
        db.delete(material)

    db.delete(job)
    db.commit()
    invalidate_jobs_query_cache()
    return {"ok": True}


@router.post("/{job_id}/materials", response_model=MaterialResponse)
async def materials(job_id: int, req: MaterialRequest, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    stored = db.query(JobMaterial).filter(JobMaterial.job_id == job_id).first()
    if stored:
        return MaterialResponse(
            ats_keywords=json.loads(stored.ats_keywords),
            resume_bullet_suggestions=json.loads(stored.resume_bullet_suggestions),
            cover_letter_draft=stored.cover_letter_draft,
            outreach_message_draft=stored.outreach_message_draft,
        )

    # Privacy guard: hobbies are private recommendation signals and must not appear
    # in employer-facing application materials.
    profile = _load_profile_record(db)
    blocked_hobbies = {_normalize_phrase(x) for x in _load_profile_hobbies(db, profile)}

    def _remove_hobby_terms(values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            term = _normalize_phrase(raw)
            if term and term in blocked_hobbies:
                continue
            cleaned.append(raw)
        return cleaned

    safe_profile_skills = _remove_hobby_terms(req.profile_skills)
    safe_experience_areas = _remove_hobby_terms(req.experience_areas)

    data = await generate_materials(
        title=job.title,
        company=job.company,
        description=job.description,
        profile_skills=safe_profile_skills,
        experience_areas=safe_experience_areas,
        include_cover_letter=req.include_cover_letter,
    )
    return MaterialResponse(
        ats_keywords=data["ats_keywords"],
        resume_bullet_suggestions=data["resume_bullet_suggestions"],
        cover_letter_draft=data.get("cover_letter_draft"),
        outreach_message_draft=data["outreach_message_draft"],
    )


def _load_profile_record(db: Session) -> UserProfile | None:
    return db.scalar(select(UserProfile).order_by(UserProfile.id.asc()))


def _load_profile_skills(db: Session, profile: UserProfile | None = None) -> list[str]:
    profile = profile or _load_profile_record(db)
    if not profile:
        return []
    try:
        return json.loads(profile.skills_json or "[]")
    except json.JSONDecodeError:
        return []


def _load_profile_hobbies(db: Session, profile: UserProfile | None = None) -> list[str]:
    profile = profile or _load_profile_record(db)
    if not profile:
        return []
    try:
        return json.loads(profile.hobbies_json or "[]")
    except json.JSONDecodeError:
        return []


def _load_profile_score_tuning_mode(db: Session, profile: UserProfile | None = None) -> str:
    profile = profile or _load_profile_record(db)
    return normalize_score_tuning_mode(profile.score_tuning_mode if profile else "balanced")


def _load_profile_zip(db: Session, profile: UserProfile | None = None) -> str | None:
    profile = profile or _load_profile_record(db)
    zip_code = (profile.zip_code or "").strip() if profile else ""
    return zip_code or None


def _scores_from_breakdown(breakdown: dict[str, Any], fallback_score: float | None) -> tuple[float | None, float | None]:
    interview = breakdown.get("interview_chance_percent")
    potential = breakdown.get("potential_match_percent")
    try:
        interview_val = float(interview) if interview is not None else fallback_score
    except (TypeError, ValueError):
        interview_val = fallback_score
    try:
        potential_val = float(potential) if potential is not None else None
    except (TypeError, ValueError):
        potential_val = None
    return interview_val, potential_val


def _expected_value(row: JobRead) -> float:
    try:
        return float(row.expected_value_score or 0)
    except (TypeError, ValueError):
        return 0.0


def _final_weighted(row: JobRead) -> float:
    try:
        if row.final_weighted_score is not None:
            return float(row.final_weighted_score)
        return float(row.score or 0)
    except (TypeError, ValueError):
        return 0.0


def _bounded_candidate_limit(base_limit: int, multiplier: int, minimum: int, maximum: int) -> int:
    try:
        requested = int(base_limit)
    except (TypeError, ValueError):
        requested = minimum
    return max(minimum, min(maximum, requested * multiplier))


def _merge_rescore_metadata(dynamic_breakdown: dict[str, Any], stored_breakdown: dict[str, Any]) -> dict[str, Any]:
    merged = dict(dynamic_breakdown or {})
    for key in (
        "previous_interview_chance_percent",
        "previous_potential_match_percent",
        "previous_expected_value_score",
        "previous_final_weighted_score",
        "last_rescored_at",
    ):
        if key in stored_breakdown and key not in merged:
            merged[key] = stored_breakdown[key]
    return merged


def _diversify_rows_by_company(rows: list[JobRead], max_per_company_first_pass: int = 2) -> list[JobRead]:
    if not rows or max_per_company_first_pass <= 0:
        return rows

    buckets: dict[str, list[JobRead]] = {}
    company_order: list[str] = []
    for row in rows:
        company_key = (row.company or "").strip().lower() or f"unknown-{row.id}"
        if company_key not in buckets:
            buckets[company_key] = []
            company_order.append(company_key)
        buckets[company_key].append(row)

    chosen: list[JobRead] = []
    bucket_indexes: dict[str, int] = {k: 0 for k in company_order}
    per_company: dict[str, int] = {k: 0 for k in company_order}
    while True:
        progressed = False
        for company_key in company_order:
            idx = bucket_indexes[company_key]
            bucket = buckets[company_key]
            if idx >= len(bucket):
                continue
            if per_company[company_key] >= max_per_company_first_pass:
                continue
            chosen.append(bucket[idx])
            bucket_indexes[company_key] += 1
            per_company[company_key] += 1
            progressed = True
        if not progressed:
            break

    chosen_ids = {row.id for row in chosen}
    remainder = [row for row in rows if row.id not in chosen_ids]
    return [*chosen, *remainder]


def _remote_type_matches(remote_pref: str, remote_type: str) -> bool:
    current = (remote_type or "unknown").lower().strip()
    if remote_pref == "any":
        return True
    if remote_pref == "local":
        return current in {"onsite", "hybrid", "unknown"}
    return current == remote_pref


def _is_suspicious_pay(pay_min: float | None, pay_max: float | None, pay_text: str | None) -> bool:
    values = [float(v) for v in [pay_min, pay_max] if v is not None]
    if not values:
        return False
    low = min(values)
    high = max(values)
    text = (pay_text or "").lower()
    hourly_hint = any(tok in text for tok in ["hour", "/hr", "hourly", "/h"])
    annual_hint = any(tok in text for tok in ["year", "/yr", "/year", "annual"])

    if high >= 10000 and low < 10 and not hourly_hint:
        return True
    if high <= 7 and not hourly_hint:
        return True
    if annual_hint and high < 10000:
        return True
    return False


def _has_salary(job: JobRead) -> bool:
    if _is_suspicious_pay(job.pay_min, job.pay_max, job.pay_text):
        return False
    if (job.pay_max or job.pay_min) is not None:
        return True
    text = (job.pay_text or "").strip().lower()
    if not text:
        return False
    return "not listed" not in text


def _is_confidential_employer(company: str | None) -> bool:
    text = (company or "").strip().lower()
    if not text:
        return False
    return any(term in text for term in ["confidential", "stealth", "undisclosed"])


def _filter_serialized_rows(
    rows: list[JobRead],
    remote_pref: str,
    min_salary: float | None,
    salary_required: bool,
    exclude_confidential: bool,
    profile_skills: list[str] | None = None,
    profile_hobbies: list[str] | None = None,
) -> list[JobRead]:
    out = [
        r
        for r in rows
        if _job_is_relevant_to_profile(
            title=r.title,
            description=r.description,
            extracted_skills=r.extracted_skills,
            profile_skills=profile_skills,
            profile_hobbies=profile_hobbies,
            potential_match_score=r.potential_match_score,
            interview_score=r.interview_score,
        )
    ]
    if remote_pref != "any":
        out = [r for r in out if _remote_type_matches(remote_pref, r.remote_type or "unknown")]
    if salary_required:
        out = [r for r in out if _has_salary(r)]
    if exclude_confidential:
        out = [r for r in out if not _is_confidential_employer(r.company)]
    if min_salary is not None:
        out = [r for r in out if ((r.pay_max or r.pay_min) is not None and (r.pay_max or r.pay_min or 0) >= min_salary)]
    return out


def _location_looks_local(base_zip: str, location_text: str | None) -> bool:
    text = (location_text or "").lower()
    if not text:
        return False
    city_state = ZIP_CITY_STATE.get(base_zip)
    if not city_state:
        return False
    city, state = city_state
    state_tokens = {state.lower(), "oh", "ohio"} if state else set()
    city_tokens = {city.lower()} if city else set()
    nearby_tokens = {
        "akron",
        "cleveland",
        "stow",
        "kent",
        "hudson",
        "cuyahoga falls",
        "tallmadge",
        "twinsburg",
        "aurora",
        "medina",
        "canton",
        "strongsville",
        "wadsworth",
        "barberton",
        "new philadelphia",
    }
    if city_tokens.intersection(set(text.split())):
        return True
    if any(tok in text for tok in nearby_tokens) and any(tok in text for tok in state_tokens):
        return True
    if any(tok in text for tok in city_tokens) and any(tok in text for tok in state_tokens):
        return True
    return False


def _best_distance_from_location(
    base_zip: str,
    location_text: str | None,
    city: str | None,
    state: str | None,
) -> float | None:
    candidates: set[str] = set()

    primary = infer_zip_from_location(location_text, city=city, state=state)
    if primary:
        candidates.add(primary)

    text = location_text or ""
    for m in re.findall(r"\b(\d{5})\b", text):
        candidates.add(m)

    for match in re.finditer(r"([A-Za-z][A-Za-z .'\-]{1,40}),\s*([A-Za-z]{2})", text):
        city_name = (match.group(1) or "").strip().lower()
        state_code = (match.group(2) or "").strip().lower()
        zip_code = CITY_STATE_TO_ZIP.get((city_name, state_code))
        if zip_code:
            candidates.add(zip_code)

    distances = [distance_from_base_zip(base_zip, z) for z in candidates]
    distances = [d for d in distances if d is not None]
    return min(distances) if distances else None


def _serialize_rows_with_dynamic_distance(
    rows: list[Job],
    db: Session,
    base_zip: str | None,
    max_distance: float | None,
) -> list[JobRead]:
    profile = _load_profile_record(db)
    profile_skills = _load_profile_skills(db, profile)
    profile_hobbies = _load_profile_hobbies(db, profile)
    score_tuning_mode = _load_profile_score_tuning_mode(db, profile)
    normalized_zip = base_zip.strip() if base_zip else None
    output: list[JobRead] = []
    for row in rows:
        dynamic_distance = row.distance_miles
        if row.remote_type != "remote" and normalized_zip:
            dynamic_distance = _best_distance_from_location(
                base_zip=normalized_zip,
                location_text=row.location_text,
                city=row.city,
                state=row.state,
            )
        if max_distance is not None and normalized_zip:
            if row.remote_type == "remote":
                pass
            elif dynamic_distance is None:
                if not _location_looks_local(normalized_zip, row.location_text):
                    continue
            elif dynamic_distance > max_distance:
                if _location_looks_local(normalized_zip, row.location_text):
                    # Multi-location postings sometimes list both local and non-local sites.
                    dynamic_distance = round(max_distance, 2)
                else:
                    continue

        extracted_skills = json.loads(row.extracted_skills or "[]")
        dynamic_score, dynamic_breakdown = score_job(
            title=row.title,
            description=row.description,
            job_skills=extracted_skills,
            profile_skills=profile_skills,
            distance_miles=dynamic_distance,
            remote_type=row.remote_type or "unknown",
            pay_min=row.pay_min,
            pay_max=row.pay_max,
            posted_date=row.posted_date,
            source=row.source or "manual",
            score_tuning_mode=score_tuning_mode,
            profile_hobbies=profile_hobbies,
        )
        try:
            stored_breakdown = json.loads(row.score_breakdown or "{}")
        except json.JSONDecodeError:
            stored_breakdown = {}
        dynamic_breakdown = _merge_rescore_metadata(dynamic_breakdown, stored_breakdown)
        output.append(
            _serialize_job(
                row,
                distance_override=dynamic_distance,
                force_distance_override=True,
                score_override=dynamic_score,
                score_breakdown_override=dynamic_breakdown,
            )
        )

    output.sort(
        key=lambda j: (
            j.distance_miles is None,
            j.distance_miles if j.distance_miles is not None else 9999,
            -(j.score or 0),
            -(j.posted_date.timestamp() if j.posted_date else 0),
        )
    )
    return output


def _serialize_job(
    job: Job,
    distance_override: float | None = None,
    force_distance_override: bool = False,
    score_override: float | None = None,
    score_breakdown_override: dict[str, Any] | None = None,
) -> JobRead:
    breakdown = json.loads(job.score_breakdown or "{}") if score_breakdown_override is None else score_breakdown_override
    interview_score, potential_match_score = _scores_from_breakdown(breakdown, score_override if score_override is not None else job.score)
    interview_score_10 = round((interview_score or 0) / 10, 1) if interview_score is not None else None
    potential_match_score_10 = round((potential_match_score or 0) / 10, 1) if potential_match_score is not None else None
    prev_interview = breakdown.get("previous_interview_chance_percent") if isinstance(breakdown, dict) else None
    prev_compatibility = breakdown.get("previous_potential_match_percent") if isinstance(breakdown, dict) else None
    try:
        interview_drift_10 = round(((float(interview_score) - float(prev_interview)) / 10), 1) if interview_score is not None and prev_interview is not None else None
    except (TypeError, ValueError):
        interview_drift_10 = None
    try:
        compatibility_drift_10 = round(((float(potential_match_score) - float(prev_compatibility)) / 10), 1) if potential_match_score is not None and prev_compatibility is not None else None
    except (TypeError, ValueError):
        compatibility_drift_10 = None
    sentiment_score_10 = _estimate_company_sentiment_score_10(job.company, job.description, job.source)
    components = breakdown.get("components", {}) if isinstance(breakdown, dict) else {}
    decision = breakdown.get("decision", {}) if isinstance(breakdown, dict) else {}
    role_family_data = breakdown.get("role_family", {}) if isinstance(breakdown, dict) else {}
    if not isinstance(decision, dict):
        decision = {}
    if not isinstance(role_family_data, dict):
        role_family_data = {}
    resume_signal_available = bool(breakdown.get("resume_signal_available", True)) if isinstance(breakdown, dict) else True
    role_c = float(components.get("role", 0) or 0)
    skills_c = float(components.get("skills", 0) or 0)
    skills_direct_c = float(components.get("skills_direct", skills_c) or 0)
    skills_transferable_c = float(components.get("skills_transferable", 0) or 0)
    distance_c = float(components.get("distance", 0) or 0)
    freshness_c = float(components.get("freshness", 0) or 0)
    salary_c = float(components.get("salary", 0) or 0)
    resume_strength_c = float(components.get("resume_strength", 0) or 0)
    seniority_multiplier = float(components.get("seniority_multiplier", 1.0) or 1.0)
    seniority_signal = str(breakdown.get("seniority_signal", "neutral")) if isinstance(breakdown, dict) else "neutral"
    score_tuning_mode = str(breakdown.get("score_tuning_mode", "balanced")) if isinstance(breakdown, dict) else "balanced"
    requirements_ignored = int(breakdown.get("requirements_ignored_count", 0) or 0) if isinstance(breakdown, dict) else 0
    skill_signals = breakdown.get("skill_signals", {}) if isinstance(breakdown, dict) else {}
    direct_overlap = int(skill_signals.get("direct_overlap_count", 0) or 0)
    transferable_overlap = int(skill_signals.get("transferable_group_count", 0) or 0)

    def _score10(raw: Any) -> float | None:
        try:
            if raw is None:
                return None
            return round(float(raw) * 10, 1)
        except (TypeError, ValueError):
            return None

    expected_value_score = None
    try:
        expected_value_score = float(
            decision.get("expected_value_score", breakdown.get("expected_value_score"))
        )
    except (TypeError, ValueError, AttributeError):
        expected_value_score = None

    expected_value_drift = None
    try:
        prev_expected = breakdown.get("previous_expected_value_score") if isinstance(breakdown, dict) else None
        if expected_value_score is not None and prev_expected is not None:
            expected_value_drift = round(float(expected_value_score) - float(prev_expected), 2)
    except (TypeError, ValueError):
        expected_value_drift = None

    final_weighted_score = None
    try:
        final_weighted_score = float(
            decision.get(
                "final_weighted_score",
                breakdown.get("total", score_override if score_override is not None else job.score),
            )
        )
    except (TypeError, ValueError, AttributeError):
        final_weighted_score = None

    confidence_score = None
    confidence_raw = decision.get("confidence")
    try:
        if confidence_raw is not None:
            confidence_score = round(float(confidence_raw) * 100, 2)
        elif isinstance(breakdown, dict) and breakdown.get("confidence_score") is not None:
            confidence_score = float(breakdown.get("confidence_score"))
    except (TypeError, ValueError):
        confidence_score = None

    role_family_key = None
    role_family_label = None
    if isinstance(role_family_data, dict):
        role_family_key = role_family_data.get("key") or decision.get("role_family_key")
        role_family_label = role_family_data.get("label") or decision.get("role_family_label")

    strategy_tag = str(decision.get("strategy_tag")) if decision.get("strategy_tag") else None
    reason_summary = str(decision.get("reason_summary")) if decision.get("reason_summary") else None
    recommended_resume_variant = (
        str(decision.get("recommended_resume_variant")) if decision.get("recommended_resume_variant") else None
    )
    recommended_apply_strategy = (
        str(decision.get("recommended_apply_strategy")) if decision.get("recommended_apply_strategy") else None
    )
    top_matched_qualifications = decision.get("top_matched_qualifications") or []
    top_missing_qualifications = decision.get("top_missing_qualifications") or []

    def _ensure_str_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out

    interview_reason = (
        f"Interview potential is resume-first: role fit {round(role_c*10,1)}/10, direct skills {round(skills_direct_c*10,1)}/10, "
        f"transferable skills {round(skills_transferable_c*10,1)}/10, resume quality {round(resume_strength_c*10,1)}/10; "
        f"distance {round(distance_c*10,1)}/10 and freshness {round(freshness_c*10,1)}/10 are secondary. "
        f"Seniority adjustment: {seniority_signal} ({round(seniority_multiplier,2)}x). "
        f"Requirement text ignored: {requirements_ignored} degree/years phrase(s). Mode: {score_tuning_mode}."
    )
    compatibility_reason = (
        (
            f"Compatibility combines role alignment ({round(role_c*10,1)}/10), direct skill overlap ({round(skills_direct_c*10,1)}/10), "
            f"transferable experience ({round(skills_transferable_c*10,1)}/10), and resume quality ({round(resume_strength_c*10,1)}/10). "
            f"Detected {direct_overlap} direct and {transferable_overlap} transferable match signal(s); ignored {requirements_ignored} degree/years requirement phrase(s)."
        )
        if resume_signal_available
        else (
            f"Compatibility currently uses role alignment only ({round(role_c*10,1)}/10) because resume text/skills were not extracted."
        )
    )
    pay_min = job.pay_min
    pay_max = job.pay_max
    pay_text = job.pay_text
    if _is_suspicious_pay(pay_min, pay_max, pay_text):
        pay_min = None
        pay_max = None
        pay_text = None
    clean_description = _clean_description_text(job.raw_description or job.description)
    return JobRead(
        id=job.id,
        clean_description=clean_description,
        title=job.title,
        company=job.company,
        location_text=job.location_text,
        city=job.city,
        state=job.state,
        remote_type=job.remote_type,
        pay_min=pay_min,
        pay_max=pay_max,
        pay_text=pay_text,
        job_type=job.job_type,
        seniority=job.seniority,
        posted_date=job.posted_date,
        source=job.source,
        url=job.url,
        canonical_url=job.canonical_url,
        description=job.description,
        raw_description=job.raw_description,
        extracted_skills=json.loads(job.extracted_skills or "[]"),
        keywords=json.loads(job.keywords or "[]"),
        distance_miles=distance_override if force_distance_override else (job.distance_miles if distance_override is None else distance_override),
        score=job.score if score_override is None else score_override,
        score_breakdown=breakdown,
        interview_score=interview_score,
        potential_match_score=potential_match_score,
        compatibility_score_10=potential_match_score_10,
        interview_score_10=interview_score_10,
        potential_match_score_10=potential_match_score_10,
        company_sentiment_score_10=sentiment_score_10,
        interview_drift_10=interview_drift_10,
        compatibility_drift_10=compatibility_drift_10,
        interview_reason=interview_reason,
        compatibility_reason=compatibility_reason,
        role_family_key=role_family_key,
        role_family_label=role_family_label,
        expected_value_score=expected_value_score,
        expected_value_drift=expected_value_drift,
        final_weighted_score=final_weighted_score,
        confidence_score=confidence_score,
        strategy_tag=strategy_tag,
        reason_summary=reason_summary,
        hard_match_score_10=_score10(decision.get("hard_match")),
        soft_match_score_10=_score10(decision.get("soft_match")),
        salary_likelihood_score_10=_score10(decision.get("salary_likelihood")),
        application_friction_score_10=_score10(decision.get("application_friction")),
        response_probability_score_10=_score10(decision.get("response_probability")),
        realness_risk_score_10=_score10(decision.get("realness_risk")),
        career_growth_fit_score_10=_score10(decision.get("career_growth_fit")),
        work_style_fit_score_10=_score10(decision.get("work_style_fit")),
        resume_gap_severity_score_10=_score10(decision.get("resume_gap_severity")),
        recommended_resume_variant=recommended_resume_variant,
        recommended_apply_strategy=recommended_apply_strategy,
        top_matched_qualifications=_ensure_str_list(top_matched_qualifications),
        top_missing_qualifications=_ensure_str_list(top_missing_qualifications),
        status=job.status,
        notes=job.notes,
        applied_date=job.applied_date,
        follow_up_date=job.follow_up_date,
        reminders=json.loads(job.reminders or "[]"),
        attachments=json.loads(job.attachments or "[]"),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _estimate_company_sentiment_score_10(company: str | None, description: str | None, source: str | None) -> float:
    # Proxy signal based on listing language + source quality.
    text = (description or "").lower()
    baseline = 5.0 + (SOURCE_TRUST.get((source or "").lower(), 0.6) - 0.6) * 3.0
    positive_terms = [
        "inclusive",
        "wellness",
        "benefits",
        "growth",
        "mentorship",
        "work-life",
        "great place",
        "flexible",
        "career development",
        "supportive",
    ]
    caution_terms = [
        "fast-paced",
        "high pressure",
        "weekends",
        "overtime",
        "on-call",
        "nights",
        "must lift",
        "demanding",
        "stressful",
    ]
    pos = sum(1 for t in positive_terms if t in text)
    neg = sum(1 for t in caution_terms if t in text)
    score = baseline + pos * 0.6 - neg * 0.8
    if company and len(company.strip()) <= 2:
        score -= 0.5
    return round(max(0.0, min(10.0, score)), 1)
