from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AutomationRunResponse(BaseModel):
    run_started_at: datetime
    run_finished_at: datetime | None = None
    sources_processed: int
    ingested_count: int
    updated_count: int
    ready_count: int


class AutomationStatusResponse(BaseModel):
    last_run_at: datetime | None = None
    last_run: AutomationRunResponse | None = None


class JobSourceCreate(BaseModel):
    source_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class JobSourceUpdate(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class JobSourceRead(BaseModel):
    id: int
    source_type: str
    config: dict[str, Any]
    enabled: bool
    last_run_at: datetime | None = None
