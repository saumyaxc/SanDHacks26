import json

import pytest

from app.domain.enums import Priority
from app.domain.quotes import quote_in_text
from app.domain.schemas import (
    EvidenceExtraction,
    ExtractEvidenceInput,
    ExtractRequirementsInput,
    RequirementsExtraction,
)
from app.llm.fake_client import DEFAULT_RESPONSES, FakeLLMClient
from app.pipeline.extract_evidence import extract_evidence
from app.pipeline.extract_requirements import extract_requirements


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
        "category": "tool",
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


def test_default_fake_evidence_lines_are_consistent_with_matches():
    evidence = json.loads(DEFAULT_RESPONSES["EvidenceExtraction"])
    resume = "\n".join(i["line"] for i in evidence["items"])
    result = extract_evidence(ExtractEvidenceInput(resume_text=resume), FakeLLMClient())
    assert len(result.items) == 4
