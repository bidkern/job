import json
from datetime import datetime, timedelta

from app.models.job import Job
from app.services.performance import build_role_family_performance_rows, build_score_band_analytics_rows, build_source_performance_rows


def _job(*, title: str, source: str, status: str, final_score: float, expected_value: float, role_family: str) -> Job:
    breakdown = {
        "total": final_score,
        "role_family": {"label": role_family},
        "decision": {
            "final_weighted_score": final_score,
            "expected_value_score": expected_value,
        },
    }
    return Job(
        title=title,
        source=source,
        status=status,
        score=final_score,
        score_breakdown=json.dumps(breakdown),
        created_at=datetime.utcnow() - timedelta(days=1),
        updated_at=datetime.utcnow(),
    )


def test_source_performance_auto_weight_rewards_better_converting_source():
    jobs = [
        _job(title="Analyst 1", source="greenhouse", status="applied", final_score=82, expected_value=78, role_family="Data Analyst"),
        _job(title="Analyst 2", source="greenhouse", status="interview", final_score=86, expected_value=84, role_family="Data Analyst"),
        _job(title="Analyst 3", source="greenhouse", status="offer", final_score=91, expected_value=88, role_family="Data Analyst"),
        _job(title="Ops 1", source="adzuna", status="applied", final_score=61, expected_value=52, role_family="Operations Analyst"),
        _job(title="Ops 2", source="adzuna", status="no_response", final_score=58, expected_value=49, role_family="Operations Analyst"),
        _job(title="Ops 3", source="adzuna", status="declined", final_score=55, expected_value=46, role_family="Operations Analyst"),
    ]

    rows = build_source_performance_rows(jobs)
    greenhouse = next(row for row in rows if row["source"] == "greenhouse")
    adzuna = next(row for row in rows if row["source"] == "adzuna")

    assert greenhouse["auto_weight"] > adzuna["auto_weight"]
    assert greenhouse["auto_weight"] > 1.0


def test_conversion_analytics_group_role_family_and_score_bands():
    jobs = [
        _job(title="Data Analyst", source="greenhouse", status="offer", final_score=89, expected_value=83, role_family="Data Analyst"),
        _job(title="Business Analyst", source="greenhouse", status="interview", final_score=76, expected_value=74, role_family="Business Analyst"),
        _job(title="Warehouse Associate", source="adzuna", status="applied", final_score=63, expected_value=58, role_family="Operations Analyst"),
        _job(title="Sales Associate", source="adzuna", status="new", final_score=42, expected_value=41, role_family="General fallback"),
    ]

    role_rows = build_role_family_performance_rows(jobs)
    score_rows = build_score_band_analytics_rows(jobs)

    data_row = next(row for row in role_rows if row["role_family"] == "Data Analyst")
    assert data_row["offer_count"] == 1
    assert data_row["response_rate"] == 100.0

    high_band = next(row for row in score_rows if row["band_label"] == "85-100")
    assert high_band["job_count"] == 1
    assert high_band["offer_count"] == 1
