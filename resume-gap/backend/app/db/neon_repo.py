"""Neon (Postgres) repository. Same contract as MemoryRepository; see db/base.py."""

import logging

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import ValidationError

from app.db.base import AnalysisRepository
from app.db.tables import SCHEMA
from app.domain.schemas import AnalysisResult

log = logging.getLogger(__name__)


class NeonRepository(AnalysisRepository):
    def __init__(self, database_url: str) -> None:
        # Small pool: Neon is remote, so reusing TLS connections saves ~100ms+ per request.
        # check_connection discards connections Neon dropped while the compute was suspended.
        self._pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=5,
            check=ConnectionPool.check_connection,
            # No server-side prepared statements, so Neon's pooled (PgBouncer) URL works too.
            kwargs={"prepare_threshold": None},
            open=True,
        )
        with self._pool.connection() as conn:
            conn.execute(SCHEMA)

    def close(self) -> None:
        self._pool.close()

    def save(self, result: AnalysisResult, input_hash: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO analyses (id, session_id, input_hash, created_at, result)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (session_id, input_hash) DO NOTHING
                """,
                (result.id, result.session_id, input_hash, result.created_at, Jsonb(result.model_dump(mode="json"))),
            )

    def get(self, analysis_id: str) -> AnalysisResult | None:
        with self._pool.connection() as conn:
            row = conn.execute("SELECT result FROM analyses WHERE id = %s", (analysis_id,)).fetchone()
        return _load(row[0]) if row else None

    def list_for_session(self, session_id: str, limit: int = 50) -> list[AnalysisResult]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT result FROM analyses WHERE session_id = %s ORDER BY created_at DESC LIMIT %s",
                (session_id, limit),
            ).fetchall()
        return [r for r in (_load(row[0]) for row in rows) if r is not None]

    def find_by_hash(self, session_id: str, input_hash: str) -> AnalysisResult | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT result FROM analyses WHERE session_id = %s AND input_hash = %s",
                (session_id, input_hash),
            ).fetchone()
        return _load(row[0]) if row else None

    def known_skills(self, session_id: str) -> list[str]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT req->>'canonical_skill'
                FROM analyses, jsonb_array_elements(result->'requirements'->'requirements') AS req
                WHERE session_id = %s
                """,
                (session_id,),
            ).fetchall()
        return sorted(r[0] for r in rows if r[0])


def _load(data: dict) -> AnalysisResult | None:
    # Rows saved before a schema change may no longer validate; skip them rather than 500.
    try:
        return AnalysisResult.model_validate(data)
    except ValidationError:
        log.warning("skipping stored analysis %s: no longer matches the schema", data.get("id"))
        return None
