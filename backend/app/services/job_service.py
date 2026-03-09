import json
from datetime import datetime

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.job import Job
from app.models.job_packet_history import JobPacketHistory
from app.models.job_status_event import JobStatusEvent
from app.models.profile import UserProfile
from app.services.dedupe import extract_external_job_keys, is_probable_duplicate
from app.services.distance import distance_from_base_zip, infer_zip_from_location
from app.services.extraction import extract_keywords, extract_skills
from app.services.scoring import normalize_score_tuning_mode, score_job


def _infer_role_category(breakdown: dict) -> str:
    role_family = breakdown.get("role_family")
    if isinstance(role_family, dict):
        label = str(role_family.get("label") or "").strip()
        if label:
            return label
    decision = breakdown.get("decision")
    if isinstance(decision, dict):
        label = str(decision.get("role_family_label") or "").strip()
        if label:
            return label
    matched = breakdown.get("matched_role_categories") or []
    return matched[0] if matched else "other"


def _profile_skills_from_db(db: Session, profile: UserProfile | None = None) -> list[str]:
    profile = profile or db.scalar(select(UserProfile).order_by(UserProfile.id.asc()))
    if not profile:
        return []
    try:
        return json.loads(profile.skills_json or "[]")
    except json.JSONDecodeError:
        return []


def _profile_hobbies_from_db(db: Session, profile: UserProfile | None = None) -> list[str]:
    profile = profile or db.scalar(select(UserProfile).order_by(UserProfile.id.asc()))
    if not profile:
        return []
    try:
        return json.loads(profile.hobbies_json or "[]")
    except json.JSONDecodeError:
        return []


def _profile_from_db(db: Session) -> UserProfile | None:
    return db.scalar(select(UserProfile).order_by(UserProfile.id.asc()))


def _resolve_profile_skills(db: Session, profile_skills: list[str] | None, profile: UserProfile | None = None) -> list[str]:
    supplied = [s.strip() for s in (profile_skills or []) if s and s.strip()]
    if supplied:
        return sorted(set(supplied))
    stored = [s.strip() for s in _profile_skills_from_db(db, profile) if s and s.strip()]
    return sorted(set(stored))


def _resolve_profile_hobbies(db: Session, profile: UserProfile | None = None) -> list[str]:
    stored = [s.strip() for s in _profile_hobbies_from_db(db, profile) if s and s.strip()]
    return sorted(set(stored))


def create_or_update_job(db: Session, payload: dict, profile_skills: list[str], commit: bool = True) -> Job:
    job, _ = create_or_update_job_with_flag(db, payload, profile_skills, commit=commit)
    return job


