import shutil
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _bootstrap_sqlite_db() -> None:
    url = settings.database_url or ""
    if not url.startswith("sqlite:///"):
        return

    db_path = Path(url.replace("sqlite:///", "", 1))
    if db_path.exists():
        return

    # Legacy location used earlier by this project.
    legacy_path = Path(__file__).resolve().parents[2] / "jobs.db"
    if legacy_path.exists() and legacy_path != db_path:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_path, db_path)


_bootstrap_sqlite_db()
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

