import json

import pytest

from app.domain.enums import Priority
from app.domain.schemas import ExtractRequirementsInput, RequirementsExtraction
from app.llm.fake_client import FakeLLMClient
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
