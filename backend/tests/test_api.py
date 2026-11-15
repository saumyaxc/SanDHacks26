import json

import pytest
from fastapi.testclient import TestClient

from app.db.memory_repo import MemoryRepository
from app.dependencies import get_llm, get_repo, get_url_checker
from app.llm.base import LLMError, LLMRateLimitError
from app.llm.fake_client import DEFAULT_JD_TEXT, DEFAULT_RESPONSES, FakeLLMClient
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
    return {"session_id": "s1", "jd_text": DEFAULT_JD_TEXT, "resume_text": _default_resume()} | overrides


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
    assert data["rewrites"]["rewrites"] == []  # nothing honest to rewrite in the demo data -> no LLM call
    assert len(data["recommendations"]["recommendations"]) == 2
    assert sorted(name for name, _ in llm.calls) == sorted(
        ["RequirementsExtraction", "EvidenceExtraction", "MatchDecisions", "GapRecommendationDrafts"]
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
    assert a["id"] != b["id"] and len(llm.calls) == 8  # 4 calls per fresh analysis


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
    client.post("/api/analyze", json=_body(jd_text=DEFAULT_JD_TEXT + "\nfirst JD"))
    client.post("/api/analyze", json=_body(jd_text=DEFAULT_JD_TEXT + "\nsecond JD"))
    client.post("/api/analyze", json=_body(session_id="other", jd_text=DEFAULT_JD_TEXT + "\nthird JD"))

    assert seen[0] == []  # fresh session
    assert seen[1] == ["aws", "communication", "kubernetes", "postgresql", "python"]
    assert seen[2] == []  # other sessions' history doesn't leak in


def test_history_lists_summaries_newest_first_and_gets_by_id(client):
    _use(FakeLLMClient())
    old = client.post("/api/analyze", json=_body(jd_text=DEFAULT_JD_TEXT + "\nfirst JD")).json()
    new = client.post("/api/analyze", json=_body(jd_text=DEFAULT_JD_TEXT + "\nsecond JD")).json()

    rows = client.get("/api/sessions/s1/analyses").json()
    assert [r["id"] for r in rows] == [new["id"], old["id"]]
    assert rows[0]["role_title"] == "Backend Engineer"
    assert rows[0]["bucket_counts"] == {"covered": 2, "underemphasized": 1, "transferable": 1, "gap": 1}

    assert client.get(f"/api/analyses/{old['id']}").json()["id"] == old["id"]
    assert client.get("/api/analyses/nope").status_code == 404
    assert client.get("/api/sessions/nobody/analyses").json() == []


def test_gap_ranking_endpoint(client):
    _use(FakeLLMClient())
    assert client.get("/api/sessions/s1/gaps").json() == {"analysis_count": 0, "gaps": [], "dismissed": []}
    client.post("/api/analyze", json=_body())
    ranking = client.get("/api/sessions/s1/gaps").json()
    # Fake analysis: kubernetes (required gap) = 2, aws (preferred transferable) = 0.5
    assert ranking["analysis_count"] == 1
    assert [(g["canonical_skill"], g["score"]) for g in ranking["gaps"]] == [("kubernetes", 2.0), ("aws", 0.5)]


def test_pasted_resume_contact_info_never_reaches_the_llm(client):
    llm = FakeLLMClient()
    _use(llm)
    resume = "Alex Rivera\nalex@x.io | 858-555-1234 | github.com/alexr\nEXPERIENCE\n" + _default_resume()
    r = client.post("/api/analyze", json=_body(resume_text=resume))
    assert r.status_code == 200
    for _, prompt in llm.calls:
        for secret in ("alex@x.io", "555-1234", "github.com/alexr", "Alex Rivera"):
            assert secret not in prompt
    # Fake data: python 2 + k8s 0 + aws 0.4 + postgres 1.6 over weight 7; communication is
    # a soft skill (interview material), so it's left out.
    assert r.json()["match_score"]["percent"] == 57


def test_delete_analysis_is_scoped_to_session(client):
    _use(FakeLLMClient())
    a = client.post("/api/analyze", json=_body()).json()
    assert client.delete(f"/api/sessions/someone-else/analyses/{a['id']}").status_code == 404
    assert client.delete(f"/api/sessions/s1/analyses/{a['id']}").status_code == 204
    assert client.get("/api/sessions/s1/analyses").json() == []
    assert client.get(f"/api/analyses/{a['id']}").status_code == 404


def test_dismissed_gap_is_hidden_then_restorable(client):
    _use(FakeLLMClient())
    client.post("/api/analyze", json=_body())
    assert client.put("/api/sessions/s1/dismissed-gaps/kubernetes").status_code == 204
    ranking = client.get("/api/sessions/s1/gaps").json()
    assert [g["canonical_skill"] for g in ranking["gaps"]] == ["aws"]
    assert ranking["dismissed"] == ["kubernetes"]
    client.delete("/api/sessions/s1/dismissed-gaps/kubernetes")
    assert [g["canonical_skill"] for g in client.get("/api/sessions/s1/gaps").json()["gaps"]] == ["kubernetes", "aws"]


def test_ranked_gaps_carry_their_projects_and_the_saved_jd(client):
    _use(FakeLLMClient())
    a = client.post("/api/analyze", json=_body(jd_text=DEFAULT_JD_TEXT + "\nBackend Engineer at Acme, needs K8s")).json()
    assert a["jd_text"].endswith("Backend Engineer at Acme, needs K8s")
    k8s = client.get("/api/sessions/s1/gaps").json()["gaps"][0]
    assert k8s["canonical_skill"] == "kubernetes"
    assert len(k8s["recommendation"]["projects"]) == 2
    assert k8s["occurrences"][0]["requirement_id"] == "req-2"


def test_same_job_with_two_resumes_shares_a_job_key(client):
    _use(FakeLLMClient())
    client.post("/api/analyze", json=_body(resume_label="old.pdf"))
    client.post("/api/analyze", json=_body(resume_text=_default_resume() + "\n- Extra line", resume_label="new.pdf"))
    client.post("/api/analyze", json=_body(jd_text=DEFAULT_JD_TEXT + "\nA different job entirely"))
    rows = client.get("/api/sessions/s1/analyses").json()
    assert [r["resume_label"] for r in rows] == ["", "new.pdf", "old.pdf"]  # newest first
    assert rows[1]["job_key"] == rows[2]["job_key"] != rows[0]["job_key"]
    # The ranking counts that job once, not once per resume.
    assert client.get("/api/sessions/s1/gaps").json()["analysis_count"] == 2


def test_rerunning_the_same_resume_keeps_one_resume_fingerprint(client):
    _use(FakeLLMClient())
    a = client.post("/api/analyze", json=_body()).json()
    b = client.post("/api/analyze", json=_body(resume_text=_default_resume() + "\n- Extra line")).json()
    assert a["resume_hash"] and a["resume_hash"] != b["resume_hash"]
    assert a["match_score"]["skills_counted"] == 4  # python, k8s, aws, postgres; communication is interview



def test_text_that_isnt_a_job_description_is_a_clear_422(client):
    _use(FakeLLMClient())  # its canned requirements quote text that isn't in this "JD"
    r = client.post("/api/analyze", json=_body(jd_text="this is not a job description"))
    assert r.status_code == 422 and "job posting" in r.json()["detail"]
