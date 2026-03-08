from datetime import datetime, timedelta, timezone

from app.services.scoring import score_job


def test_scoring_outputs_breakdown():
    score, breakdown = score_job(
        title="Data Analyst",
        description="Build dashboards with SQL and Tableau",
        job_skills=["sql", "tableau"],
        profile_skills=["sql", "python", "tableau"],
        distance_miles=12,
        remote_type="hybrid",
        pay_min=70000,
        pay_max=95000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=2),
        source="greenhouse",
    )
    assert score > 0
    assert "components" in breakdown
    assert breakdown["components"]["role"] > 0


def test_transferable_skills_contribute_to_compatibility():
    score, breakdown = score_job(
        title="Warehouse Associate",
        description="Assist with shipping, receiving, inventory handling, and team communication.",
        job_skills=["warehouse", "shipping", "receiving"],
        profile_skills=["inventory", "customer service", "communication"],
        distance_miles=8,
        remote_type="onsite",
        pay_min=38000,
        pay_max=45000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=1),
        source="adzuna",
    )
    assert score > 0
    assert breakdown["components"]["skills_transferable"] > 0
    assert breakdown["skill_signals"]["transferable_group_count"] >= 1


def test_entry_level_titles_score_higher_interview_than_senior_titles():
    _, senior_breakdown = score_job(
        title="Senior Data Analyst Manager",
        description="Build dashboards with SQL and Excel",
        job_skills=["sql", "excel", "reporting"],
        profile_skills=["sql", "excel", "communication"],
        distance_miles=10,
        remote_type="hybrid",
        pay_min=70000,
        pay_max=95000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=2),
        source="greenhouse",
    )
    _, entry_breakdown = score_job(
        title="Junior Data Analyst",
        description="Build dashboards with SQL and Excel",
        job_skills=["sql", "excel", "reporting"],
        profile_skills=["sql", "excel", "communication"],
        distance_miles=10,
        remote_type="hybrid",
        pay_min=70000,
        pay_max=95000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=2),
        source="greenhouse",
    )
    assert entry_breakdown["interview_chance_percent"] > senior_breakdown["interview_chance_percent"]


def test_aggressive_mode_is_more_optimistic_than_strict_mode():
    _, strict_breakdown = score_job(
        title="Operations Coordinator",
        description="Coordinate inventory, reporting, and customer communication.",
        job_skills=["operations", "inventory", "reporting"],
        profile_skills=["customer service", "communication", "inventory"],
        distance_miles=15,
        remote_type="onsite",
        pay_min=42000,
        pay_max=52000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=3),
        source="adzuna",
        score_tuning_mode="strict",
    )
    _, aggressive_breakdown = score_job(
        title="Operations Coordinator",
        description="Coordinate inventory, reporting, and customer communication.",
        job_skills=["operations", "inventory", "reporting"],
        profile_skills=["customer service", "communication", "inventory"],
        distance_miles=15,
        remote_type="onsite",
        pay_min=42000,
        pay_max=52000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=3),
        source="adzuna",
        score_tuning_mode="aggressive",
    )
    assert aggressive_breakdown["interview_chance_percent"] >= strict_breakdown["interview_chance_percent"]
    assert aggressive_breakdown["potential_match_percent"] >= strict_breakdown["potential_match_percent"]


def test_degree_and_years_requirements_are_ignored_in_scoring():
    _, with_requirements = score_job(
        title="Operations Associate",
        description=(
            "Bachelor's degree required. 5+ years experience required. "
            "Handle inventory, customer service, and reporting."
        ),
        job_skills=["inventory", "customer service", "reporting"],
        profile_skills=["inventory", "customer service", "communication", "operations"],
        distance_miles=10,
        remote_type="onsite",
        pay_min=42000,
        pay_max=50000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=1),
        source="greenhouse",
    )
    _, without_requirements = score_job(
        title="Operations Associate",
        description="Handle inventory, customer service, and reporting.",
        job_skills=["inventory", "customer service", "reporting"],
        profile_skills=["inventory", "customer service", "communication", "operations"],
        distance_miles=10,
        remote_type="onsite",
        pay_min=42000,
        pay_max=50000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=1),
        source="greenhouse",
    )
    assert with_requirements["requirements_ignored_count"] >= 1
    assert abs(with_requirements["interview_chance_percent"] - without_requirements["interview_chance_percent"]) <= 3.5


def test_entry_level_service_jobs_are_lenient_with_transferable_resume():
    _, breakdown = score_job(
        title="Fast Food Crew Member",
        description="Support customer service, cash handling, food prep, and teamwork.",
        job_skills=["customer service", "cash handling", "food service"],
        profile_skills=["customer service", "communication", "inventory", "sales", "leadership"],
        distance_miles=7,
        remote_type="onsite",
        pay_min=14,
        pay_max=18,
        posted_date=datetime.now(timezone.utc) - timedelta(days=1),
        source="adzuna",
    )
    assert breakdown["interview_chance_percent"] >= 80
    assert breakdown["potential_match_percent"] >= 70


def test_hobby_blend_increases_match_for_hobby_aligned_roles():
    _, aligned = score_job(
        title="Blockchain Community Support Specialist",
        description="Support crypto users, community channels, and token product education.",
        job_skills=["customer service", "community", "crypto"],
        profile_skills=["customer service", "sales", "communication"],
        profile_hobbies=["Cryptocurrency", "Video Games"],
        distance_miles=12,
        remote_type="hybrid",
        pay_min=52000,
        pay_max=70000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=1),
        source="greenhouse",
    )
    _, not_aligned = score_job(
        title="Accounting Clerk",
        description="Handle AP/AR, invoicing, and monthly reconciliations.",
        job_skills=["accounting", "invoicing", "reconciliation"],
        profile_skills=["customer service", "sales", "communication"],
        profile_hobbies=["Cryptocurrency", "Video Games"],
        distance_miles=12,
        remote_type="hybrid",
        pay_min=52000,
        pay_max=70000,
        posted_date=datetime.now(timezone.utc) - timedelta(days=1),
        source="greenhouse",
    )
    assert aligned["potential_match_percent"] > not_aligned["potential_match_percent"]
    assert aligned["hobbies_influence_percent"] == 8
    assert aligned["resume_influence_percent"] == 92
    assert aligned["hobby_signals"]["active"] is True
