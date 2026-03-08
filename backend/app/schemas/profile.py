from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ScoreTuningMode = Literal["strict", "balanced", "aggressive"]


class ProfileBase(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    zip_code: str | None = None
    distance_miles: float | None = None
    skills: list[str] = Field(default_factory=list)
    hobbies: list[str] = Field(default_factory=list)
    score_tuning_mode: ScoreTuningMode = "balanced"
    resume_path: str | None = None
    resume_filename: str | None = None


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    zip_code: str | None = None
    distance_miles: float | None = None
    skills: list[str] | None = None
    hobbies: list[str] | None = None
    score_tuning_mode: ScoreTuningMode | None = None


class ProfileRead(ProfileBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_rescored_at: datetime | None = None


class ResumeUploadResponse(BaseModel):
    resume_path: str
    resume_filename: str
    extracted_skills_count: int = 0
    warning: str | None = None