def create_or_update_job_with_flag(
    db: Session,
    payload: dict,
    profile_skills: list[str],
    commit: bool = True,
) -> tuple[Job, bool]:
    profile = _profile_from_db(db)
    profile_skills = _resolve_profile_skills(db, profile_skills, profile)
    profile_hobbies = _resolve_profile_hobbies(db, profile)
    score_tuning_mode = normalize_score_tuning_mode(profile.score_tuning_mode) if profile else "balanced"
    base_zip = (((profile.zip_code or "").strip() if profile else "") or settings.base_zip)
    canonical_url = payload.get("canonical_url")
    existing: Job | None = None
    incoming_source = str(payload.get("source") or "manual").strip().lower()
    incoming_url = canonical_url or payload.get("url")
    incoming_external_keys = extract_external_job_keys(
        incoming_url,
        source=incoming_source,
        description=payload.get("description"),
    )

    if canonical_url:
        existing = db.scalar(select(Job).where(Job.canonical_url == canonical_url))

    if not existing:
        candidates = db.scalars(select(Job).order_by(Job.updated_at.desc()).limit(500)).all()
        for job in candidates:
            existing_external_keys = extract_external_job_keys(
                job.canonical_url or job.url,
                source=job.source,
                description=job.description,
            )
            if incoming_external_keys and existing_external_keys.intersection(incoming_external_keys):
                existing = job
                break
        if not existing:
            for job in candidates:
                if is_probable_duplicate(
                    existing_company=job.company,
                    existing_title=job.title,
                    existing_location=job.location_text,
                    existing_url=job.canonical_url or job.url,
                    existing_source=job.source,
                    existing_description=job.description,
                    existing_pay_min=job.pay_min,
                    existing_pay_max=job.pay_max,
                    company=payload.get("company"),
                    title=payload.get("title"),
                    location=payload.get("location_text"),
                    url=incoming_url,
                    source=incoming_source,
                    description=payload.get("description"),
                    pay_min=payload.get("pay_min"),
                    pay_max=payload.get("pay_max"),
                ):
                    existing = job
                    break

    if existing and not existing.canonical_url and canonical_url:
        existing.canonical_url = canonical_url
    if existing and not existing.url and payload.get("url"):
        existing.url = payload.get("url")

    extracted_skills = extract_skills(payload.get("description"))
    keywords = extract_keywords(payload.get("description"))

    target_zip = infer_zip_from_location(
        payload.get("location_text"),
        city=payload.get("city"),
        state=payload.get("state"),
    )

    distance = None
    if payload.get("remote_type") != "remote":
        distance = distance_from_base_zip(base_zip, target_zip)

    score, breakdown = score_job(
        title=payload.get("title", ""),
        description=payload.get("description"),
        job_skills=extracted_skills,
        profile_skills=profile_skills,
        distance_miles=distance,
        remote_type=payload.get("remote_type", "unknown"),
        pay_min=payload.get("pay_min"),
        pay_max=payload.get("pay_max"),
        posted_date=payload.get("posted_date"),
        source=payload.get("source", "manual"),
        score_tuning_mode=score_tuning_mode,
        profile_hobbies=profile_hobbies,
    )

    if existing:
        for key, value in payload.items():
            current_value = getattr(existing, key, None)
            if value in (None, "") and current_value not in (None, ""):
                continue
            setattr(existing, key, value)
        existing.extracted_skills = json.dumps(extracted_skills)
        existing.keywords = json.dumps(keywords)
        existing.distance_miles = distance
        existing.score = score
        existing.score_breakdown = json.dumps(breakdown)
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        if commit:
            db.commit()
            db.refresh(existing)
        else:
            db.flush()
        return existing, False

    new_job = Job(
        **payload,
        extracted_skills=json.dumps(extracted_skills),
        keywords=json.dumps(keywords),
        distance_miles=distance,
        score=score,
        score_breakdown=json.dumps(breakdown),
    )
    db.add(new_job)
    if commit:
        db.commit()
        db.refresh(new_job)
    else:
        db.flush()
    return new_job, True


def _jobs_fts_available(db: Session) -> bool:
    row = db.execute(
        text("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = 'jobs_fts' LIMIT 1")
    ).first()
    return row is not None


def _build_fts_match_query(raw_query: str) -> str | None:
    normalized = " ".join(str(raw_query or "").strip().split())
    if not normalized:
        return None

    tokens = []
    for token in normalized.lower().split():
        cleaned = "".join(ch for ch in token if ch.isalnum() or ch in {"+", "#"})
        if len(cleaned) >= 2:
            tokens.append(cleaned)

    if not tokens:
        return None

    parts: list[str] = []
    if len(normalized.split()) > 1:
        escaped_phrase = normalized.replace('"', '""')
        parts.append(f'"{escaped_phrase}"')
    for token in tokens[:8]:
        parts.append(f"{token}*")
    if not parts:
        return None
    return " OR ".join(dict.fromkeys(parts))


def get_job_match_snippets(db: Session, raw_query: str, limit: int = 200) -> dict[int, str]:
    match_query = _build_fts_match_query(str(raw_query or ""))
    if not match_query or not _jobs_fts_available(db):
        return {}

    try:
        search_limit = max(20, min(500, int(limit)))
    except (TypeError, ValueError):
        search_limit = 200

    try:
        rows = db.execute(
            text(
                """
                SELECT
                    rowid,
                    snippet(jobs_fts, 3, '[[', ']]', ' ... ', 18) AS description_snippet,
                    snippet(jobs_fts, -1, '[[', ']]', ' ... ', 18) AS best_snippet
                FROM jobs_fts
                WHERE jobs_fts MATCH :match_query
                ORDER BY bm25(jobs_fts, 8.0, 5.0, 2.0, 1.0)
                LIMIT :search_limit
                """
            ),
            {"match_query": match_query, "search_limit": search_limit},
        ).all()
    except Exception:
        return {}

    snippets: dict[int, str] = {}
    for rowid, description_snippet, best_snippet in rows:
        try:
            job_id = int(rowid)
        except (TypeError, ValueError):
            continue
        snippet_text = str(description_snippet or "").strip()
        if "[[" not in snippet_text or "]]" not in snippet_text:
            snippet_text = str(best_snippet or "").strip()
        if snippet_text:
            snippets[job_id] = snippet_text
    return snippets


