import json
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.automation_run import AutomationRun
from app.models.job import Job
from app.models.job_material import JobMaterial
from app.models.job_source import JobSource
from app.services import ingestion
from app.services.job_service import create_or_update_job_with_flag
from app.services.materials import generate_materials


def _safe_config_source(source_type: str, config: dict) -> dict:
    if source_type != "adzuna":
        return config

    cfg = dict(config)
    cfg.setdefault("app_id", getattr(settings, "adzuna_app_id", None))
    cfg.setdefault("app_key", getattr(settings, "adzuna_app_key", None))
    return cfg


async def _fetch_for_source(source_type: str, config: dict) -> list[dict]:
    source_type = source_type.lower().strip()
    if source_type == "greenhouse":
        return await ingestion.fetch_greenhouse(config["board_token"])
    if source_type == "lever":
        return await ingestion.fetch_lever(config["company_slug"])
    if source_type == "adzuna":
        cfg = _safe_config_source(source_type, config)
        if not cfg.get("app_id") or not cfg.get("app_key"):
            raise ValueError("Adzuna source missing app_id/app_key")
        return await ingestion.fetch_adzuna(
            cfg["app_id"],
            cfg["app_key"],
            cfg.get("where", "Akron, OH"),
            cfg.get("what", "data analyst"),
            cfg.get("page", 1),
        )
    if source_type == "rss":
        return await ingestion.fetch_rss(config["rss_url"])
    if source_type == "themuse":
        return await ingestion.fetch_themuse(
            config.get("location", "Akron, OH"),
            config.get("category"),
            config.get("page", 1),
        )
    if source_type == "csv":
        return ingestion.parse_csv_content(config.get("csv_content", ""))
    if source_type == "manual":
        return [ingestion.normalize_job(config, "manual")]
    raise ValueError(f"Unsupported source_type: {source_type}")


async def _precompute_materials_for_ready_jobs(db: Session) -> None:
    ready_jobs = db.scalars(select(Job).where(Job.status == "ready")).all()
    for job in ready_jobs:
        existing = db.scalar(select(JobMaterial).where(JobMaterial.job_id == job.id))
        if existing:
            continue

        result = await generate_materials(
            title=job.title,
            company=job.company,
            description=job.description,
            profile_skills=[],
            experience_areas=["Relevant work experience"],
            include_cover_letter=True,
        )
        db.add(
            JobMaterial(
                job_id=job.id,
                ats_keywords=json.dumps(result.get("ats_keywords", [])),
                resume_bullet_suggestions=json.dumps(result.get("resume_bullet_suggestions", [])),
                cover_letter_draft=result.get("cover_letter_draft"),
                outreach_message_draft=result.get("outreach_message_draft", ""),
                openai_used=bool(result.get("openai_used")),
            )
        )
    db.commit()


async def run_automation_cycle(db: Session) -> AutomationRun:
    run = AutomationRun(run_started_at=datetime.utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)

    sources = db.scalars(select(JobSource).where(JobSource.enabled.is_(True))).all()
    sources_processed = 0
    ingested_count = 0
    updated_count = 0
    ready_count = 0

    for source in sources:
        sources_processed += 1
        try:
            config = json.loads(source.config_json or "{}")
        except json.JSONDecodeError:
            config = {}

        try:
            profile_skills = config.get("profile_skills", [])
            normalized_jobs = await _fetch_for_source(source.source_type, config)
            for item in normalized_jobs:
                job, created = create_or_update_job_with_flag(db, item, profile_skills)
                if created:
                    ingested_count += 1
                else:
                    updated_count += 1

                if (job.score or 0) >= 75 and (job.status or "new") in {"new", "saved"}:
                    job.status = "ready"
                    db.add(job)
                    ready_count += 1

            source.last_run_at = datetime.utcnow()
            db.add(source)
            db.commit()
        except Exception:
            # Keep automation resilient: one bad source should not block all others.
            db.rollback()
            continue

    if settings.openai_enabled:
        await _precompute_materials_for_ready_jobs(db)

    run.sources_processed = sources_processed
    run.ingested_count = ingested_count
    run.updated_count = updated_count
    run.ready_count = ready_count
    run.run_finished_at = datetime.utcnow()
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_latest_automation_run(db: Session) -> AutomationRun | None:
    return db.scalar(select(AutomationRun).order_by(desc(AutomationRun.run_started_at)))
