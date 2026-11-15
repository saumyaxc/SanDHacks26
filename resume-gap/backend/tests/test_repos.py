"""Contract tests every AnalysisRepository must pass.

Memory always runs. Neon runs only when TEST_DATABASE_URL is set (use a Neon *branch*,
not your main database). Each test uses fresh session ids and deletes its rows.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.memory_repo import MemoryRepository
from app.domain.schemas import (
    AnalysisResult,
    EvidenceExtraction,
    GapRecommendations,
    MatchResult,
    RequirementsExtraction,
    RewriteSuggestions,
)
from app.llm.fake_client import DEFAULT_RESPONSES

_TEST_DB = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(params=["memory", "neon"])
def repo(request):
    if request.param == "memory":
        yield MemoryRepository()
        return
    if not _TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set")
    from app.db.neon_repo import NeonRepository

    neon = NeonRepository(_TEST_DB)
    yield neon
    with neon._pool.connection() as conn:
        conn.execute("DELETE FROM analyses WHERE session_id LIKE 'test-%'")
        conn.execute("DELETE FROM dismissed_gaps WHERE session_id LIKE 'test-%'")
    neon.close()


def _session() -> str:
    return f"test-{uuid.uuid4().hex}"


def _result(session_id: str, minutes: int = 0, skills: tuple[str, ...] = ("python",)) -> AnalysisResult:
    reqs = json.loads(DEFAULT_RESPONSES["RequirementsExtraction"])
    reqs["requirements"] = [
        {**reqs["requirements"][0], "id": f"req-{i}", "skill": s, "canonical_skill": s}
        for i, s in enumerate(skills, start=1)
    ]
    matches = [
        {"requirement_id": f"req-{i}", "bucket": "gap", "rationale": "r"} for i in range(1, len(skills) + 1)
    ]
    return AnalysisResult(
        id=uuid.uuid4().hex,
        session_id=session_id,
        created_at=datetime(2026, 11, 1, tzinfo=UTC) + timedelta(minutes=minutes),
        requirements=RequirementsExtraction.model_validate(reqs),
        evidence=EvidenceExtraction.model_validate(json.loads(DEFAULT_RESPONSES["EvidenceExtraction"])),
        matches=MatchResult.model_validate({"matches": matches}),
        rewrites=RewriteSuggestions(rewrites=[]),
        recommendations=GapRecommendations(recommendations=[]),
    )


def test_save_then_get_round_trips_exactly(repo):
    r = _result(_session())
    repo.save(r, "h1")
    assert repo.get(r.id) == r
    assert repo.get("missing") is None


def test_list_is_newest_first_limited_and_per_session(repo):
    s, other = _session(), _session()
    old, new = _result(s, 0), _result(s, 5)
    repo.save(old, "h1")
    repo.save(new, "h2")
    repo.save(_result(other), "h1")
    assert [r.id for r in repo.list_for_session(s)] == [new.id, old.id]
    assert [r.id for r in repo.list_for_session(s, limit=1)] == [new.id]
    assert repo.list_for_session(_session()) == []


def test_find_by_hash_is_per_session(repo):
    s = _session()
    r = _result(s)
    repo.save(r, "h1")
    assert repo.find_by_hash(s, "h1") == r
    assert repo.find_by_hash(s, "other") is None
    assert repo.find_by_hash(_session(), "h1") is None


def test_known_skills_are_distinct_sorted_and_per_session(repo):
    s = _session()
    repo.save(_result(s, 0, ("python", "docker")), "h1")
    repo.save(_result(s, 1, ("docker", "aws")), "h2")
    repo.save(_result(_session(), 0, ("rust",)), "h1")
    assert repo.known_skills(s) == ["aws", "docker", "python"]


def test_delete_only_within_session(repo):
    s = _session()
    r = _result(s)
    repo.save(r, "h1")
    assert repo.delete(_session(), r.id) is False
    assert repo.delete(s, r.id) is True
    assert repo.get(r.id) is None and repo.find_by_hash(s, "h1") is None
    assert repo.delete(s, r.id) is False


def test_dismiss_and_restore_gaps(repo):
    s = _session()
    repo.dismiss_gap(s, "docker")
    repo.dismiss_gap(s, "docker")  # idempotent
    repo.dismiss_gap(s, "aws")
    assert repo.dismissed_gaps(s) == ["aws", "docker"]
    assert repo.dismissed_gaps(_session()) == []
    repo.restore_gap(s, "docker")
    assert repo.dismissed_gaps(s) == ["aws"]
