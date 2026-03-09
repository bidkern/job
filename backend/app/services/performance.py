from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.job_packet_history import JobPacketHistory
from app.models.job_status_event import JobStatusEvent


ACTIVE_PIPELINE_STATUSES = {"saved", "applied", "interview", "final_round", "offer", "no_response"}
APPLIED_LIKE_STATUSES = {"applied", "interview", "final_round", "offer", "declined", "no_response"}
RESPONSE_STATUSES = {"interview", "final_round", "offer"}
OFFER_STATUSES = {"offer"}
SCORE_BANDS = [
    (0.0, 40.0, "0-39"),
    (40.0, 55.0, "40-54"),
    (55.0, 70.0, "55-69"),
    (70.0, 85.0, "70-84"),
    (85.0, 101.0, "85-100"),
]


def _safe_breakdown(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _role_family_label(breakdown: dict) -> str:
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
    return str(matched[0]).strip() if matched else "General fallback"


def _score_values(job: Job) -> tuple[float, float]:
    breakdown = _safe_breakdown(job.score_breakdown)
    decision = breakdown.get("decision")
    if not isinstance(decision, dict):
        decision = {}

    final_score = decision.get("final_weighted_score", breakdown.get("total", job.score))
    expected_value = decision.get("expected_value_score", breakdown.get("expected_value_score"))
    try:
        final_score_value = float(final_score or 0.0)
    except (TypeError, ValueError):
        final_score_value = 0.0
    try:
        expected_value_value = float(expected_value or 0.0)
    except (TypeError, ValueError):
        expected_value_value = 0.0
    return final_score_value, expected_value_value


def _bayesian_rate(successes: int, total: int, prior_rate: float, prior_strength: float) -> float:
    if total <= 0:
        return max(0.0, min(1.0, prior_rate))
    adjusted = (float(successes) + (prior_rate * prior_strength)) / (float(total) + prior_strength)
    return max(0.0, min(1.0, adjusted))


def _priority_tier(auto_weight: float) -> str:
    if auto_weight >= 1.05:
        return "boost"
    if auto_weight <= 0.95:
        return "deprioritize"
    return "neutral"


def build_source_performance_rows(jobs: list[Job]) -> list[dict[str, float | int | str]]:
    source_rollup: dict[str, dict[str, float | int | str]] = {}
    global_applied = 0
    global_interviews = 0
    global_offers = 0
    global_ev_sum = 0.0
    global_jobs = 0

    for job in jobs:
        source = (job.source or "unknown").lower().strip() or "unknown"
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
                "offer_rate": 0.0,
                "avg_final_score": 0.0,
                "avg_expected_value": 0.0,
                "auto_weight": 1.0,
                "priority_tier": "neutral",
                "_score_sum": 0.0,
                "_expected_value_sum": 0.0,
            },
        )

        status = (job.status or "new").lower().strip()
        final_score, expected_value = _score_values(job)

        bucket["total_jobs"] = int(bucket["total_jobs"]) + 1
        if status in ACTIVE_PIPELINE_STATUSES:
            bucket["active_pipeline"] = int(bucket["active_pipeline"]) + 1
        if status in APPLIED_LIKE_STATUSES:
            bucket["applied_count"] = int(bucket["applied_count"]) + 1
            global_applied += 1
        if status in RESPONSE_STATUSES:
            bucket["interview_count"] = int(bucket["interview_count"]) + 1
            global_interviews += 1
        if status in OFFER_STATUSES:
            bucket["offer_count"] = int(bucket["offer_count"]) + 1
            global_offers += 1

        bucket["_score_sum"] = float(bucket["_score_sum"]) + final_score
        bucket["_expected_value_sum"] = float(bucket["_expected_value_sum"]) + expected_value
        global_ev_sum += expected_value
        global_jobs += 1

    global_response_rate = (global_interviews / global_applied) if global_applied else 0.18
    global_offer_rate = (global_offers / global_applied) if global_applied else 0.04
    global_avg_ev = (global_ev_sum / global_jobs) if global_jobs else 55.0

    rows: list[dict[str, float | int | str]] = []
    for bucket in source_rollup.values():
        total_jobs = max(1, int(bucket["total_jobs"]))
        applied_count = int(bucket["applied_count"])
        interview_count = int(bucket["interview_count"])
        offer_count = int(bucket["offer_count"])
        avg_final = float(bucket["_score_sum"]) / total_jobs
        avg_ev = float(bucket["_expected_value_sum"]) / total_jobs

        blended_response = _bayesian_rate(interview_count, applied_count, global_response_rate, 6.0)
        blended_offer = _bayesian_rate(offer_count, applied_count, global_offer_rate, 8.0)
        volume_factor = min(1.0, total_jobs / 30.0)
        ev_delta = (avg_ev - global_avg_ev) / 100.0
        auto_weight = 1.0 + volume_factor * (
            ((blended_response - global_response_rate) * 1.15)
            + ((blended_offer - global_offer_rate) * 1.6)
            + (ev_delta * 0.35)
        )
        auto_weight = max(0.82, min(1.2, auto_weight))

        bucket["response_rate"] = round((interview_count / applied_count) * 100, 1) if applied_count else 0.0
        bucket["interview_rate"] = round((interview_count / total_jobs) * 100, 1)
        bucket["offer_rate"] = round((offer_count / applied_count) * 100, 1) if applied_count else 0.0
        bucket["avg_final_score"] = round(avg_final, 1)
        bucket["avg_expected_value"] = round(avg_ev, 1)
        bucket["auto_weight"] = round(auto_weight, 3)
        bucket["priority_tier"] = _priority_tier(auto_weight)
        bucket.pop("_score_sum", None)
        bucket.pop("_expected_value_sum", None)
        rows.append(bucket)

    rows.sort(
        key=lambda row: (
            -float(row["auto_weight"]),
            -float(row["response_rate"]),
            -float(row["offer_rate"]),
            -float(row["avg_expected_value"]),
            -int(row["total_jobs"]),
        )
    )
    return rows


