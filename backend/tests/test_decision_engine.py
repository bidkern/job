from datetime import datetime, timezone

from app.services.decision_engine import build_decision_metrics
from app.services.role_family import classify_role_family


def test_role_family_classifier_data_analyst():
    result = classify_role_family(
        title="Data Analyst",
        description="Build SQL dashboards and reporting for product KPIs.",
        job_skills=["sql", "tableau", "dashboarding"],
    )
    assert result["key"] == "data_analyst"
    assert float(result["confidence"]) > 0.4


def test_decision_metrics_ranges_and_strategy():
    metrics = build_decision_metrics(
        title="Operations Analyst",
        description="Easy apply role focused on reporting, process improvement, and KPI dashboards.",
        role_family_key="operations_analyst",
        role_family_confidence=0.8,
        compatibility_core=0.76,
        interview_core=0.72,
        role_score=0.74,
        skill_direct_ratio=0.65,
        skill_transferable_ratio=0.82,
        resume_strength=0.7,
        distance_score=0.85,
        salary_score=0.66,
        freshness_score=0.9,
        source_score=0.95,
        hobby_score=0.35,
        pay_min=70000,
        pay_max=90000,
        posted_date=datetime.now(timezone.utc),
        source="greenhouse",
        remote_type="hybrid",
        seniority_signal="entry",
        job_skills=["excel", "sql", "kpi", "reporting"],
        matched_skills=["excel", "sql"],
        missing_skills=["power bi"],
    )
    assert 0 <= metrics["hard_match"] <= 1
    assert 0 <= metrics["soft_match"] <= 1
    assert 0 <= metrics["confidence"] <= 1
    assert 0 <= metrics["final_weighted_score"] <= 100
    assert 0 <= metrics["expected_value_score"] <= 100
    assert metrics["strategy_tag"] in {
        "Apply now",
        "Tailor lightly",
        "Tailor heavily",
        "Save for later",
        "Reach out first",
        "Skip",
    }
