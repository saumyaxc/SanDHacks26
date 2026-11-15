"""In-process repository: dict storage, lost on restart. For dev and tests."""

import threading

from app.db.base import AnalysisRepository
from app.domain.schemas import AnalysisResult


class MemoryRepository(AnalysisRepository):
    def __init__(self) -> None:
        # Sync routes run in FastAPI's threadpool, so guard the dicts.
        self._lock = threading.Lock()
        self._results: dict[str, AnalysisResult] = {}  # insertion order == save order
        self._by_hash: dict[tuple[str, str], str] = {}  # (session_id, input_hash) -> analysis id
        self._dismissed: dict[str, set[str]] = {}  # session_id -> hidden canonical skills

    def save(self, result: AnalysisResult, input_hash: str) -> None:
        with self._lock:
            self._results[result.id] = result
            self._by_hash[(result.session_id, input_hash)] = result.id

    def get(self, analysis_id: str) -> AnalysisResult | None:
        with self._lock:
            return self._results.get(analysis_id)

    def list_for_session(self, session_id: str, limit: int = 50) -> list[AnalysisResult]:
        with self._lock:
            results = [r for r in self._results.values() if r.session_id == session_id]
        return sorted(results, key=lambda r: r.created_at, reverse=True)[:limit]

    def find_by_hash(self, session_id: str, input_hash: str) -> AnalysisResult | None:
        with self._lock:
            analysis_id = self._by_hash.get((session_id, input_hash))
            return self._results.get(analysis_id) if analysis_id else None

    def known_skills(self, session_id: str) -> list[str]:
        with self._lock:
            results = [r for r in self._results.values() if r.session_id == session_id]
        return sorted({req.canonical_skill for r in results for req in r.requirements.requirements})

    def delete(self, session_id: str, analysis_id: str) -> bool:
        with self._lock:
            result = self._results.get(analysis_id)
            if result is None or result.session_id != session_id:
                return False
            del self._results[analysis_id]
            self._by_hash = {k: v for k, v in self._by_hash.items() if v != analysis_id}
            return True

    def dismiss_gap(self, session_id: str, canonical_skill: str) -> None:
        with self._lock:
            self._dismissed.setdefault(session_id, set()).add(canonical_skill)

    def restore_gap(self, session_id: str, canonical_skill: str) -> None:
        with self._lock:
            self._dismissed.get(session_id, set()).discard(canonical_skill)

    def dismissed_gaps(self, session_id: str) -> list[str]:
        with self._lock:
            return sorted(self._dismissed.get(session_id, set()))
