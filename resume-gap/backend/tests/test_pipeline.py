import json
from datetime import date

import pytest

from app.domain.enums import Bucket, Priority
from app.domain.quotes import quote_in_text
from app.domain.schemas import (
    EligibilityRequirement,
    EvidenceExtraction,
    ExtractEvidenceInput,
    ExtractRequirementsInput,
    MatchInput,
    MatchResult,
    RecommendInput,
    RequirementsExtraction,
    RewriteInput,
)
from app.llm.base import LLMError
from app.llm.fake_client import DEFAULT_JD_TEXT, DEFAULT_RESPONSES, FakeLLMClient
from app.pipeline.extract_evidence import extract_evidence
from app.pipeline.extract_requirements import extract_requirements
from app.pipeline.match import match
from app.pipeline.recommend_gaps import recommend_gaps
from app.pipeline.suggest_rewrites import suggest_rewrites


def _req(
    id: str,
    skill: str,
    canonical: str | None = None,
    priority: str = "required",
    years: int | None = None,
    group: str | None = None,
) -> dict:
    return {
        "id": id,
        "skill": skill,
        "canonical_skill": canonical or skill,
        "category": "technology",
        "priority": priority,
        "years_required": years,
        "any_of_group": group,
        "jd_quote": f"quote for {skill}",
    }


def _fake(requirements: list[dict]) -> FakeLLMClient:
    payload = {"role_title": "Engineer", "company": None, "requirements": requirements}
    return FakeLLMClient({"RequirementsExtraction": json.dumps(payload)})


def _run(requirements: list[dict], **input_kwargs) -> RequirementsExtraction:
    jd = "\n".join(r["jd_quote"] for r in requirements)
    return extract_requirements(ExtractRequirementsInput(jd_text=jd, **input_kwargs), _fake(requirements))


def test_prompt_contains_jd_and_known_skills():
    llm = _fake([_req("x", "Python")])
    jd = "We need Python. Literal {braces} are fine.\nquote for Python"

    extract_requirements(ExtractRequirementsInput(jd_text=jd, known_skills=["Snowflake"]), llm)

    _, prompt = llm.calls[0]
    assert jd in prompt
    assert "snowflake" in prompt  # caller-supplied, normalized
    assert "kubernetes" in prompt  # seeded from the alias dictionary
    assert "{{" not in prompt


def test_llm_canonical_is_used_then_normalized():
    result = _run([_req("a", "AI technologies", canonical="Artificial-Intelligence")])
    assert result.requirements[0].canonical_skill == "artificial intelligence"


def test_empty_canonical_falls_back_to_skill():
    result = _run([_req("a", "K8s", canonical="")])
    assert result.requirements[0].canonical_skill == "kubernetes"


def test_dedupes_by_canonical_skill_and_renumbers():
    result = _run(
        [
            _req("a", "K8s", priority="preferred"),
            _req("b", "Python"),
            _req("c", "Kubernetes", priority="required", years=2),
        ]
    )

    assert [r.id for r in result.requirements] == ["req-1", "req-2"]
    assert [r.canonical_skill for r in result.requirements] == ["kubernetes", "python"]
    k8s = result.requirements[0]
    assert k8s.skill == "K8s"  # first occurrence's text wins
    assert k8s.priority == Priority.REQUIRED  # required beats preferred
    assert k8s.years_required == 2


def test_merges_aliased_skills():
    result = _run([_req("a", "Data Structures"), _req("b", "Algorithms"), _req("c", "Written Communication")])
    assert [r.canonical_skill for r in result.requirements] == [
        "data structures and algorithms",
        "communication",
    ]


def test_any_of_groups_are_relabelled_in_order():
    result = _run(
        [
            _req("a", "Go", group="langs-b"),
            _req("b", "Rust", group="langs-b"),
            _req("c", "JavaScript", group="x"),
            _req("d", "Python", group="x"),
        ]
    )
    assert [(r.canonical_skill, r.any_of_group) for r in result.requirements] == [
        ("go", "group-1"),
        ("rust", "group-1"),
        ("javascript", "group-2"),
        ("python", "group-2"),
    ]
    assert all(r.priority == Priority.REQUIRED for r in result.requirements)


def test_standalone_occurrence_pulls_skill_out_of_group():
    # "Python required" elsewhere + "JavaScript or Python": Python is standalone,
    # JavaScript is left alone in its group, so it becomes a preferred standalone.
    result = _run(
        [
            _req("a", "Python"),
            _req("b", "JavaScript", group="g"),
            _req("c", "Python", group="g"),
        ]
    )
    by_skill = {r.canonical_skill: r for r in result.requirements}
    assert by_skill["python"].any_of_group is None
    assert by_skill["python"].priority == Priority.REQUIRED
    assert by_skill["javascript"].any_of_group is None
    assert by_skill["javascript"].priority == Priority.PREFERRED


def test_default_fake_responses():
    result = extract_requirements(ExtractRequirementsInput(jd_text=DEFAULT_JD_TEXT), FakeLLMClient())
    assert len(result.requirements) == 5


def test_rejects_empty_jd():
    with pytest.raises(ValueError):
        ExtractRequirementsInput(jd_text="   ")


# ---------- quotes ----------


@pytest.mark.parametrize(
    "quote",
    [
        "Built REST APIs in Python",  # exact
        "• built rest apis in python",  # bullet + case
        "Built REST\n   APIs in Python",  # PDF line wrap
        "Built REST APIs in Python’s ecosystem",  # smart quote vs straight
    ],
)
def test_quote_in_text_ignores_formatting_noise(quote):
    resume = "Experience\n- Built REST APIs in Python's ecosystem for 3 teams"
    assert quote_in_text(quote, resume)


def test_quote_in_text_rejects_changed_words():
    assert not quote_in_text("Built GraphQL APIs in Python", "Built REST APIs in Python")
    assert not quote_in_text("   ", "anything")


