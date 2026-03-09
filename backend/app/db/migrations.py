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
                CREATE TABLE IF NOT EXISTS job_status_events (
                    id INTEGER PRIMARY KEY,
                    job_id INTEGER NOT NULL,
                    previous_status VARCHAR(30),
                    new_status VARCHAR(30) NOT NULL,
                    action_source VARCHAR(40) NOT NULL DEFAULT 'manual',
                    note TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS job_packet_history (
                    id INTEGER PRIMARY KEY,
                    job_id INTEGER NOT NULL,
                    packet_text TEXT NOT NULL,
                    ats_keywords TEXT NOT NULL,
                    resume_bullet_suggestions TEXT NOT NULL,
                    cover_letter_draft TEXT,
                    outreach_message_draft TEXT NOT NULL,
                    openai_used BOOLEAN NOT NULL DEFAULT 0,
                    generated_via TEXT NOT NULL DEFAULT 'single',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
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
                CREATE TABLE IF NOT EXISTS refresh_states (
                    id INTEGER PRIMARY KEY,
                    scope VARCHAR(40) NOT NULL UNIQUE,
                    status VARCHAR(20) NOT NULL DEFAULT 'idle',
                    last_enqueued_at DATETIME,
                    last_started_at DATETIME,
                    last_finished_at DATETIME,
                    last_success_at DATETIME,
                    last_error TEXT,
                    items_written INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
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

        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_remote_type ON jobs(remote_type)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_status_updated_at ON jobs(status, updated_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_posted_date ON jobs(posted_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_follow_up_date ON jobs(follow_up_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_salary_bounds ON jobs(pay_max, pay_min)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_refresh_states_scope ON refresh_states(scope)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_job_status_events_job_created ON job_status_events(job_id, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_job_status_events_status_created ON job_status_events(new_status, created_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_job_packet_history_job_created ON job_packet_history(job_id, created_at DESC)"))

        conn.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
                    title,
                    company,
                    location_text,
                    description,
                    content='jobs',
                    content_rowid='id'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS jobs_fts_ai AFTER INSERT ON jobs BEGIN
                    INSERT INTO jobs_fts(rowid, title, company, location_text, description)
                    VALUES (
                        new.id,
                        coalesce(new.title, ''),
                        coalesce(new.company, ''),
                        coalesce(new.location_text, ''),
                        coalesce(new.description, '')
                    );
                END
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS jobs_fts_ad AFTER DELETE ON jobs BEGIN
                    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, location_text, description)
                    VALUES (
                        'delete',
                        old.id,
                        coalesce(old.title, ''),
                        coalesce(old.company, ''),
                        coalesce(old.location_text, ''),
                        coalesce(old.description, '')
                    );
                END
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS jobs_fts_au AFTER UPDATE ON jobs BEGIN
                    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, location_text, description)
                    VALUES (
                        'delete',
                        old.id,
                        coalesce(old.title, ''),
                        coalesce(old.company, ''),
                        coalesce(old.location_text, ''),
                        coalesce(old.description, '')
                    );
                    INSERT INTO jobs_fts(rowid, title, company, location_text, description)
                    VALUES (
                        new.id,
                        coalesce(new.title, ''),
                        coalesce(new.company, ''),
                        coalesce(new.location_text, ''),
                        coalesce(new.description, '')
                    );
                END
                """
            )
        )
        conn.execute(text("INSERT INTO jobs_fts(jobs_fts) VALUES ('rebuild')"))
