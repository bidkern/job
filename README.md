# Local Job Application Assistant

Production-ready starter app to find, organize, and prepare tailored materials for jobs near ZIP `44224`.

## Backend automation additions

### New tables
- `job_sources`: stores source type + config JSON + enabled flag
- `automation_runs`: stores run history and counts
- `job_materials`: stores precomputed materials for ready jobs

### New endpoints
- `POST /automation/run-now`
- `GET /automation/status`

### Daily scheduler
- Runs daily at `08:00` local time (`LOCAL_TIMEZONE`, default `America/New_York`)
- For each enabled `job_sources` record:
  - fetches jobs via source-specific ingestion
  - dedupes + scores + upserts jobs
  - marks high-scoring jobs as `ready` when `score >= 75` (from `new/saved`)
- If `OPENAI_ENABLED=true`, precomputes materials for `ready` jobs into `job_materials`

### Auto-follow-up behavior
When a job is patched to `status="applied"` and `follow_up_date` is null:
- `applied_date` is set to now (if absent)
- `follow_up_date` is set to `applied_date + 7 days`
- reminder string is appended to `reminders`

### Migrations
- SQL artifact: `backend/migrations/001_automation.sql`
- Runtime idempotent migrator: `app/db/migrations.py`
  - runs on app startup and backfills missing follow-up columns for older DBs

## Running backend with scheduler

### Dev
```powershell
cd backend
py -3.11 -m pip install -r requirements.txt
py -3.11 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Prod
Use a single process manager command (systemd/supervisor/container):
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```
Notes:
- Keep `workers=1` if you want exactly one in-process scheduler instance.
- For multi-worker deployments, run scheduler in a separate dedicated process/container to avoid duplicate runs.

## Frontend
- Next.js app router dashboard in `frontend/`
- Includes dark mode toggle with persisted preference in localStorage.
- Run:
```powershell
cd frontend
copy .env.example .env.local
npm install
npm run dev
```
