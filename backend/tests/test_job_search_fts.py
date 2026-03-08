from app.services.job_service import _build_fts_match_query


def test_build_fts_match_query_includes_phrase_and_prefix_terms():
    value = _build_fts_match_query("data analyst")
    assert value is not None
    assert '"data analyst"' in value
    assert "data*" in value
    assert "analyst*" in value


def test_build_fts_match_query_skips_short_noise():
    value = _build_fts_match_query("a i")
    assert value is None