# ---------- Stage 2: extract evidence ----------


def _ev(id: str, line: str, skills: list[tuple[str, str]] | None = None, section: str = "experience") -> dict:
    return {
        "id": id,
        "section": section,
        "line": line,
        "skills": [{"skill": s, "canonical_skill": c} for s, c in (skills or [])],
    }


def _run_evidence(items: list[dict], resume: str) -> EvidenceExtraction:
    llm = FakeLLMClient({"EvidenceExtraction": json.dumps({"items": items})})
    return extract_evidence(ExtractEvidenceInput(resume_text=resume), llm)


RESUME = """Jane Doe | jane@example.com
EXPERIENCE
• Built REST APIs in Python and FastAPI serving
  10k daily users
• Deployed services to Google Cloud Run
SKILLS
Python, Postgres, Docker
"""


def test_evidence_prompt_contains_resume_and_vocabulary():
    resume = "My resume {x}"
    llm = FakeLLMClient({"EvidenceExtraction": json.dumps({"items": [_ev("a", resume)]})})
    extract_evidence(ExtractEvidenceInput(resume_text=resume, known_skills=["Snowflake"]), llm)
    _, prompt = llm.calls[0]
    assert "My resume {x}" in prompt
    assert "snowflake" in prompt
    assert "{{" not in prompt


def test_evidence_drops_lines_not_in_resume_and_renumbers():
    result = _run_evidence(
        [
            _ev("a", "Built REST APIs in Python and FastAPI serving 10k daily users", [("Python", "python")]),
            _ev("b", "Led a team of 12 engineers on Kubernetes migration"),  # hallucinated
            _ev("c", "Deployed services to Google Cloud Run", [("Google Cloud Run", "gcp")]),
        ],
        RESUME,
    )
    assert [(i.id, i.line) for i in result.items] == [
        ("ev-1", "Built REST APIs in Python and FastAPI serving 10k daily users"),
        ("ev-2", "Deployed services to Google Cloud Run"),
    ]


def test_evidence_dedupes_lines_and_skills():
    result = _run_evidence(
        [
            _ev("a", "Python, Postgres, Docker", [("Postgres", "postgres"), ("PostgreSQL", "postgresql")], "skills"),
            _ev("b", "• Python, Postgres, Docker", [("Python", "python")], "skills"),
        ],
        RESUME,
    )
    assert len(result.items) == 1
    assert [s.canonical_skill for s in result.items[0].skills] == ["postgresql"]


def test_evidence_fails_if_nothing_is_verbatim():
    with pytest.raises(LLMError):
        _run_evidence([_ev("a", "Invented line")], RESUME)


def _default_resume() -> str:
    evidence = json.loads(DEFAULT_RESPONSES["EvidenceExtraction"])
    return "\n".join(i["line"] for i in evidence["items"])


def test_default_fake_evidence_lines_survive_verbatim_check():
    result = extract_evidence(ExtractEvidenceInput(resume_text=_default_resume()), FakeLLMClient())
    assert len(result.items) == 4


# ---------- Stage 3: match ----------


def _match_input(requirements: list[dict], evidence_items: list[dict]) -> MatchInput:
    return MatchInput(
        requirements=RequirementsExtraction(role_title="Eng", requirements=requirements),
        evidence=EvidenceExtraction(items=evidence_items),
    )


def _decision(req_id: str, bucket: str, ev_id: str | None = None) -> dict:
    return {"requirement_id": req_id, "bucket": bucket, "evidence_id": ev_id, "rationale": "r"}


def _run_match(inp: MatchInput, decisions: list[dict] | list[list[dict]]) -> MatchResult:
    if decisions and isinstance(decisions[0], list):  # queued attempts
        responses = [json.dumps({"decisions": d}) for d in decisions]
    else:
        responses = json.dumps({"decisions": decisions})
    return match(inp, FakeLLMClient({"MatchDecisions": responses}))


EV_BULLET = _ev("ev-1", "Built REST APIs in Python", [("Python", "python")], "experience")
EV_SKILLS = _ev("ev-2", "Skills: Python, Go", [("Python", "python"), ("Go", "go")], "skills")
EV_COURSE = _ev("ev-3", "Coursework: Operating Systems", [("Operating Systems", "operating systems")], "education")
EV_DEGREE = _ev("ev-4", "BS, Computer Science", [("Computer Science", "computer science degree")], "education")


def test_match_copies_quote_from_evidence_not_llm():
    inp = _match_input([_req("req-1", "Python")], [EV_BULLET])
    result = _run_match(inp, [_decision("req-1", "covered", "ev-1")])
    m = result.matches[0]
    assert (m.bucket, m.evidence_id, m.evidence_quote) == (Bucket.COVERED, "ev-1", "Built REST APIs in Python")


def test_match_downgrades_covered_on_skills_list_or_coursework():
    inp = _match_input(
        [_req("req-1", "Go"), _req("req-2", "Operating Systems"), _req("req-3", "CS degree", "computer science degree")],
        [EV_SKILLS, EV_COURSE, EV_DEGREE],
    )
    inp.requirements.requirements[2].category = "credential"
    result = _run_match(
        inp,
        [_decision("req-1", "covered", "ev-2"), _decision("req-2", "covered", "ev-3"), _decision("req-3", "covered", "ev-4")],
    )
    # Go on a skills list -> underemphasized. "Operating Systems" is a concept (generic noun),
    # and coursework is how concepts are shown -> stays covered. A degree is a credential -> covered.
    assert [m.bucket for m in result.matches] == [Bucket.UNDEREMPHASIZED, Bucket.COVERED, Bucket.COVERED]


def test_match_downgrades_tool_the_line_does_not_name():
    ev = _ev("ev-1", "Built a CI/CD pipeline with GitHub Actions", [("CI/CD", "ci/cd")], "experience")
    inp = _match_input([_req("req-1", "Docker")], [ev])
    m = _run_match(inp, [_decision("req-1", "covered", "ev-1")]).matches[0]
    assert m.bucket == Bucket.TRANSFERABLE
    assert m.rationale == "Your resume doesn't name Docker; this line is the closest related experience."
    assert m.evidence_quote == ev["line"]  # evidence is kept