def _list_jobs_fts(db: Session, filters: dict) -> list[Job]:
    match_query = _build_fts_match_query(str(filters.get("q") or ""))
    if not match_query or not _jobs_fts_available(db):
        return []

    limit = filters.get("limit")
    try:
        search_limit = max(50, min(500, int(limit) * 4 if limit is not None else 200))
    except (TypeError, ValueError):
        search_limit = 200

    try:
        ids = list(
            db.execute(
                text(
                    """
                    SELECT rowid
                    FROM jobs_fts
                    WHERE jobs_fts MATCH :match_query
                    ORDER BY bm25(jobs_fts, 8.0, 5.0, 2.0, 1.0)
                    LIMIT :search_limit
                    """
                ),
                {"match_query": match_query, "search_limit": search_limit},
            ).scalars()
        )
    except Exception:
        return []

    if not ids:
        return []

    jobs = db.scalars(select(Job).where(Job.id.in_(ids))).all()
    jobs_by_id = {job.id: job for job in jobs}
    ordered = [jobs_by_id[job_id] for job_id in ids if job_id in jobs_by_id]

    if filters.get("status"):
        ordered = [job for job in ordered if job.status == filters["status"]]
    if filters.get("remote_type"):
        ordered = [job for job in ordered if job.remote_type == filters["remote_type"]]
    if filters.get("source"):
        ordered = [job for job in ordered if job.source == filters["source"]]
    if filters.get("max_distance") is not None:
        ordered = [job for job in ordered if job.distance_miles is None or job.distance_miles <= filters["max_distance"]]
    if filters.get("salary_present"):
        ordered = [job for job in ordered if job.pay_min is not None or job.pay_max is not None or bool(job.pay_text)]

    if limit is not None:
        try:
            ordered = ordered[: max(1, int(limit))]
        except (TypeError, ValueError):
            pass
    return ordered


def list_jobs(db: Session, filters: dict) -> list[Job]:
    if filters.get("q"):
        fts_rows = _list_jobs_fts(db, filters)
        if fts_rows:
            return fts_rows

    query = select(Job)
    if filters.get("q"):
        q = f"%{str(filters['q']).strip().lower()}%"
        query = query.where(
            func.lower(Job.title).like(q)
            | func.lower(func.coalesce(Job.company, "")).like(q)
            | func.lower(func.coalesce(Job.location_text, "")).like(q)
            | func.lower(func.coalesce(Job.description, "")).like(q)
        )
    if filters.get("status"):
        query = query.where(Job.status == filters["status"])
    if filters.get("remote_type"):
        query = query.where(Job.remote_type == filters["remote_type"])
    if filters.get("source"):
        query = query.where(Job.source == filters["source"])
    if filters.get("max_distance") is not None:
        query = query.where((Job.distance_miles <= filters["max_distance"]) | (Job.distance_miles.is_(None)))
    if filters.get("salary_present"):
        query = query.where((Job.pay_min.is_not(None)) | (Job.pay_max.is_not(None)) | (Job.pay_text.is_not(None)))

    limit = filters.get("limit")
    if limit is not None:
        try:
            query = query.limit(max(1, int(limit)))
        except (TypeError, ValueError):
            pass

    return list(
        db.scalars(
            query.order_by(
                (Job.distance_miles.is_(None)).asc(),
                Job.distance_miles.asc(),
                desc(Job.score),
                desc(Job.posted_date),
                desc(Job.updated_at),
            )
        ).all()
    )


