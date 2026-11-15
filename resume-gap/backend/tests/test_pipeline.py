import json

import pytest

from app.domain.enums import Bucket, Priority
from app.domain.quotes import quote_in_text
from app.domain.schemas import (
    EvidenceExtraction,
    ExtractEvidenceInput,
    ExtractRequirementsInput,
    MatchInput,
    MatchResult,
    RequirementsExtraction,
)
from app.llm.base import LLMError
from app.llm.fake_client import DEFAULT_RESPONSES, FakeLLMClient
from app.pipeline.extract_evidence import extract_evidence
from app.pipeline.extract_requirements import extract_requirements
from app.pipeline.match import match


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
    return extract_requirements(ExtractRequirementsInput(jd_text="jd", **input_kwargs), _fake(requirements))


def test_prompt_contains_jd_and_known_skills():
    llm = _fake([_req("x", "Python")])
    jd = "We need Python. Literal {braces} are fine."

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
    result = extract_requirements(ExtractRequirementsInput(jd_text="jd"), FakeLLMClient())
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
    with pytest.raises(ValueError):
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
    assert [m.bucket for m in result.matches] == [Bucket.UNDEREMPHASIZED, Bucket.UNDEREMPHASIZED, Bucket.COVERED]


def test_match_downgrades_tool_the_line_does_not_name():
    ev = _ev("ev-1", "Built a CI/CD pipeline with GitHub Actions", [("CI/CD", "ci/cd")], "experience")
    inp = _match_input([_req("req-1", "Docker")], [ev])
    m = _run_match(inp, [_decision("req-1", "covered", "ev-1")]).matches[0]
    assert m.bucket == Bucket.TRANSFERABLE
    assert "No line names Docker" in m.rationale
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
    reqs = extract_requirements(ExtractRequirementsInput(jd_text="jd"), llm)
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
