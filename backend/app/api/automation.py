import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.job_source import JobSource
from app.schemas.automation import (
    AutomationRunResponse,
    AutomationStatusResponse,
    JobSourceCreate,
    JobSourceRead,
    JobSourceUpdate,
)
from app.services.automation import get_latest_automation_run, run_automation_cycle
from app.services.query_cache import invalidate_jobs_query_cache

router = APIRouter(prefix="/automation", tags=["automation"])


def _serialize_source(src: JobSource) -> JobSourceRead:
    return JobSourceRead(
        id=src.id,
        source_type=src.source_type,
        config=json.loads(src.config_json or "{}"),
        enabled=src.enabled,
        last_run_at=src.last_run_at,
    )


@router.get("/sources", response_model=list[JobSourceRead])
def list_sources(db: Session = Depends(get_db)):
    sources = db.scalars(select(JobSource).order_by(JobSource.id.desc())).all()
    return [_serialize_source(s) for s in sources]


@router.post("/sources", response_model=JobSourceRead)
def add_source(payload: JobSourceCreate, db: Session = Depends(get_db)):
    src = JobSource(source_type=payload.source_type.lower().strip(), config_json=json.dumps(payload.config), enabled=payload.enabled)
    db.add(src)
    db.commit()
    db.refresh(src)
    return _serialize_source(src)


@router.patch("/sources/{source_id}", response_model=JobSourceRead)
def update_source(source_id: int, payload: JobSourceUpdate, db: Session = Depends(get_db)):
    src = db.get(JobSource, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    if payload.enabled is not None:
        src.enabled = payload.enabled
    if payload.config is not None:
        src.config_json = json.dumps(payload.config)
    db.add(src)
    db.commit()
    db.refresh(src)
    return _serialize_source(src)


@router.post("/run-now", response_model=AutomationRunResponse)
async def run_now(db: Session = Depends(get_db)):
    run = await run_automation_cycle(db)
    invalidate_jobs_query_cache()
    return AutomationRunResponse(
        run_started_at=run.run_started_at,
        run_finished_at=run.run_finished_at,
        sources_processed=run.sources_processed,
        ingested_count=run.ingested_count,
        updated_count=run.updated_count,
        ready_count=run.ready_count,
    )


@router.get("/status", response_model=AutomationStatusResponse)
def status(db: Session = Depends(get_db)):
    run = get_latest_automation_run(db)
    if not run:
        return AutomationStatusResponse(last_run_at=None, last_run=None)
    return AutomationStatusResponse(
        last_run_at=run.run_started_at,
        last_run=AutomationRunResponse(
            run_started_at=run.run_started_at,
            run_finished_at=run.run_finished_at,
            sources_processed=run.sources_processed,
            ingested_count=run.ingested_count,
            updated_count=run.updated_count,
            ready_count=run.ready_count,
        ),
    )
