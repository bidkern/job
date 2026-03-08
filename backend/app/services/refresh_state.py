from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.refresh_state import RefreshState

REFRESH_SCOPE_LABELS = {
    "local_search": "Local refresh",
    "nationwide": "Nationwide refresh",
}

ACTIVE_REFRESH_STATUSES = {"queued", "running"}


def _get_or_create_state(db, scope: str) -> RefreshState:
    state = db.scalar(select(RefreshState).where(RefreshState.scope == scope))
    if state:
        return state
    state = RefreshState(scope=scope, status="idle", items_written=0)
    db.add(state)
    db.flush()
    return state


def mark_refresh_queued(scope: str) -> None:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        state = _get_or_create_state(db, scope)
        state.status = "queued"
        state.last_enqueued_at = now
        state.updated_at = now
        db.add(state)
        db.commit()
    finally:
        db.close()


def mark_refresh_started(scope: str) -> None:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        state = _get_or_create_state(db, scope)
        state.status = "running"
        state.last_started_at = now
        state.last_error = None
        state.updated_at = now
        db.add(state)
        db.commit()
    finally:
        db.close()


def mark_refresh_finished(scope: str, *, success: bool, items_written: int = 0, error: str | None = None) -> None:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        state = _get_or_create_state(db, scope)
        state.status = "success" if success else "error"
        state.last_finished_at = now
        state.updated_at = now
        state.items_written = max(0, int(items_written))
        if success:
            state.last_success_at = now
            state.last_error = None
        else:
            state.last_error = (error or "Unknown refresh error")[:1000]
        db.add(state)
        db.commit()
    finally:
        db.close()


def list_refresh_states(db) -> list[RefreshState]:
    return list(db.scalars(select(RefreshState).order_by(RefreshState.scope.asc())).all())
