Backend Prompt

Build a production-oriented job decision engine and ingestion backend for a local job application assistant.

Primary goal:
- Maximize the user's chances of finding compatible, good-paying jobs and applying efficiently at scale.

Core responsibilities:
- Ingest jobs from compliant public sources.
- Normalize and dedupe listings.
- Score jobs using resume-first logic.
- Rank jobs by expected value and realistic interview odds.
- Return explainable metadata for frontend decision-making.

Ranking requirements:
- Compatibility
- Interviewability
- Sentiment
- Expected value
- Hard match
- Soft match
- Salary likelihood
- Application friction
- Response probability
- Realness / scam / stale risk
- Career trajectory fit
- Work-style fit
- Resume gap severity
- Confidence

Weighting principles:
- Resume / experience / skill fit should dominate.
- Job requirement match is secondary.
- Compensation and logistics matter, but do not overpower fit.
- Hobbies are a light preference layer only and must never be exposed to employers.

API behavior requirements:
- Return local recommendations quickly.
- Avoid blocking the UI while broad ingestion is running.
- Batch persistence work instead of committing each job individually.
- Bound candidate windows for interactive searches so search remains responsive.
- Always include explainability fields so the frontend can show why a job ranked where it did.

Data requirements:
- SQLite
- Job normalization
- Distance from ZIP
- Score breakdown JSON
- Status tracking
- Resume/profile-based rescoring

Trust and safety requirements:
- Use only compliant public job sources.
- Do not bypass logins, CAPTCHAs, or prohibited scraping.
- Do not auto-submit applications.
- Keep private hobbies out of employer-facing materials.

System standard:
- Every backend decision should improve one of these outcomes:
  - stronger fit
  - better pay
  - higher interview odds
  - less wasted application effort
