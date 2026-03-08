from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobBase(BaseModel):
    title: str
    company: str | None = None
    location_text: str | None = None
    city: str | None = None
    state: str | None = None
    remote_type: str = "unknown"
    pay_min: float | None = None
    pay_max: float | None = None
    pay_text: str | None = None
    job_type: str | None = None
    seniority: str | None = None
    posted_date: datetime | None = None
    source: str = "manual"
    url: str | None = None
    canonical_url: str | None = None
    description: str | None = None
    raw_description: str | None = None
    extracted_skills: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    distance_miles: float | None = None
    score: float | None = None
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
    status: str = "new"
    notes: str | None = None
    applied_date: datetime | None = None
    follow_up_date: datetime | None = None
    reminders: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    applied_date: datetime | None = None
    follow_up_date: datetime | None = None
    reminders: list[str] | None = None
    attachments: list[str] | None = None


class JobRead(JobBase):
    id: int
    clean_description: str | None = None
    match_snippet: str | None = None
    interview_score: float | None = None
    potential_match_score: float | None = None
    compatibility_score_10: float | None = None
    interview_score_10: float | None = None
    potential_match_score_10: float | None = None
    company_sentiment_score_10: float | None = None
    interview_drift_10: float | None = None
    compatibility_drift_10: float | None = None
    interview_reason: str | None = None
    compatibility_reason: str | None = None
    role_family_key: str | None = None
    role_family_label: str | None = None
    expected_value_score: float | None = None
    final_weighted_score: float | None = None
    confidence_score: float | None = None
    strategy_tag: str | None = None
    reason_summary: str | None = None
    expected_value_drift: float | None = None
    hard_match_score_10: float | None = None
    soft_match_score_10: float | None = None
    salary_likelihood_score_10: float | None = None
    application_friction_score_10: float | None = None
    response_probability_score_10: float | None = None
    realness_risk_score_10: float | None = None
    career_growth_fit_score_10: float | None = None
    work_style_fit_score_10: float | None = None
    resume_gap_severity_score_10: float | None = None
    recommended_resume_variant: str | None = None
    recommended_apply_strategy: str | None = None
    top_matched_qualifications: list[str] = Field(default_factory=list)
    top_missing_qualifications: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MaterialRequest(BaseModel):
    profile_skills: list[str] = Field(default_factory=list)
    experience_areas: list[str] = Field(default_factory=list)
    include_cover_letter: bool = False


class MaterialResponse(BaseModel):
    ats_keywords: list[str]
    resume_bullet_suggestions: list[str]
    cover_letter_draft: str | None = None
    outreach_message_draft: str


class IngestRequest(BaseModel):
    source: str
    payload: dict[str, Any]


class JobSearchRequest(BaseModel):
    query: str | None = None
    base_zip: str | None = None
    max_distance: float | None = None
    min_salary: float | None = None
    remote_type: str = "any"
    salary_required: bool = True
    exclude_confidential: bool = True
    created_after: datetime | None = None
    pages: int = 6
    limit: int = 500
    refresh_pool: bool = True


class NationwideRecommendationRequest(BaseModel):
    query: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    base_zip: str | None = None
    max_distance: float | None = None
    min_salary: float | None = None
    remote_type: str = "any"
    salary_required: bool = True
    exclude_confidential: bool = True
    min_interview_score_10: float = Field(default=8.0, ge=0, le=10)
    min_compatibility_score_10: float = Field(default=7.0, ge=0, le=10)
    limit: int = Field(default=25, ge=1, le=100)
    pages_per_region: int = Field(default=2, ge=1, le=5)
    refresh_pool: bool = True
    adaptive_thresholds: bool = True


class CompanySiteDiscoverRequest(BaseModel):
    company_urls: list[str] = Field(default_factory=list)
    query: str | None = None
    base_zip: str | None = None
    max_distance: float | None = None
    min_salary: float | None = None
    remote_type: str = "any"
    salary_required: bool = True
    exclude_confidential: bool = True


class DashboardResponse(BaseModel):
    by_status: dict[str, int]
    by_role_category: dict[str, int]
    weekly_trend: dict[str, int]


class BulkActionRequest(BaseModel):
    ids: list[int] = Field(default_factory=list)
    action: str


class BulkActionResponse(BaseModel):
    updated: int = 0
    deleted: int = 0


class RescoreAllResponse(BaseModel):
    rescored_count: int = 0
    score_tuning_mode: str = "balanced"
    base_zip: str | None = None
    last_rescored_at: datetime


class RefreshScopeRead(BaseModel):
    scope: str
    label: str
    status: str
    active: bool = False
    last_enqueued_at: datetime | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    items_written: int = 0
    updated_at: datetime | None = None


class RefreshStatusResponse(BaseModel):
    last_source_refresh_at: datetime | None = None
    scopes: list[RefreshScopeRead] = Field(default_factory=list)


class RefreshNowRequest(BaseModel):
    query: str | None = None
    base_zip: str | None = None
    max_distance: float | None = None
    min_salary: float | None = None
    local_remote_type: str = "local"
    nationwide_remote_type: str = "any"
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    min_interview_score_10: float = Field(default=5.5, ge=0, le=10)
    min_compatibility_score_10: float = Field(default=6.5, ge=0, le=10)
    local_pages: int = Field(default=4, ge=1, le=6)
    local_limit: int = Field(default=160, ge=1, le=300)
    nationwide_limit: int = Field(default=25, ge=1, le=100)
    refresh_local: bool = True
    refresh_nationwide: bool = True


class RefreshNowResponse(BaseModel):
    queued_scopes: list[str] = Field(default_factory=list)
    already_running_scopes: list[str] = Field(default_factory=list)