def test_match_finds_naming_line_the_llm_missed():
    skills = _ev("ev-1", "Skills: Python, JavaScript", [("JavaScript", "javascript")], "skills")
    project = _ev("ev-2", "Built a JavaScript frontend for a journaling app", [], "project")
    inp = _match_input([_req("req-1", "JavaScript")], [skills, project])
    m = _run_match(inp, [_decision("req-1", "transferable", "ev-1")]).matches[0]
    assert (m.bucket, m.evidence_id) == (Bucket.COVERED, "ev-2")


def test_match_prefers_experience_line_over_skills_line():
    inp = _match_input([_req("req-1", "Python")], [EV_SKILLS, EV_BULLET])
    m = _run_match(inp, [_decision("req-1", "underemphasized", "ev-2")]).matches[0]
    assert (m.bucket, m.evidence_id) == (Bucket.COVERED, "ev-1")


def test_match_overrides_gap_when_skills_list_names_it():
    inp = _match_input([_req("req-1", "Go")], [EV_SKILLS])
    m = _run_match(inp, [_decision("req-1", "gap")]).matches[0]
    assert (m.bucket, m.evidence_id) == (Bucket.UNDEREMPHASIZED, "ev-2")
    assert "listed in your skills" in m.rationale


def test_match_concepts_skip_name_check():
    ev = _ev("ev-1", "Standardized architecture docs with PlantUML diagrams", [], "experience")
    inp = _match_input([_req("req-1", "Technical Documentation")], [ev])
    inp.requirements.requirements[0].category = "concept"
    m = _run_match(inp, [_decision("req-1", "covered", "ev-1")]).matches[0]
    assert m.bucket == Bucket.COVERED


def test_match_c_does_not_match_cpp():
    inp = _match_input([_req("req-1", "C")], [_ev("ev-1", "Wrote a renderer in C++", [], "experience")])
    m = _run_match(inp, [_decision("req-1", "covered", "ev-1")]).matches[0]
    assert m.bucket == Bucket.TRANSFERABLE


@pytest.mark.parametrize(
    ("skill", "line"),
    [
        ("PostgreSQL", "Stored events in Postgres"),  # alias in text
        ("Large Language Models", "Integrated a locally hosted Mistral LLM"),  # alias "llm"
        ("C++", "Wrote a renderer in C++ and OpenGL"),  # punctuation in term
        ("AWS", "Deployed with AWS CloudFront"),  # product of platform
    ],
)
def test_match_keeps_covered_when_line_names_skill(skill, line):
    inp = _match_input([_req("req-1", skill)], [_ev("ev-1", line, [], "experience")])
    m = _run_match(inp, [_decision("req-1", "covered", "ev-1")]).matches[0]
    assert m.bucket == Bucket.COVERED


def test_match_name_check_is_whole_word():
    inp = _match_input([_req("req-1", "Go")], [_ev("ev-1", "Ongoing work on going concerns", [], "experience")])
    m = _run_match(inp, [_decision("req-1", "covered", "ev-1")]).matches[0]
    assert m.bucket == Bucket.TRANSFERABLE


def test_match_soft_skills_skip_name_check():
    inp = _match_input([_req("req-1", "Teamwork")], [_ev("ev-1", "Built an app with three classmates", [], "project")])
    inp.requirements.requirements[0].category = "soft_skill"
    m = _run_match(inp, [_decision("req-1", "covered", "ev-1")]).matches[0]
    assert m.bucket == Bucket.COVERED


def test_match_marks_group_members_satisfied_by_best_member():
    inp = _match_input(
        [
            _req("req-1", "JavaScript", group="group-1"),
            _req("req-2", "TypeScript", group="group-1"),
            _req("req-3", "Python", group="group-1"),
            _req("req-4", "Kubernetes"),
        ],
        [EV_BULLET],
    )
    result = _run_match(
        inp,
        [
            _decision("req-1", "gap"),
            _decision("req-2", "transferable", "ev-1"),
            _decision("req-3", "covered", "ev-1"),
            _decision("req-4", "gap"),
        ],
    )
    assert [m.satisfied_by for m in result.matches] == ["req-3", "req-3", None, None]


def test_match_retries_on_unknown_evidence_id_then_succeeds():
    inp = _match_input([_req("req-1", "Python")], [EV_BULLET])
    result = _run_match(
        inp,
        [[_decision("req-1", "covered", "ev-99")], [_decision("req-1", "covered", "ev-1")]],
    )
    assert result.matches[0].evidence_id == "ev-1"


def test_match_fails_when_requirement_missing_twice():
    inp = _match_input([_req("req-1", "Python"), _req("req-2", "Go")], [EV_BULLET])
    with pytest.raises(LLMError):
        _run_match(inp, [[_decision("req-1", "gap")], [_decision("req-1", "gap")]])


def test_match_with_default_fake_pipeline():
    llm = FakeLLMClient()
    reqs = extract_requirements(ExtractRequirementsInput(jd_text=DEFAULT_JD_TEXT), llm)
    evidence = extract_evidence(ExtractEvidenceInput(resume_text=_default_resume()), llm)
    result = match(MatchInput(requirements=reqs, evidence=evidence), llm)
    assert [m.bucket for m in result.matches] == [
        Bucket.COVERED,
        Bucket.GAP,
        Bucket.TRANSFERABLE,
        Bucket.UNDEREMPHASIZED,
        Bucket.COVERED,
    ]
    assert all(m.evidence_quote in _default_resume() for m in result.matches if m.evidence_quote)


# ---------- Stage 4: suggest rewrites ----------


