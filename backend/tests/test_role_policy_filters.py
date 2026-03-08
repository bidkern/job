from app.api.jobs import _job_is_relevant_to_profile


def test_relevance_filters_out_unrelated_roles():
    assert not _job_is_relevant_to_profile(
        title="Registered Nurse",
        description="Clinical patient care and medication administration.",
        extracted_skills=["patient care"],
        profile_skills=["sales", "customer service", "inventory", "operations"],
    )


def test_relevance_keeps_jobs_with_direct_skill_overlap():
    assert _job_is_relevant_to_profile(
        title="Sales Representative",
        description="Outbound calls, lead generation, and CRM updates.",
        extracted_skills=["sales", "crm", "lead generation"],
        profile_skills=["sales", "customer service", "inventory", "operations"],
    )


def test_relevance_keeps_jobs_with_transferable_token_overlap():
    assert _job_is_relevant_to_profile(
        title="Warehouse Associate",
        description="Inventory counts, shipping, and receiving tasks.",
        extracted_skills=["warehouse", "inventory", "shipping", "receiving"],
        profile_skills=["inventory management", "operations", "customer communication"],
    )


def test_relevance_keeps_high_scored_rows_even_without_direct_term_hit():
    assert _job_is_relevant_to_profile(
        title="Operations Coordinator",
        description="Coordinate schedules and reporting.",
        extracted_skills=["reporting"],
        profile_skills=["customer service", "sales"],
        potential_match_score=58,
        interview_score=62,
    )
