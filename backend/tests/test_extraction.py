from app.services.extraction import extract_skills


def test_extract_skills_matches_keywords():
    text = "Strong SQL and Python skills with dashboard development in Power BI"
    skills = extract_skills(text)
    assert "sql" in skills
    assert "python" in skills
    assert "power bi" in skills