def _m(req_id: str, bucket: str, ev: dict | None = None, satisfied_by: str | None = None) -> dict:
    return {
        "requirement_id": req_id,
        "bucket": bucket,
        "evidence_id": ev["id"] if ev else None,
        "evidence_quote": ev["line"] if ev else None,
        "rationale": "r",
        "satisfied_by": satisfied_by,
    }


EV_CLOUD = _ev("ev-5", "Deployed services to Cloud Run in 3 regions", [("Cloud Run", "gcp")], "experience")


def _rewrite_input(reqs: list[dict], evs: list[dict], matches: list[dict]) -> RewriteInput:
    return RewriteInput(
        requirements=RequirementsExtraction(role_title="Eng", requirements=reqs),
        evidence=EvidenceExtraction(items=evs),
        matches=MatchResult(matches=matches),
    )


def _draft(ev_id: str, line: str, req_ids: list[str]) -> dict:
    return {"evidence_id": ev_id, "suggested_line": line, "requirement_ids": req_ids, "reason": "why"}


def _run_rewrites(inp: RewriteInput, drafts: list[dict] | list[list[dict]]):
    if drafts and isinstance(drafts[0], list):
        responses = [json.dumps({"rewrites": d}) for d in drafts]
    else:
        responses = json.dumps({"rewrites": drafts})
    llm = FakeLLMClient({"RewriteDrafts": responses})
    return suggest_rewrites(inp, llm), llm


def test_rewrites_skip_llm_when_nothing_to_surface():
    inp = _rewrite_input([_req("req-1", "Python")], [EV_BULLET], [_m("req-1", "covered", EV_BULLET)])
    result, llm = _run_rewrites(inp, [])
    assert result.rewrites == [] and llm.calls == []


# A concept the line shows without the JD's keyword: the honest rewrite surfaces "CI/CD".
EV_CI = _ev("ev-7", "Set up GitHub Actions to run tests on every pull request in 3 repos", [], "experience")
CI_REWRITE = "Set up CI/CD with GitHub Actions to run tests on every pull request in 3 repos"


def _cicd(id: str = "req-2") -> dict:
    r = _req(id, "CI/CD", "ci/cd")
    r["category"] = "concept"
    return r


def test_rewrites_target_only_lines_that_can_honestly_gain_the_keyword():
    reqs = [_req("req-1", "Go"), _cicd(), _req("req-3", "AWS"), _req("req-4", "Rust", group="group-1")]
    matches = [
        _m("req-1", "underemphasized", EV_SKILLS),  # skills list: rewording it adds nothing
        _m("req-2", "underemphasized", EV_CI),  # target
        _m("req-3", "transferable", EV_CLOUD),  # can't add "AWS" to a Cloud Run line: project instead
        _m("req-4", "transferable", EV_CLOUD, satisfied_by="req-9"),  # optional group member
    ]
    _, llm = _run_rewrites(_rewrite_input(reqs, [EV_SKILLS, EV_CLOUD, EV_CI], matches), [])
    prompt = llm.calls[0][1]
    assert "ev-7 | experience" in prompt and "req-2" in prompt
    for absent in ("ev-2 |", "ev-5 |", "req-3", "req-4"):
        assert absent not in prompt


def test_rewrites_copy_original_line_from_evidence():
    inp = _rewrite_input([_cicd()], [EV_CI], [_m("req-2", "underemphasized", EV_CI)])
    result, _ = _run_rewrites(inp, [_draft("ev-7", CI_REWRITE, ["req-2"])])
    assert result.rewrites[0].original_line == EV_CI["line"]


@pytest.mark.parametrize(
    "suggested",
    [
        "Set up CI/CD with GitHub Actions to run tests on every pull request in 12 repos",  # invented number
        "Set up CI/CD with Jenkins and GitHub Actions for every pull request in 3 repos",  # adds a JD technology
        "Automated testing with GitHub Actions on every pull request in 3 repos",  # keyword missing
        "set up github actions to run tests on every pull request in 3 repos",  # no real change
    ],
)
def test_rewrites_drop_dishonest_empty_or_keywordless_rewrites(suggested):
    reqs = [_cicd(), _req("req-5", "Jenkins")]
    inp = _rewrite_input(reqs, [EV_CI], [_m("req-2", "underemphasized", EV_CI)])
    result, _ = _run_rewrites(inp, [_draft("ev-7", suggested, ["req-2"])])
    assert result.rewrites == []


def test_rewrites_retry_when_llm_targets_unlisted_line():
    inp = _rewrite_input([_cicd()], [EV_BULLET, EV_CI], [_m("req-2", "underemphasized", EV_CI)])
    bad = [_draft("ev-1", "Built Python REST APIs with CI/CD", ["req-2"])]
    result, llm = _run_rewrites(inp, [bad, [_draft("ev-7", CI_REWRITE, ["req-2"])]])
    assert len(llm.calls) == 2 and result.rewrites[0].evidence_id == "ev-7"


def test_rewrites_keep_one_per_line():
    inp = _rewrite_input([_cicd()], [EV_CI], [_m("req-2", "underemphasized", EV_CI)])
    other = "Built CI/CD in GitHub Actions running tests on every pull request in 3 repos"
    result, _ = _run_rewrites(inp, [_draft("ev-7", CI_REWRITE, ["req-2"]), _draft("ev-7", other, ["req-2"])])
    assert [r.suggested_line for r in result.rewrites] == [CI_REWRITE]


# ---------- Stage 5: recommend gaps ----------


def _project(hours: int = 8) -> dict:
    return {"title": "Build a thing", "description": "Build it.", "estimated_hours": hours}


def _rec(req_id: str, projects: list[dict] | None = None, url: str | None = None) -> dict:
    return {
        "requirement_id": req_id,
        "projects": projects if projects is not None else [_project()],
        "resource_type": "official_docs",
        "resource_title": f"{req_id} docs",
        "resource_url": url,
    }


