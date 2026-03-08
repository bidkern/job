from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "jobs.db"


class Settings(BaseSettings):
    app_name: str = "Local Job Application Assistant"
    # Keep SQLite file outside backend/ so uvicorn --reload does not restart on every DB write.
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
    base_zip: str = "44224"
    default_radius_miles: float = 35.0
    openai_enabled: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    local_timezone: str = "America/New_York"
    automation_hour_local: int = 8
    automation_minute_local: int = 0
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    aggressive_legal_mode: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
