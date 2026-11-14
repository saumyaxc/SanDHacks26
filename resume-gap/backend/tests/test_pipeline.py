import json

import pytest

from app.domain.enums import Priority
from app.domain.schemas import ExtractRequirementsInput, RequirementsExtraction
from app.llm.fake_client import FakeLLMClient
from app.pipeline.extract_requirements import extract_requirements


def _req(id: str, skill: str, priority: str = "required", years: int | None = None) -> dict:
    return {
        "id": id,
        "skill": skill,
        "category": "tool",
        "priority": priority,
        "years_required": years,
        "jd_quote": f"quote for {skill}",
    }


def _fake(requirements: list[dict]) -> FakeLLMClient:
    payload = {"role_title": "Engineer", "company": None, "requirements": requirements}
    return FakeLLMClient({"RequirementsExtraction": json.dumps(payload)})


def test_extract_requirements_fills_prompt():
    llm = _fake([_req("x", "Python")])
    jd = "We need Python. Literal {braces} are fine."

    extract_requirements(ExtractRequirementsInput(jd_text=jd), llm)

    _, prompt = llm.calls[0]
    assert jd in prompt
    assert "{{JD_TEXT}}" not in prompt


def test_extract_requirements_dedupes_by_canonical_skill_and_renumbers():
    llm = _fake(
        [
            _req("a", "K8s", priority="preferred"),
            _req("b", "Python"),
            _req("c", "Kubernetes", priority="required", years=2),
        ]
    )

    result = extract_requirements(ExtractRequirementsInput(jd_text="jd"), llm)

    assert [r.id for r in result.requirements] == ["req-1", "req-2"]
    assert [r.canonical_skill for r in result.requirements] == ["kubernetes", "python"]
    k8s = result.requirements[0]
    assert k8s.skill == "K8s"  # first occurrence's text wins
    assert k8s.priority == Priority.REQUIRED  # required beats preferred
    assert k8s.years_required == 2


def test_extract_requirements_with_default_fake_responses():
    result = extract_requirements(ExtractRequirementsInput(jd_text="jd"), FakeLLMClient())
    assert isinstance(result, RequirementsExtraction)
    assert len(result.requirements) == 5


def test_extract_requirements_rejects_empty_jd():
    with pytest.raises(ValueError):
        ExtractRequirementsInput(jd_text="   ")
