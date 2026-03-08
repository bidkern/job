-- 001_automation.sql
-- Idempotent table creation for automation features.

CREATE TABLE IF NOT EXISTS job_sources (
  id INTEGER PRIMARY KEY,
  source_type VARCHAR(30) NOT NULL,
  config_json TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT 1,
  last_run_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

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
);

CREATE TABLE IF NOT EXISTS automation_runs (
  id INTEGER PRIMARY KEY,
  run_started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  run_finished_at DATETIME,
  sources_processed INTEGER NOT NULL DEFAULT 0,
  ingested_count INTEGER NOT NULL DEFAULT 0,
  updated_count INTEGER NOT NULL DEFAULT 0,
  ready_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_profiles (
  id INTEGER PRIMARY KEY,
  full_name VARCHAR(120),
  email VARCHAR(160),
  phone VARCHAR(40),
  zip_code VARCHAR(10),
  distance_miles FLOAT,
  skills_json TEXT,
  resume_path VARCHAR(500),
  resume_filename VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
