import json

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_llm
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
def client():
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
        ["RequirementsExtraction", "EvidenceExtraction", "MatchDecisions", "RewriteDrafts", "GapRecommendations"]
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