def _recommend_input(reqs: list[dict], matches: list[dict]) -> RecommendInput:
    return RecommendInput(
        requirements=RequirementsExtraction(role_title="Eng", requirements=reqs),
        evidence=EvidenceExtraction(items=[EV_BULLET, EV_CLOUD]),
        matches=MatchResult(matches=matches),
    )


def _run_recommend(inp: RecommendInput, attempts: list[list[dict]], live_urls: set[str] = frozenset()):
    llm = FakeLLMClient({"GapRecommendationDrafts": [json.dumps({"recommendations": a}) for a in attempts]})
    return recommend_gaps(inp, llm, lambda url: url in live_urls), llm


def _gap_scenario() -> RecommendInput:
    reqs = [
        _req("req-1", "Docker", priority="preferred"),
        _req("req-2", "CS degree", "computer science degree"),
        _req("req-3", "Kubernetes"),
        _req("req-4", "TypeScript", group="group-1"),
        _req("req-5", "Python", group="group-1"),
        _req("req-6", "AWS"),
    ]
    reqs[1]["category"] = "credential"
    matches = [
        _m("req-1", "gap"),
        _m("req-2", "gap"),
        _m("req-3", "gap"),
        _m("req-4", "gap", satisfied_by="req-5"),
        _m("req-5", "covered", EV_BULLET),
        _m("req-6", "transferable", EV_CLOUD),
    ]
    return _recommend_input(reqs, matches)


def test_recommend_targets_and_orders_required_first():
    result, llm = _run_recommend(_gap_scenario(), [[_rec("req-1"), _rec("req-6"), _rec("req-3")]])
    assert [r.requirement_id for r in result.recommendations] == ["req-3", "req-6", "req-1"]
    prompt = llm.calls[0][1]
    assert "req-2" not in prompt and "req-4" not in prompt and "req-5" not in prompt  # credential, satisfied, covered
    assert "python" in prompt  # candidate's existing skills are offered


def test_recommend_skips_llm_when_nothing_missing():
    inp = _recommend_input([_req("req-1", "Python")], [_m("req-1", "covered", EV_BULLET)])
    result, llm = _run_recommend(inp, [])
    assert result.recommendations == [] and llm.calls == []


@pytest.mark.parametrize(
    "bad",
    [
        [_rec("req-1"), _rec("req-3")],  # req-6 missing
        [_rec("req-1"), _rec("req-3"), _rec("req-6", projects=[_project(hours=40)])],  # not a weekend
        [_rec("req-1"), _rec("req-3"), _rec("req-6", projects=[])],  # no projects
        [_rec("req-1"), _rec("req-3"), _rec("req-6", projects=[_project()] * 4)],  # too many
        [_rec("req-1"), _rec("req-3"), _rec("req-6", url="http://example.com/aws")],  # not https
    ],
)
def test_recommend_retries_invalid_output(bad):
    good = [_rec("req-1"), _rec("req-3"), _rec("req-6")]
    result, llm = _run_recommend(_gap_scenario(), [bad, good])
    assert len(llm.calls) == 2 and len(result.recommendations) == 3


def test_recommend_shows_only_verified_urls_and_searches_otherwise():
    attempts = [
        [
            _rec("req-1", url="https://docs.docker.com/get-started/"),  # live
            _rec("req-3", url="https://kubernetes.io/made-up-page"),  # dead
            _rec("req-6"),  # model wasn't sure
        ]
    ]
    result, _ = _run_recommend(_gap_scenario(), attempts, live_urls={"https://docs.docker.com/get-started/"})
    by_id = {r.requirement_id: r for r in result.recommendations}
    assert (by_id["req-1"].resource_url, by_id["req-1"].resource_url_verified) == (
        "https://docs.docker.com/get-started/",
        True,
    )
    for rid in ("req-3", "req-6"):
        assert not by_id[rid].resource_url_verified
        assert by_id[rid].resource_url == f"https://www.google.com/search?q={rid}+docs"


def test_recommend_keeps_multiple_projects():
    projects = [_project(4), _project(8), _project(14)]
    result, _ = _run_recommend(_gap_scenario(), [[_rec("req-1", projects), _rec("req-3"), _rec("req-6")]])
    assert [p.estimated_hours for p in result.recommendations[-1].projects] == [4, 8, 14]


def test_full_default_fake_pipeline():
    llm = FakeLLMClient()
    reqs = extract_requirements(ExtractRequirementsInput(jd_text=DEFAULT_JD_TEXT), llm)
    evidence = extract_evidence(ExtractEvidenceInput(resume_text=_default_resume()), llm)
    matches = match(MatchInput(requirements=reqs, evidence=evidence), llm)
    rewrites = suggest_rewrites(RewriteInput(requirements=reqs, evidence=evidence, matches=matches), llm)
    recs = recommend_gaps(RecommendInput(requirements=reqs, evidence=evidence, matches=matches), llm, lambda _: True)
    # The demo's only rewrite candidate is AWS-from-Cloud-Run: not honest, so none (a project instead).
    assert rewrites.rewrites == []
    assert [r.requirement_id for r in recs.recommendations] == ["req-2", "req-3"]


# ---------- eligibility, traits, optional group members, implied concepts ----------


def _elig(id: str, kind: str, description: str = "rule") -> dict:
    return {"id": id, "kind": kind, "description": description, "jd_quote": f"quote for {description}"}


def _match_with_eligibility(rules: list[dict], ev_items: list[dict], elig_attempts: list[list[dict]]):
    inp = _match_input([_req("req-1", "Python")], ev_items)
    inp.requirements.eligibility = [EligibilityRequirement.model_validate(r) for r in rules]
    responses = [
        json.dumps({"decisions": [_decision("req-1", "covered", ev_items[0]["id"])], "eligibility": e})
        for e in elig_attempts
    ]
    llm = FakeLLMClient({"MatchDecisions": responses})
    return match(inp, llm, today=date(2026, 11, 14)), llm


