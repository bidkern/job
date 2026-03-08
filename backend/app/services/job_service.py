import json
from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.job import Job
from app.models.profile import UserProfile
from app.services.dedupe import is_fuzzy_duplicate
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

    if canonical_url:
        existing = db.scalar(select(Job).where(Job.canonical_url == canonical_url))

    if not existing:
        candidates = db.scalars(select(Job).where(Job.company == payload.get("company"))).all()
        for job in candidates:
            if is_fuzzy_duplicate(
                job.company,
                job.title,
                job.location_text,
                payload.get("company"),
                payload.get("title"),
                payload.get("location_text"),
            ):
                existing = job
                break

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


def list_jobs(db: Session, filters: dict) -> list[Job]:
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

    return {
        "by_status": by_status,
        "by_role_category": role_counts,
        "weekly_trend": weekly,
    }
