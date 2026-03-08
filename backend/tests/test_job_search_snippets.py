from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.migrations import run_migrations
from app.db.session import Base
from app.models.job import Job
from app.services.job_service import get_job_match_snippets


def test_get_job_match_snippets_returns_highlighted_description_text(tmp_path):
    db_path = tmp_path / "jobs-snippets.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    run_migrations(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with SessionLocal() as db:
        job = Job(
            title="Data Analyst",
            company="Acme",
            location_text="Akron, OH",
            remote_type="hybrid",
            source="manual",
            description="Build SQL dashboards, analyze sales trends, and explain results to stakeholders.",
            extracted_skills="[]",
            keywords="[]",
            score_breakdown="{}",
            status="new",
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        snippets = get_job_match_snippets(db, "sql dashboard", limit=10)

        assert job.id in snippets
        assert "[[" in snippets[job.id]
        assert "]]" in snippets[job.id]
        assert "sql" in snippets[job.id].lower() or "dashboard" in snippets[job.id].lower()