def build_source_weight_map(db: Session) -> dict[str, float]:
    jobs = db.scalars(select(Job)).all()
    return {
        str(row["source"]): float(row.get("auto_weight") or 1.0)
        for row in build_source_performance_rows(jobs)
    }


def build_role_family_performance_rows(jobs: list[Job]) -> list[dict[str, float | int | str]]:
    rollup: dict[str, dict[str, float | int | str]] = {}

    for job in jobs:
        breakdown = _safe_breakdown(job.score_breakdown)
        role_family = _role_family_label(breakdown)
        bucket = rollup.setdefault(
            role_family,
            {
                "role_family": role_family,
                "total_jobs": 0,
                "applied_count": 0,
                "interview_count": 0,
                "offer_count": 0,
                "response_rate": 0.0,
                "offer_rate": 0.0,
                "avg_final_score": 0.0,
                "avg_expected_value": 0.0,
                "_score_sum": 0.0,
                "_expected_value_sum": 0.0,
            },
        )
        status = (job.status or "new").lower().strip()
        final_score, expected_value = _score_values(job)

        bucket["total_jobs"] = int(bucket["total_jobs"]) + 1
        if status in APPLIED_LIKE_STATUSES:
            bucket["applied_count"] = int(bucket["applied_count"]) + 1
        if status in RESPONSE_STATUSES:
            bucket["interview_count"] = int(bucket["interview_count"]) + 1
        if status in OFFER_STATUSES:
            bucket["offer_count"] = int(bucket["offer_count"]) + 1
        bucket["_score_sum"] = float(bucket["_score_sum"]) + final_score
        bucket["_expected_value_sum"] = float(bucket["_expected_value_sum"]) + expected_value

    rows: list[dict[str, float | int | str]] = []
    for bucket in rollup.values():
        total_jobs = max(1, int(bucket["total_jobs"]))
        applied_count = int(bucket["applied_count"])
        interview_count = int(bucket["interview_count"])
        offer_count = int(bucket["offer_count"])
        bucket["response_rate"] = round((interview_count / applied_count) * 100, 1) if applied_count else 0.0
        bucket["offer_rate"] = round((offer_count / applied_count) * 100, 1) if applied_count else 0.0
        bucket["avg_final_score"] = round(float(bucket["_score_sum"]) / total_jobs, 1)
        bucket["avg_expected_value"] = round(float(bucket["_expected_value_sum"]) / total_jobs, 1)
        bucket.pop("_score_sum", None)
        bucket.pop("_expected_value_sum", None)
        rows.append(bucket)

    rows.sort(
        key=lambda row: (
            -float(row["response_rate"]),
            -float(row["offer_rate"]),
            -float(row["avg_expected_value"]),
            -int(row["total_jobs"]),
        )
    )
    return rows


