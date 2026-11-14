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

## Run tests

```bash
cd backend
pytest
```
