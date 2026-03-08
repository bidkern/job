from app.services.dedupe import canonicalize_url, extract_external_job_keys, is_fuzzy_duplicate, is_probable_duplicate


def test_canonicalize_url_sorts_query():
    url = "HTTPS://example.com/jobs/123/?b=2&a=1"
    assert canonicalize_url(url) == "https://example.com/jobs/123?a=1&b=2"


def test_canonicalize_url_drops_tracking_params():
    url = "https://jobs.example.com/opening/123?utm_source=x&gh_jid=999&source=linkedin"
    assert canonicalize_url(url) == "https://jobs.example.com/opening/123?gh_jid=999"


def test_fuzzy_duplicate_true():
    assert is_fuzzy_duplicate(
        "Acme",
        "Data Analyst",
        "Akron, OH",
        "Acme Inc",
        "Data Analytics Analyst",
        "Akron OH",
        threshold=70,
    )


def test_extract_external_job_keys_reads_source_specific_ids():
    keys = extract_external_job_keys(
        "https://boards.greenhouse.io/acme/jobs/1234567?gh_jid=1234567&utm_source=linkedin",
        source="greenhouse",
    )
    assert "greenhouse:id:1234567" in keys
    assert "param:gh_jid:1234567" in keys


def test_probable_duplicate_matches_cross_source_same_job():
    assert is_probable_duplicate(
        existing_company="Acme Inc.",
        existing_title="Operations Coordinator",
        existing_location="Akron, OH",
        existing_url="https://boards.greenhouse.io/acme/jobs/1234567",
        existing_source="greenhouse",
        existing_description="REQ-7788 Coordinate inventory, customer communication, and reporting.",
        existing_pay_min=52000,
        existing_pay_max=62000,
        company="Acme",
        title="Operations Coordinator",
        location="Akron OH",
        url="https://jobs.acme.com/openings/operations-coordinator?jobId=1234567&utm_source=linkedin",
        source="company_board",
        description="Req 7788 Coordinate inventory, customer communication and reporting across teams.",
        pay_min=53000,
        pay_max=61000,
    )