def test_eligibility_checks_quote_evidence_and_never_infer_work_authorization():
    degree = _ev("ev-9", "B.S. Computer Science, expected May 2027", [], "education")
    rules = [_elig("elig-1", "graduation_window", "Graduating 2027"), _elig("elig-2", "work_authorization")]
    decisions = [
        {"eligibility_id": "elig-1", "status": "met", "evidence_id": "ev-9", "rationale": "May 2027 is in range."},
        {"eligibility_id": "elig-2", "status": "met", "evidence_id": "ev-9", "rationale": "US school."},
    ]
    result, llm = _match_with_eligibility(rules, [EV_BULLET, degree], [decisions])
    grad, auth = result.eligibility
    assert (grad.status, grad.evidence_quote) == ("met", degree["line"])
    assert (auth.status, auth.evidence_quote) == ("unknown", None)  # overridden: never inferred
    assert "Today's date: 2026-11-14" in llm.calls[0][1]


def test_eligibility_retries_when_a_rule_is_missing():
    rules = [_elig("elig-1", "degree_level")]
    good = [{"eligibility_id": "elig-1", "status": "unknown", "rationale": "Not stated."}]
    result, llm = _match_with_eligibility(rules, [EV_BULLET], [[], good])
    assert len(llm.calls) == 2 and result.eligibility[0].status == "unknown"


def test_requirements_eligibility_is_renumbered():
    payload = {
        "role_title": "Intern",
        "requirements": [_req("x", "Python")],
        "eligibility": [_elig("a", "enrollment", "Returning to school after the internship"), _elig("b", "degree_level", "Pursuing a BS")],
    }
    llm = FakeLLMClient({"RequirementsExtraction": json.dumps(payload)})
    jd = "\n".join(x["jd_quote"] for x in payload["requirements"] + payload["eligibility"])
    result = extract_requirements(ExtractRequirementsInput(jd_text=jd), llm)
    assert [e.id for e in result.eligibility] == ["elig-1", "elig-2"]


def test_other_group_members_become_optional_once_one_is_met():
    reqs = [_req("req-1", "Python", group="group-1"), _req("req-2", "Java", group="group-1")]
    java = _ev("ev-2", "Skills: Python, Java", [("Java", "java"), ("Python", "python")], "skills")
    inp = _match_input(reqs, [EV_BULLET, java])
    result = _run_match(inp, [_decision("req-1", "covered", "ev-1"), _decision("req-2", "underemphasized", "ev-2")])
    assert [(m.bucket, m.satisfied_by) for m in result.matches] == [
        (Bucket.COVERED, None),
        (Bucket.UNDEREMPHASIZED, "req-1"),  # still shown, but optional
    ]


def test_rewrite_for_implied_concept_needs_confirmation_but_stated_work_does_not():
    oop = _req("req-1", "OOP", "object oriented programming")
    oop["category"] = "concept"
    app_line = _ev("ev-6", "Built a journaling app in Python with a FastAPI backend", [], "project")
    matches = [_m("req-1", "transferable", app_line), _m("req-2", "underemphasized", EV_CI)]
    inp = _rewrite_input([oop, _cicd()], [app_line, EV_CI], matches)
    drafts = [
        _draft("ev-6", "Built a journaling app in Python using OOP with a FastAPI backend", ["req-1"]),
        _draft("ev-7", CI_REWRITE, ["req-2"]),
    ]
    result, _ = _run_rewrites(inp, drafts)
    # OOP is only implied by the line -> "only if true"; CI/CD is what the line already describes.
    assert {r.evidence_id: r.needs_confirmation for r in result.rewrites} == {"ev-6": True, "ev-7": False}


def test_recommend_skips_traits_and_implied_concepts():
    trait = _req("req-1", "Passion for Pinterest", "passion for pinterest")
    trait["category"] = "trait"
    oop = _req("req-2", "OOP", "object oriented programming")
    oop["category"] = "concept"
    reqs = [trait, oop, _req("req-3", "Kubernetes")]
    matches = [_m("req-1", "gap"), _m("req-2", "transferable", EV_BULLET), _m("req-3", "gap")]
    result, llm = _run_recommend(_recommend_input(reqs, matches), [[_rec("req-3")]])
    assert [r.requirement_id for r in result.recommendations] == ["req-3"]
    assert "Pinterest" not in llm.calls[0][1] and "OOP" not in llm.calls[0][1]


def test_concept_named_in_coursework_counts_as_covered():
    algo = _req("req-1", "Algorithms", "data structures and algorithms")
    algo["category"] = "concept"
    java = _req("req-2", "Java")  # a technology in a course list stays underemphasized
    course = _ev("ev-3", "Coursework: Design and Analysis of Algorithms, Java Programming", [], "education")
    inp = _match_input([algo, java], [course])
    result = _run_match(inp, [_decision("req-1", "underemphasized", "ev-3"), _decision("req-2", "covered", "ev-3")])
    assert [m.bucket for m in result.matches] == [Bucket.COVERED, Bucket.UNDEREMPHASIZED]


def test_soft_skills_are_examples_not_grades_and_never_rewritten():
    team = _ev("ev-1", "Built a mobile app with a team of four", [], "project")
    comm = _req("req-1", "Communication", "communication")
    comm["category"] = "soft_skill"
    solve = _req("req-2", "Problem solving", "problem solving")
    solve["category"] = "soft_skill"
    inp = _match_input([comm, solve], [team])
    result = _run_match(inp, [_decision("req-1", "underemphasized", "ev-1"), _decision("req-2", "transferable", "ev-1")])
    assert [m.bucket for m in result.matches] == [Bucket.COVERED, Bucket.COVERED]

    rewrites, llm = _run_rewrites(_rewrite_input([comm, solve], [team], [_m("req-1", "underemphasized", team)]), [])
    assert rewrites.rewrites == [] and llm.calls == []  # nothing to rewrite: no LLM call at all


