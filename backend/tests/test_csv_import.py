from app.services.ingestion import parse_csv_content


def test_csv_import():
    raw = "title,company,location_text,url,description\nData Analyst,Acme,Akron OH 44308,https://example.com/1,SQL and dashboard"
    rows = parse_csv_content(raw)
    assert len(rows) == 1
    assert rows[0]["title"] == "Data Analyst"
    assert rows[0]["source"] == "csv"


def test_csv_import_handles_bom_and_semicolon_and_aliases():
    raw = (
        "\ufeffjob_title;company_name;job_location;link;job_description\n"
        "Data Analyst;Acme;Akron OH 44308;https://example.com/1;SQL and dashboard\n"
    )
    rows = parse_csv_content(raw)
    assert len(rows) == 1
    assert rows[0]["title"] == "Data Analyst"
    assert rows[0]["company"] == "Acme"
    assert rows[0]["canonical_url"] == "https://example.com/1"
