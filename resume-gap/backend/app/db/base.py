"""Storage interface. Routes and services depend on this, never on a concrete repo.

Implementations: memory_repo.MemoryRepository (dev/tests), neon_repo (later).
dependencies.py alone decides which one is used.
"""

from abc import ABC, abstractmethod

from app.domain.schemas import AnalysisResult


class AnalysisRepository(ABC):
    @abstractmethod
    def save(self, result: AnalysisResult, input_hash: str) -> None:
        """Store a finished analysis. `input_hash` identifies its (JD, resume) input for caching."""

    @abstractmethod
    def get(self, analysis_id: str) -> AnalysisResult | None: ...

    @abstractmethod
    def list_for_session(self, session_id: str, limit: int = 50) -> list[AnalysisResult]:
        """Newest first."""

    @abstractmethod
    def find_by_hash(self, session_id: str, input_hash: str) -> AnalysisResult | None:
        """A previous analysis of the same input in this session, if any (the cache lookup)."""

    @abstractmethod
    def known_skills(self, session_id: str) -> list[str]:
        """Canonical requirement skills from this session's past analyses, sorted.

        Fed back into extraction so the same skill gets the same name across JDs.
        """

    @abstractmethod
    def delete(self, session_id: str, analysis_id: str) -> bool:
        """Delete one analysis, only if it belongs to `session_id`. True if something was deleted."""

    @abstractmethod
    def dismiss_gap(self, session_id: str, canonical_skill: str) -> None:
        """Hide a skill from this session's gap ranking ("Learn next")."""

    @abstractmethod
    def restore_gap(self, session_id: str, canonical_skill: str) -> None: ...

    @abstractmethod
    def dismissed_gaps(self, session_id: str) -> list[str]:
        """Sorted canonical skills this session has hidden."""
