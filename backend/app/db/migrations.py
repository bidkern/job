from sqlalchemy import text
from sqlalchemy.engine import Engine


def _table_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS job_sources (
                    id INTEGER PRIMARY KEY,
                    source_type VARCHAR(30) NOT NULL,
                    config_json TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    last_run_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS job_materials (
                    id INTEGER PRIMARY KEY,
                    job_id INTEGER NOT NULL UNIQUE,
                    ats_keywords TEXT NOT NULL,
                    resume_bullet_suggestions TEXT NOT NULL,
                    cover_letter_draft TEXT,
                    outreach_message_draft TEXT NOT NULL,
                    openai_used BOOLEAN NOT NULL DEFAULT 0,
                    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS automation_runs (
                    id INTEGER PRIMARY KEY,
                    run_started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    run_finished_at DATETIME,
                    sources_processed INTEGER NOT NULL DEFAULT 0,
                    ingested_count INTEGER NOT NULL DEFAULT 0,
                    updated_count INTEGER NOT NULL DEFAULT 0,
                    ready_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    id INTEGER PRIMARY KEY,
                    full_name VARCHAR(120),
                    email VARCHAR(160),
                    phone VARCHAR(40),
                    zip_code VARCHAR(10),
                    distance_miles FLOAT,
                    skills_json TEXT,
                    hobbies_json TEXT,
                    score_tuning_mode VARCHAR(20) NOT NULL DEFAULT 'balanced',
                    last_rescored_at DATETIME,
                    resume_path VARCHAR(500),
                    resume_filename VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        profile_columns = _table_columns(conn, "user_profiles")
        if profile_columns:
            if "score_tuning_mode" not in profile_columns:
                conn.execute(text("ALTER TABLE user_profiles ADD COLUMN score_tuning_mode VARCHAR(20) DEFAULT 'balanced'"))
            if "last_rescored_at" not in profile_columns:
                conn.execute(text("ALTER TABLE user_profiles ADD COLUMN last_rescored_at DATETIME"))
            if "hobbies_json" not in profile_columns:
                conn.execute(text("ALTER TABLE user_profiles ADD COLUMN hobbies_json TEXT"))
            conn.execute(text("UPDATE user_profiles SET score_tuning_mode = 'balanced' WHERE score_tuning_mode IS NULL OR TRIM(score_tuning_mode) = ''"))

        jobs_columns = _table_columns(conn, "jobs")
        if jobs_columns:
            if "applied_date" not in jobs_columns:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN applied_date DATETIME"))
            if "follow_up_date" not in jobs_columns:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN follow_up_date DATETIME"))
            if "reminders" not in jobs_columns:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN reminders TEXT"))
            if "attachments" not in jobs_columns:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN attachments TEXT"))
            if "raw_description" not in jobs_columns:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN raw_description TEXT"))