def test_generic_technology_is_judged_like_a_concept_not_by_name():
    tools = _req("req-1", "AI coding tools", "ai coding tools")  # category technology, but generic
    line = _ev("ev-1", "Used Claude Code to accelerate implementation and testing", [], "project")
    result = _run_match(_match_input([tools], [line]), [_decision("req-1", "covered", "ev-1")])
    assert result.matches[0].bucket == Bucket.COVERED  # no "line doesn't name ai coding tools" downgrade


def test_concept_backed_by_coursework_is_covered_even_without_the_jds_wording():
    fundamentals = _req("req-1", "Computer science fundamentals", "computer science fundamentals")
    fundamentals["category"] = "concept"
    course = _ev("ev-3", "Data Structures and Algorithms, Operating Systems, Computer Architecture", [], "education")
    result = _run_match(_match_input([fundamentals], [course]), [_decision("req-1", "underemphasized", "ev-3")])
    assert result.matches[0].bucket == Bucket.COVERED



def _extract(reqs: list[dict], eligibility: list[dict] | None = None) -> RequirementsExtraction:
    payload = {"role_title": "Intern", "requirements": reqs, "eligibility": eligibility or []}
    jd = "\n".join(x["jd_quote"] for x in reqs + (eligibility or []))
    return extract_requirements(ExtractRequirementsInput(jd_text=jd), FakeLLMClient({"RequirementsExtraction": json.dumps(payload)}))


def test_curiosity_about_a_field_becomes_an_optional_trait():
    defi = _req("x", "DeFi/crypto", "defi")
    defi["category"] = "domain_knowledge"
    defi["jd_quote"] = "Curiosity about DeFi/crypto (prior domain experience not required)"
    python = _req("y", "Python")
    python["jd_quote"] = "Strong Python skills and a passion for learning"
    (d, p) = _extract([defi, python]).requirements
    assert (d.category, d.priority) == ("trait", "preferred")
    assert (p.category, p.priority) == ("technology", "required")  # "passion for learning" isn't about Python


def test_duplicate_enrollment_rule_is_dropped_but_real_conditions_stay():
    rules = [
        _elig("a", "degree_level", "Currently pursuing a Bachelor's or Master's degree"),
        _elig("b", "enrollment", "Currently enrolled as a full-time student"),
        _elig("c", "enrollment", "Returning to school after the internship"),
    ]
    result = _extract([_req("x", "Python")], rules)
    assert [e.description for e in result.eligibility] == [
        "Currently pursuing a Bachelor's or Master's degree",
        "Returning to school after the internship",
    ]


def test_student_status_credential_becomes_an_eligibility_rule():
    bs = _req("x", "Computer Science degree", "computer science degree")
    bs["category"] = "credential"
    bs["jd_quote"] = "A rising senior pursuing a BS computer science or related field"
    result = _extract([bs, _req("y", "Python")])
    assert [r.canonical_skill for r in result.requirements] == ["python"]
    assert [(e.kind, e.jd_quote) for e in result.eligibility] == [("degree_level", bs["jd_quote"])]


def test_mission_enthusiasm_is_a_trait_but_domain_experience_is_not():
    mission = _req("x", "Healthcare", "healthcare")
    mission["category"] = "domain_knowledge"
    mission["jd_quote"] = "Inspired by our mission to improve healthcare through technology"
    experience = _req("y", "Payments", "payments")
    experience["category"] = "domain_knowledge"
    experience["jd_quote"] = "Experience with payments systems, and passionate about fintech"
    (m, e) = _extract([mission, experience]).requirements
    assert (m.category, e.category) == ("trait", "domain_knowledge")


def test_code_overrides_llm_on_student_status_degree_rules():
    ms = _ev("ev-8", "Master of Science, Computer Science\tSept. 2026 – Jun. 2028", [], "education")
    rule = _elig("elig-1", "degree_level", "A rising senior pursuing a BS computer science or related field")
    llm_says = [{"eligibility_id": "elig-1", "status": "met", "evidence_id": "ev-8", "rationale": "Has a CS degree."}]
    result, _ = _match_with_eligibility([rule], [EV_BULLET, ms], [llm_says])
    check = result.eligibility[0]
    assert check.status == "not_met" and "master's" in check.rationale and check.evidence_quote == ms["line"]


def test_combined_eligibility_sentence_is_dropped_when_already_split():
    rules = [
        _elig("a", "degree_level", "Currently a junior in an undergraduate program or pursuing a master's degree"),
        _elig("b", "graduation_window", "Expected graduation within approximately 18 months"),
        _elig(
            "c",
            "degree_level",
            "Currently a junior in an undergraduate program or pursuing a master's degree, with an expected graduation date within 18 months",
        ),
    ]
    result = _extract([_req("x", "Python")], rules)
    assert [e.kind for e in result.eligibility] == ["degree_level", "graduation_window"]



def test_override_replaces_the_llms_contradictory_rationale():
    skills = _ev("ev-1", "Languages: Python, JavaScript, C++, Java, HTML/CSS, Rust", [], "skills")
    inp = _match_input([_req("req-1", "TypeScript")], [skills])
    llm = [{"requirement_id": "req-1", "bucket": "underemphasized", "evidence_id": "ev-1",
            "rationale": "Rust is listed in the skills section without a specific project line."}]
    m = _run_match(inp, llm).matches[0]
    assert m.bucket == Bucket.TRANSFERABLE and "Rust" not in m.rationale and "TypeScript" in m.rationale


def test_apis_is_a_kind_of_thing_so_fastapi_work_can_cover_it():
    apis = _req("req-1", "APIs", "apis")  # stage 1 often labels this a technology
    line = _ev("ev-1", "Built a coordination service with FastAPI and MQTT messaging", [], "project")
    m = _run_match(_match_input([apis], [line]), [_decision("req-1", "covered", "ev-1")]).matches[0]
    assert m.bucket == Bucket.COVERED


