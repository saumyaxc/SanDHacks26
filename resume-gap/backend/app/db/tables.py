"""Postgres schema for neon_repo. Applied at startup with IF NOT EXISTS (no migration tool).

The whole AnalysisResult lives in `result` (jsonb); the other columns exist only for lookups.
The job description is stored (inside `result`); raw resume text never is — only the
extracted, verified resume lines inside `result`.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id          text PRIMARY KEY,
    session_id  text NOT NULL,
    input_hash  text NOT NULL,
    created_at  timestamptz NOT NULL,
    result      jsonb NOT NULL,
    UNIQUE (session_id, input_hash)
);

CREATE INDEX IF NOT EXISTS analyses_session_created_idx
    ON analyses (session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS dismissed_gaps (
    session_id      text NOT NULL,
    canonical_skill text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, canonical_skill)
);
"""