def get_dashboard_metrics(db: Session) -> dict:
    by_status_rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    by_status = {k: v for k, v in by_status_rows}

    role_counts: dict[str, int] = {}
    for row in db.scalars(select(Job.score_breakdown)).all():
        if not row:
            continue
        data = json.loads(row)
        role = _infer_role_category(data)
        role_counts[role] = role_counts.get(role, 0) + 1

    weekly_rows = db.execute(
        select(func.strftime("%Y-%W", Job.created_at), func.count()).group_by(func.strftime("%Y-%W", Job.created_at))
    ).all()
    weekly = {k: v for k, v in weekly_rows if k}

    jobs = db.scalars(select(Job)).all()
    applied_like_statuses = {"applied", "interview", "final_round", "offer", "declined", "no_response"}
    response_statuses = {"interview", "final_round", "offer"}
    offer_statuses = {"offer"}

    source_rollup: dict[str, dict[str, float | int | str]] = {}
    for job in jobs:
        source = (job.source or "unknown").lower()
        bucket = source_rollup.setdefault(
            source,
            {
                "source": source,
                "total_jobs": 0,
                "active_pipeline": 0,
                "applied_count": 0,
                "interview_count": 0,
                "offer_count": 0,
                "response_rate": 0.0,
                "interview_rate": 0.0,
                "avg_final_score": 0.0,
                "avg_expected_value": 0.0,
                "_score_sum": 0.0,
                "_expected_value_sum": 0.0,
            },
        )
        bucket["total_jobs"] = int(bucket["total_jobs"]) + 1
        status = (job.status or "new").lower()
        if status in {"saved", "applied", "interview", "final_round", "offer"}:
            bucket["active_pipeline"] = int(bucket["active_pipeline"]) + 1
        if status in applied_like_statuses:
            bucket["applied_count"] = int(bucket["applied_count"]) + 1
        if status in response_statuses:
            bucket["interview_count"] = int(bucket["interview_count"]) + 1
        if status in offer_statuses:
            bucket["offer_count"] = int(bucket["offer_count"]) + 1
        try:
            breakdown = json.loads(job.score_breakdown or "{}")
        except json.JSONDecodeError:
            breakdown = {}
        decision = breakdown.get("decision") if isinstance(breakdown, dict) else {}
        if not isinstance(decision, dict):
            decision = {}
        final_score = decision.get("final_weighted_score", breakdown.get("total", job.score))
        expected_value = decision.get("expected_value_score", breakdown.get("expected_value_score"))
        bucket["_score_sum"] = float(bucket["_score_sum"]) + float(final_score or 0.0)
        bucket["_expected_value_sum"] = float(bucket["_expected_value_sum"]) + float(expected_value or 0.0)

    source_performance: list[dict[str, float | int | str]] = []
    for bucket in source_rollup.values():
        total_jobs = max(1, int(bucket["total_jobs"]))
        applied_count = int(bucket["applied_count"])
        interview_count = int(bucket["interview_count"])
        bucket["response_rate"] = round((interview_count / applied_count) * 100, 1) if applied_count else 0.0
        bucket["interview_rate"] = round((interview_count / total_jobs) * 100, 1)
        bucket["avg_final_score"] = round(float(bucket["_score_sum"]) / total_jobs, 1)
        bucket["avg_expected_value"] = round(float(bucket["_expected_value_sum"]) / total_jobs, 1)
        bucket.pop("_score_sum", None)
        bucket.pop("_expected_value_sum", None)
        source_performance.append(bucket)
    source_performance.sort(
        key=lambda row: (
            -float(row["response_rate"]),
            -int(row["offer_count"]),
            -float(row["avg_expected_value"]),
            -int(row["total_jobs"]),
        )
    )

    recent_status_rows = db.scalars(
        select(JobStatusEvent).order_by(JobStatusEvent.created_at.desc()).limit(10)
    ).all()
    recent_activity = [
        {
            "id": row.id,
            "job_id": row.job_id,
            "previous_status": row.previous_status,
            "new_status": row.new_status,
            "action_source": row.action_source,
            "note": row.note,
            "created_at": row.created_at,
        }
        for row in recent_status_rows
    ]

    packet_rows = db.scalars(select(JobPacketHistory).order_by(JobPacketHistory.created_at.desc())).all()
    total_packets = len(packet_rows)
    last_packet_at = packet_rows[0].created_at if packet_rows else None
    packets_last_7_days = 0
    if packet_rows and last_packet_at:
        threshold = datetime.utcnow().timestamp() - (7 * 24 * 60 * 60)
        packets_last_7_days = sum(
            1 for row in packet_rows if row.created_at and row.created_at.timestamp() >= threshold
        )

    response_count = sum(v for k, v in by_status.items() if (k or "").lower() in response_statuses)
    applied_count_total = sum(v for k, v in by_status.items() if (k or "").lower() in applied_like_statuses)
    response_rate = round((response_count / applied_count_total) * 100, 1) if applied_count_total else 0.0

    return {
        "by_status": by_status,
        "by_role_category": role_counts,
        "weekly_trend": weekly,
        "outcome_counts": by_status,
        "response_rate": response_rate,
        "source_performance": source_performance[:8],
        "recent_activity": recent_activity,
        "packet_metrics": {
            "total_generated": total_packets,
            "generated_last_7_days": packets_last_7_days,
            "last_generated_at": last_packet_at,
        },
    }
