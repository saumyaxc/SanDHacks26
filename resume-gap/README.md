# resume-gap

Paste a job description and your resume. Get back which requirements you cover
(with the exact resume line as evidence), which you underemphasize, which are
transferable, and which are real gaps — plus honest rewrite suggestions and a
weekend project for each gap.

## Backend setup

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
```

Then fill in `.env` (at least `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`).

## Run everything

```bash
./dev.sh
```

Starts the API (http://localhost:8000, docs at `/docs`) and the frontend (http://localhost:5173)
together; Ctrl+C stops both. First-time setup is the backend steps above (the script installs
frontend dependencies itself).

`LLM_PROVIDER=fake` (the default) returns canned results with no API key. It only works if the resume
contains the canned evidence lines; use `LLM_PROVIDER=gemini` for real resumes. Restart after editing `.env`.

## Storage (Neon)

Without `DATABASE_URL`, analyses are kept in memory and lost on restart. To persist them:

1. Create a project at https://neon.tech and copy its connection string.
2. Set `DATABASE_URL=postgresql://...` in `.env` and restart the API. The table is created on startup.

Stored: the job description, the extracted and verified resume lines (after contact details
are removed), and the analysis results. Raw resume text is never stored.

To run the repository tests against a real database, set `TEST_DATABASE_URL`. The tests only
create and delete rows whose session id starts with `test-`, so your real analyses are untouched:

```bash
TEST_DATABASE_URL='postgresql://...' pytest tests/test_repos.py
```

## Run tests

```bash
cd backend
pytest
```
