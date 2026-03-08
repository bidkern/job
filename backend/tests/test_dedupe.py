from app.services.dedupe import canonicalize_url, is_fuzzy_duplicate


def test_canonicalize_url_sorts_query():
    url = "HTTPS://example.com/jobs/123/?b=2&a=1"
    assert canonicalize_url(url) == "https://example.com/jobs/123?a=1&b=2"


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