def test_graduation_rule_naming_undergrad_levels_fails_for_an_ms_student():
    ms = _ev("ev-8", "Master of Science, Computer Science\tSept. 2026 – Jun. 2028", [], "education")
    rule = _elig("elig-1", "graduation_window", "Rising Junior or Senior graduating in 2027 or 2028")
    llm_says = [{"eligibility_id": "elig-1", "status": "met", "evidence_id": "ev-8", "rationale": "Ends June 2028."}]
    result, _ = _match_with_eligibility([rule], [EV_BULLET, ms], [llm_says])
    assert result.eligibility[0].status == "not_met"


def test_graduation_rule_without_levels_keeps_the_date_judgment():
    ms = _ev("ev-8", "Master of Science, Computer Science\tSept. 2026 – Jun. 2028", [], "education")
    rule = _elig("elig-1", "graduation_window", "Graduating between December 2027 and June 2028")
    llm_says = [{"eligibility_id": "elig-1", "status": "met", "evidence_id": "ev-8", "rationale": "Ends June 2028."}]
    result, _ = _match_with_eligibility([rule], [EV_BULLET, ms], [llm_says])
    assert result.eligibility[0].status == "met"


def test_covered_but_unnamed_skill_gets_a_keyword_rewrite():
    dbs = _req("req-1", "databases", "databases")
    dbs["category"] = "concept"
    line = _ev("ev-1", "Stored detection events in GCP Firestore across 74 logged runs", [], "project")
    named = _ev("ev-2", "Built REST APIs in Python", [], "experience")
    matches = [_m("req-1", "covered", line), _m("req-2", "covered", named)]
    inp = _rewrite_input([dbs, _req("req-2", "Python")], [line, named], matches)
    good = _draft("ev-1", "Stored detection events in a GCP Firestore database across 74 logged runs", ["req-1"])
    result, llm = _run_rewrites(inp, [good])
    prompt = llm.calls[0][1]
    assert "ev-1 |" in prompt and "ev-2 |" not in prompt  # Python is already named on its line
    assert [r.needs_confirmation for r in result.rewrites] == [False]  # the line already proves it


def test_universal_soft_skills_are_interview_items_with_clear_names():
    solving = _req("x", "Problem-solving", "problem solving")
    solving["category"] = "concept"  # mislabeled by stage 1
    ambiguity = _req("y", "ambiguity")  # bare noun; canonical comes from the alias
    ambiguity["category"] = "trait"
    reqs = _extract([solving, ambiguity, _req("z", "Python")]).requirements
    assert [(r.skill, r.category) for r in reqs] == [
        ("Problem solving", "soft_skill"),
        ("Navigating ambiguity", "trait"),
        ("Python", "technology"),
    ]


def test_graduation_date_must_be_for_the_degree_level_the_job_wants():
    ms = _ev("ev-8", "Master of Science, Computer Science\tSept. 2026 – Jun. 2028", [], "education")
    bs = _ev("ev-9", "Bachelor of Science, Computer Science\tSept. 2022 – Jun. 2026", [], "education")
    rules = [
        _elig("elig-1", "enrollment", "Open to Sophomore and Junior undergraduate students"),
        _elig("elig-2", "graduation_window", "Expected graduation date of Summer 2028 or Summer 2029"),
    ]
    llm_says = [
        {"eligibility_id": "elig-1", "status": "met", "evidence_id": "ev-8", "rationale": "Enrolled."},
        {"eligibility_id": "elig-2", "status": "met", "evidence_id": "ev-8", "rationale": "MS ends Jun 2028."},
    ]
    result, _ = _match_with_eligibility(rules, [EV_BULLET, ms, bs], [llm_says])
    level, dates = result.eligibility
    assert level.status == "not_met"
    assert dates.status == "not_met" and "bachelor's ended Jun 2026" in dates.rationale
    assert dates.evidence_quote == bs["line"]


def test_graduation_date_for_a_job_open_to_masters_students_is_judged_normally():
    ms = _ev("ev-8", "Master of Science, Computer Science\tSept. 2026 – Jun. 2028", [], "education")
    rules = [
        _elig("elig-1", "degree_level", "Currently pursuing a Bachelor's or Master's degree"),
        _elig("elig-2", "graduation_window", "Graduating in 2028"),
    ]
    llm_says = [
        {"eligibility_id": "elig-1", "status": "met", "evidence_id": "ev-8", "rationale": "In MS."},
        {"eligibility_id": "elig-2", "status": "met", "evidence_id": "ev-8", "rationale": "MS ends Jun 2028."},
    ]
    result, _ = _match_with_eligibility(rules, [EV_BULLET, ms], [llm_says])
    assert [c.status for c in result.eligibility] == ["met", "met"]



def test_invented_requirements_are_dropped_and_non_jds_rejected():
    from app.pipeline.extract_requirements import NotAJobDescription

    real = _req("x", "Python")
    invented = _req("y", "Communication")
    invented["jd_quote"] = "Excellent communication skills"  # not in the JD below
    payload = {"role_title": "Intern", "requirements": [real, invented]}
    llm = FakeLLMClient({"RequirementsExtraction": json.dumps(payload)})
    result = extract_requirements(ExtractRequirementsInput(jd_text=real["jd_quote"]), llm)
    assert [r.canonical_skill for r in result.requirements] == ["python"]

    only_invented = FakeLLMClient({"RequirementsExtraction": json.dumps({"role_title": "?", "requirements": [invented]})})
    with pytest.raises(NotAJobDescription):
        extract_requirements(ExtractRequirementsInput(jd_text="this is not a job description"), only_invented)

    honest = FakeLLMClient({"RequirementsExtraction": json.dumps(
        {"role_title": "?", "requirements": [], "is_job_description": False})})
    with pytest.raises(NotAJobDescription):
        extract_requirements(ExtractRequirementsInput(jd_text="this is not a job description"), honest)