def build_score_band_analytics_rows(jobs: list[Job]) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    for min_score, max_score, label in SCORE_BANDS:
        matching: list[Job] = []
        for job in jobs:
            final_score, _ = _score_values(job)
            if min_score <= final_score < max_score:
                matching.append(job)

        job_count = len(matching)
        applied_count = sum(1 for job in matching if (job.status or "").lower().strip() in APPLIED_LIKE_STATUSES)
        interview_count = sum(1 for job in matching if (job.status or "").lower().strip() in RESPONSE_STATUSES)
        offer_count = sum(1 for job in matching if (job.status or "").lower().strip() in OFFER_STATUSES)
        rows.append(
            {
                "band_label": label,
                "min_score": round(min_score, 1),
                "max_score": round(max_score - (1.0 if max_score >= 101 else 0.1), 1),
                "job_count": job_count,
                "applied_count": applied_count,
                "interview_count": interview_count,
                "offer_count": offer_count,
                "interview_rate": round((interview_count / applied_count) * 100, 1) if applied_count else 0.0,
                "offer_rate": round((offer_count / applied_count) * 100, 1) if applied_count else 0.0,
            }
        )
    return rows


def build_recent_activity_rows(db: Session, limit: int = 10) -> list[dict[str, object]]:
    recent_status_rows = db.scalars(
        select(JobStatusEvent).order_by(JobStatusEvent.created_at.desc()).limit(max(1, min(100, int(limit))))
    ).all()
    return [
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


def build_packet_metrics(db: Session) -> dict[str, object]:
    packet_rows = db.scalars(select(JobPacketHistory).order_by(JobPacketHistory.created_at.desc())).all()
    total_packets = len(packet_rows)
    last_packet_at = packet_rows[0].created_at if packet_rows else None
    packets_last_7_days = 0
    if packet_rows and last_packet_at:
        threshold = datetime.utcnow().timestamp() - (7 * 24 * 60 * 60)
        packets_last_7_days = sum(
            1 for row in packet_rows if row.created_at and row.created_at.timestamp() >= threshold
        )
    return {
        "total_generated": total_packets,
        "generated_last_7_days": packets_last_7_days,
        "last_generated_at": last_packet_at,
    }


def build_workspace_snapshot(
    db: Session,
    *,
    limit_jobs: int = 12,
    limit_packets: int = 12,
) -> dict[str, object]:
    safe_limit_jobs = max(1, min(50, int(limit_jobs)))
    safe_limit_packets = max(1, min(50, int(limit_packets)))
    candidate_jobs = db.scalars(
        select(Job).where(Job.status.in_(tuple(ACTIVE_PIPELINE_STATUSES))).limit(max(80, safe_limit_jobs * 5))
    ).all()

    def _sort_key(job: Job) -> tuple:
        status = (job.status or "new").lower().strip()
        priority_map = {
            "offer": 0,
            "final_round": 1,
            "interview": 2,
            "applied": 3,
            "saved": 4,
            "no_response": 5,
        }
        final_score, expected_value = _score_values(job)
        follow_up = job.follow_up_date or datetime.max
        return (
            priority_map.get(status, 9),
            follow_up,
            -(expected_value or 0.0),
            -(final_score or 0.0),
            -(job.updated_at.timestamp() if job.updated_at else 0.0),
        )

    candidate_jobs.sort(key=_sort_key)
    jobs = candidate_jobs[:safe_limit_jobs]
    job_ids = [job.id for job in jobs]

    latest_packet_by_job: dict[int, JobPacketHistory] = {}
    packet_count_by_job: dict[int, int] = {}
    if job_ids:
        packet_rows = db.scalars(
            select(JobPacketHistory)
            .where(JobPacketHistory.job_id.in_(job_ids))
            .order_by(JobPacketHistory.created_at.desc(), JobPacketHistory.id.desc())
        ).all()
        for row in packet_rows:
            packet_count_by_job[row.job_id] = packet_count_by_job.get(row.job_id, 0) + 1
            latest_packet_by_job.setdefault(row.job_id, row)

    last_status_by_job: dict[int, JobStatusEvent] = {}
    if job_ids:
        status_rows = db.scalars(
            select(JobStatusEvent)
            .where(JobStatusEvent.job_id.in_(job_ids))
            .order_by(JobStatusEvent.created_at.desc(), JobStatusEvent.id.desc())
        ).all()
        for row in status_rows:
            last_status_by_job.setdefault(row.job_id, row)

    recent_packets = db.scalars(
        select(JobPacketHistory).order_by(JobPacketHistory.created_at.desc(), JobPacketHistory.id.desc()).limit(safe_limit_packets)
    ).all()
    packet_job_ids = [row.job_id for row in recent_packets]
    packet_jobs = {
        job.id: job
        for job in db.scalars(select(Job).where(Job.id.in_(packet_job_ids))).all()
    } if packet_job_ids else {}

    follow_up_due = int(
        db.scalar(
            select(func.count()).select_from(Job).where(
                Job.follow_up_date.is_not(None),
                Job.follow_up_date <= datetime.utcnow(),
            )
        )
        or 0
    )
    packet_ready_jobs = int(
        db.scalar(select(func.count(func.distinct(JobPacketHistory.job_id))).select_from(JobPacketHistory)) or 0
    )
    active_jobs_count = int(
        db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(tuple(ACTIVE_PIPELINE_STATUSES)))) or 0
    )
    applied_jobs_count = int(
        db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(tuple(APPLIED_LIKE_STATUSES)))) or 0
    )
    saved_jobs_count = int(db.scalar(select(func.count()).select_from(Job).where(Job.status == "saved")) or 0)

    return {
        "summary": {
            "active_jobs": active_jobs_count,
            "applied_jobs": applied_jobs_count,
            "saved_jobs": saved_jobs_count,
            "follow_up_due": follow_up_due,
            "packet_ready_jobs": packet_ready_jobs,
        },
        "jobs": [
            {
                "job_id": job.id,
                "latest_packet_created_at": latest_packet_by_job.get(job.id).created_at if latest_packet_by_job.get(job.id) else None,
                "latest_packet_generated_via": latest_packet_by_job.get(job.id).generated_via if latest_packet_by_job.get(job.id) else None,
                "latest_packet_text": latest_packet_by_job.get(job.id).packet_text if latest_packet_by_job.get(job.id) else None,
                "packet_count": packet_count_by_job.get(job.id, 0),
                "last_status_event_at": last_status_by_job.get(job.id).created_at if last_status_by_job.get(job.id) else None,
                "last_status_action_source": last_status_by_job.get(job.id).action_source if last_status_by_job.get(job.id) else None,
                "job": job,
            }
            for job in jobs
        ],
        "recent_packets": [
            {
                "id": row.id,
                "job_id": row.job_id,
                "title": packet_jobs.get(row.job_id).title if packet_jobs.get(row.job_id) else "Unknown role",
                "company": packet_jobs.get(row.job_id).company if packet_jobs.get(row.job_id) else None,
                "status": packet_jobs.get(row.job_id).status if packet_jobs.get(row.job_id) else "unknown",
                "url": packet_jobs.get(row.job_id).url if packet_jobs.get(row.job_id) else None,
                "packet_text": row.packet_text,
                "generated_via": row.generated_via,
                "created_at": row.created_at,
            }
            for row in recent_packets
        ],
    }
