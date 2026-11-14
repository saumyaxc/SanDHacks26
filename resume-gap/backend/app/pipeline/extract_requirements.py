"""Stage 1: JD text -> structured, de-duplicated requirements."""

from pathlib import Path

from app.domain.enums import Priority
from app.domain.schemas import ExtractRequirementsInput, Requirement, RequirementsExtraction
from app.llm.base import LLMClient

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "extract_requirements.md").read_text(
    encoding="utf-8"
)


def extract_requirements(data: ExtractRequirementsInput, llm: LLMClient) -> RequirementsExtraction:
    # str.replace, not .format: JDs can contain literal braces.
    prompt = _PROMPT.replace("{{JD_TEXT}}", data.jd_text)
    raw = llm.complete_json(prompt, RequirementsExtraction)
    return _dedupe_and_renumber(raw)


def _dedupe_and_renumber(extraction: RequirementsExtraction) -> RequirementsExtraction:
    """One requirement per canonical skill, so cross-JD counts aren't inflated.

    On merge: first occurrence's text wins, REQUIRED beats PREFERRED, max years wins.
    """
    merged: dict[str, Requirement] = {}
    for req in extraction.requirements:
        key = req.canonical_skill
        if not key:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = req
            continue
        years = [y for y in (existing.years_required, req.years_required) if y is not None]
        merged[key] = existing.model_copy(
            update={
                "priority": Priority.REQUIRED
                if Priority.REQUIRED in (existing.priority, req.priority)
                else Priority.PREFERRED,
                "years_required": max(years) if years else None,
            }
        )

    # Re-construct (not model_copy) so the non-empty / unique-id validators run again.
    return RequirementsExtraction(
        role_title=extraction.role_title,
        company=extraction.company,
        requirements=[
            r.model_copy(update={"id": f"req-{i}"}) for i, r in enumerate(merged.values(), start=1)
        ],
    )
