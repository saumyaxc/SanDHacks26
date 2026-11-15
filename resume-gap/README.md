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
cp ../.env.example ../.env   # then edit values
```

## Run the API

```bash
cd backend
uvicorn app.main:app --reload
```

- `GET  http://localhost:8000/api/health`
- `POST http://localhost:8000/api/analyze` with `{"session_id", "jd_text", "resume_text"}`
- Interactive docs: http://localhost:8000/docs

`LLM_PROVIDER=fake` (the default) returns canned results with no API key. It only works if the resume
contains the canned evidence lines; use `LLM_PROVIDER=gemini` for real resumes.

## Storage (Neon)

Without `DATABASE_URL`, analyses are kept in memory and lost on restart. To persist them:

1. Create a project at https://neon.tech and copy its connection string.
2. Set `DATABASE_URL=postgresql://...` in `.env` and restart the API. The table is created on startup.

Stored: the extracted, verified resume lines and the analysis results. Raw JD and resume
text is never stored.

To run the repository tests against a real database, point `TEST_DATABASE_URL` at a Neon
*branch* (not your main database); the tests delete only rows with `test-` session ids:

```bash
TEST_DATABASE_URL='postgresql://...' pytest tests/test_repos.py
```

## Run the frontend

In a second terminal, with the API running on port 8000:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend.

## Run tests

```bash
cd backend
pytest
```
