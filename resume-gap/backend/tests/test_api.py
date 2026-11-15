import json

import pytest
from fastapi.testclient import TestClient

from app.db.memory_repo import MemoryRepository
from app.dependencies import get_llm, get_repo, get_url_checker
from app.llm.base import LLMError, LLMRateLimitError
from app.llm.fake_client import DEFAULT_RESPONSES, FakeLLMClient
from app.main import app


def _default_resume() -> str:
    # The canned evidence lines, so stage 2's verbatim check passes.
    items = json.loads(DEFAULT_RESPONSES["EvidenceExtraction"])["items"]
    return "Jane Doe\n" + "\n".join(f"- {i['line']}" for i in items)


class _FailingLLM(FakeLLMClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def _generate(self, prompt, schema):
        raise self._error


@pytest.fixture
def repo():
    return MemoryRepository()


@pytest.fixture
def client(repo):
    app.dependency_overrides[get_repo] = lambda: repo  # fresh store per test: no cross-test cache hits
    app.dependency_overrides[get_url_checker] = lambda: (lambda url: True)  # never hit the network
    yield TestClient(app)
    app.dependency_overrides.clear()


def _use(llm) -> None:
    app.dependency_overrides[get_llm] = lambda: llm


def _body(**overrides) -> dict:
    return {"session_id": "s1", "jd_text": "Backend Engineer at Acme", "resume_text": _default_resume()} | overrides


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_analyze_runs_all_stages_with_fake_llm(client):
    llm = FakeLLMClient()
    _use(llm)
    r = client.post("/api/analyze", json=_body())
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"] == "s1" and data["id"]
    assert [m["bucket"] for m in data["matches"]["matches"]] == [
        "covered",
        "gap",
        "transferable",
        "underemphasized",
        "covered",
    ]
    assert len(data["rewrites"]["rewrites"]) == 1
    assert len(data["recommendations"]["recommendations"]) == 2
    assert sorted(name for name, _ in llm.calls) == sorted(
        ["RequirementsExtraction", "EvidenceExtraction", "MatchDecisions", "RewriteDrafts", "GapRecommendationDrafts"]
    )


def test_analyze_rejects_empty_and_oversized_input(client):
    _use(FakeLLMClient())
    assert client.post("/api/analyze", json=_body(jd_text="")).status_code == 422
    assert client.post("/api/analyze", json=_body(resume_text="x" * 20_001)).status_code == 422


def test_analyze_maps_rate_limit_to_429(client):
    _use(_FailingLLM(LLMRateLimitError("quota", retry_after_seconds=12.3)))
    r = client.post("/api/analyze", json=_body())
    assert r.status_code == 429 and r.headers["retry-after"] == "13"


def test_analyze_maps_llm_failure_to_502(client):
    _use(_FailingLLM(LLMError("boom")))
    r = client.post("/api/analyze", json=_body())
    assert r.status_code == 502 and "boom" in r.json()["detail"]


# ---------- caching + history ----------


def test_same_input_is_served_from_cache(client):
    llm = FakeLLMClient()
    _use(llm)
    first = client.post("/api/analyze", json=_body()).json()
    calls = len(llm.calls)
    # Different line endings / outer whitespace still hit the cache.
    second = client.post("/api/analyze", json=_body(resume_text="\n" + _default_resume().replace("\n", "\r\n") + "  ")).json()
    assert second["id"] == first["id"] and len(llm.calls) == calls


def test_cache_is_per_session(client):
    llm = FakeLLMClient()
    _use(llm)
    a = client.post("/api/analyze", json=_body(session_id="s1")).json()
    b = client.post("/api/analyze", json=_body(session_id="s2")).json()
    assert a["id"] != b["id"] and len(llm.calls) == 10


def test_failed_analysis_is_not_stored(client, repo):
    _use(_FailingLLM(LLMError("boom")))
    client.post("/api/analyze", json=_body())
    assert repo.list_for_session("s1") == []


def test_known_skills_from_session_history_reach_the_pipeline(client, monkeypatch):
    import app.api.analyze as analyze_module

    seen: list[list[str]] = []
    real = analyze_module.run_analysis

    def spy(request, llm, url_is_live, known_skills=None):
        seen.append(known_skills)
        return real(request, llm, url_is_live, known_skills)

    monkeypatch.setattr(analyze_module, "run_analysis", spy)
    _use(FakeLLMClient())
    client.post("/api/analyze", json=_body(jd_text="first JD"))
    client.post("/api/analyze", json=_body(jd_text="second JD"))
    client.post("/api/analyze", json=_body(session_id="other", jd_text="third JD"))

    assert seen[0] == []  # fresh session
    assert seen[1] == ["aws", "communication", "kubernetes", "postgresql", "python"]
    assert seen[2] == []  # other sessions' history doesn't leak in


def test_history_lists_summaries_newest_first_and_gets_by_id(client):
    _use(FakeLLMClient())
    old = client.post("/api/analyze", json=_body(jd_text="first JD")).json()
    new = client.post("/api/analyze", json=_body(jd_text="second JD")).json()

    rows = client.get("/api/sessions/s1/analyses").json()
    assert [r["id"] for r in rows] == [new["id"], old["id"]]
    assert rows[0]["role_title"] == "Backend Engineer"
    assert rows[0]["bucket_counts"] == {"covered": 2, "underemphasized": 1, "transferable": 1, "gap": 1}

    assert client.get(f"/api/analyses/{old['id']}").json()["id"] == old["id"]
    assert client.get("/api/analyses/nope").status_code == 404
    assert client.get("/api/sessions/nobody/analyses").json() == []


def test_gap_ranking_endpoint(client):
    _use(FakeLLMClient())
    assert client.get("/api/sessions/s1/gaps").json() == {"analysis_count": 0, "gaps": []}
    client.post("/api/analyze", json=_body())
    ranking = client.get("/api/sessions/s1/gaps").json()
    # Fake analysis: kubernetes (required gap) = 2, aws (preferred transferable) = 0.5
    assert ranking["analysis_count"] == 1
    assert [(g["canonical_skill"], g["score"]) for g in ranking["gaps"]] == [("kubernetes", 2.0), ("aws", 0.5)]
