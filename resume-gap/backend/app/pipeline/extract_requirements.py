"""Stage 1: JD text -> structured, de-duplicated requirements."""

from collections import Counter
from pathlib import Path

from app.domain.enums import Priority
from app.domain.schemas import ExtractRequirementsInput, Requirement, RequirementsExtraction
from app.domain.skills import skill_vocabulary
from app.llm.base import LLMClient

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "extract_requirements.md").read_text(
    encoding="utf-8"
)


def extract_requirements(data: ExtractRequirementsInput, llm: LLMClient) -> RequirementsExtraction:
    # str.replace, not .format: JDs can contain literal braces. JD goes last so its
    # text is never scanned for placeholders.
    prompt = _PROMPT.replace("{{KNOWN_SKILLS}}", ", ".join(skill_vocabulary(data.known_skills))).replace(
        "{{JD_TEXT}}", data.jd_text
    )
    raw = llm.complete_json(prompt, RequirementsExtraction)
    return _clean(raw)


def _clean(extraction: RequirementsExtraction) -> RequirementsExtraction:
    requirements = _normalize_groups(_dedupe(extraction.requirements))
    # Re-construct (not model_copy) so the non-empty / unique-id validators run again.
    return RequirementsExtraction(
        role_title=extraction.role_title,
        company=extraction.company,
        requirements=[
            r.model_copy(update={"id": f"req-{i}"}) for i, r in enumerate(requirements, start=1)
        ],
        eligibility=[
            e.model_copy(update={"id": f"elig-{i}"}) for i, e in enumerate(extraction.eligibility, start=1)
        ],
    )


def _dedupe(requirements: list[Requirement]) -> list[Requirement]:
    """One requirement per canonical skill, so cross-JD counts aren't inflated.

    On merge: first occurrence's text wins, REQUIRED beats PREFERRED, max years wins,
    and the group survives only if both occurrences are in the same group.
    """
    merged: dict[str, Requirement] = {}
    for req in requirements:
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
                "any_of_group": existing.any_of_group
                if existing.any_of_group == req.any_of_group
                else None,
            }
        )
    return list(merged.values())


def _normalize_groups(requirements: list[Requirement]) -> list[Requirement]:
    """Relabel groups group-1..N in order of appearance.

    A group with a single member isn't a choice anymore; it becomes a standalone
    PREFERRED requirement so a lone leftover option never reads as required.
    """
    sizes = Counter(r.any_of_group for r in requirements if r.any_of_group)
    labels: dict[str, str] = {}
    out: list[Requirement] = []
    for r in requirements:
        group = r.any_of_group
        if group is None:
            out.append(r)
        elif sizes[group] < 2:
            out.append(r.model_copy(update={"any_of_group": None, "priority": Priority.PREFERRED}))
        else:
            labels.setdefault(group, f"group-{len(labels) + 1}")
            out.append(r.model_copy(update={"any_of_group": labels[group]}))
    return out
