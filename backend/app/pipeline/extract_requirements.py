"""Stage 1: JD text -> structured, de-duplicated requirements.

Code backstops on the LLM's labels, read from the JD's own wording (plain English, not skills):
- Universal soft skills (skills.SOFT_SKILLS: problem solving, navigating ambiguity, ...) are
  always interview material, with one consistent display name.
- "curiosity about / interest in / passion for X" makes X a trait (interview material).
- "not required", "a plus", "nice to have", "bonus" in its JD sentence make it preferred.
- An enrollment rule that only restates "currently pursuing a degree" is dropped as a duplicate.
- Every requirement and eligibility rule must quote the JD verbatim, or it's dropped (an
  invented requirement can't quote text that isn't there). Nothing left -> NotAJobDescription.
- A "credential" phrased as student status ("a rising senior pursuing a BS") is moved to
  eligibility, where it's checked against the candidate's CURRENT program, not their degrees.
- A domain item from a mission/inspiration sentence with no experience or knowledge asked
  ("inspired by our mission to improve healthcare") is a trait.
"""

import logging
import re
from collections import Counter
from pathlib import Path

from app.domain.enums import EligibilityKind, Priority, SkillCategory
from app.domain.schemas import (
    EligibilityRequirement,
    ExtractRequirementsInput,
    Requirement,
    RequirementsExtraction,
)
from app.domain.quotes import quote_in_text
from app.domain.skills import display_name, is_soft_skill, skill_vocabulary
from app.llm.base import LLMClient

log = logging.getLogger(__name__)

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
    if not raw.is_job_description:
        raise NotAJobDescription("This doesn't look like a job description. Paste the full job posting.")
    real = raw.model_copy(
        update={
            "requirements": [r for r in raw.requirements if quote_in_text(r.jd_quote, data.jd_text)],
            "eligibility": [e for e in raw.eligibility if quote_in_text(e.jd_quote, data.jd_text)],
        }
    )
    dropped = len(raw.requirements) - len(real.requirements)
    if dropped:
        log.warning("dropped %d requirement(s) whose quote isn't in the job description", dropped)
    if not real.requirements:
        raise NotAJobDescription(
            "Couldn't find any requirements in that text. Paste the full job posting, including its qualifications."
        )
    return _clean(real)


class NotAJobDescription(ValueError):
    """The JD text has no real requirements (wrong text pasted). Safe to show the user."""


def _clean(extraction: RequirementsExtraction) -> RequirementsExtraction:
    student_rules = [r for r in extraction.requirements if _is_student_status_credential(r)]
    kept = [r for r in extraction.requirements if r not in student_rules]
    if not kept:  # the schema needs at least one requirement; leave things as they are
        kept, student_rules = list(extraction.requirements), []
    requirements = _normalize_groups(_dedupe([_backstop(r) for r in kept]))
    eligibility = list(extraction.eligibility) + [
        EligibilityRequirement(
            id="moved", kind=EligibilityKind.DEGREE_LEVEL, description=r.jd_quote[:160], jd_quote=r.jd_quote
        )
        for r in student_rules
    ]
    # Re-construct (not model_copy) so the non-empty / unique-id validators run again.
    return RequirementsExtraction(
        role_title=extraction.role_title,
        company=extraction.company,
        requirements=[
            r.model_copy(update={"id": f"req-{i}"}) for i, r in enumerate(requirements, start=1)
        ],
        eligibility=[
            e.model_copy(update={"id": f"elig-{i}"})
            for i, e in enumerate(_dedupe_eligibility(eligibility), start=1)
        ],
    )


_INTEREST = re.compile(
    r"\b(curiosity|curious|interest|interested|passion|passionate|enthusiasm|enthusiastic|excited|excitement|love)"
    r"\s+(about|in|for|toward|towards)\s+(the\s+)?$",
    re.I,
)
_OPTIONAL = re.compile(
    r"\bnot\s+(required|necessary|needed|a\s+requirement)\b|\bnice[\s-]to[\s-]have\b|\ba\s+plus\b|\bbonus\b",
    re.I,
)


_STUDENT_STATUS = re.compile(r"\b(pursuing|currently\s+enrolled|rising\s+(sophomore|junior|senior)|undergraduate\s+student)\b", re.I)
_MISSION = re.compile(
    r"\b(inspired|motivated|driven|excited|passionate|passion|mission|believe|care\s+(deeply\s+)?about)\b", re.I
)
_EXPERIENCE = re.compile(
    r"\b(experience|experienced|knowledge|knowledgeable|background|familiarity|familiar|understanding|worked|"
    r"expertise|proficien\w*|skills?|years?)\b",
    re.I,
)


def _is_student_status_credential(req: Requirement) -> bool:
    return req.category == SkillCategory.CREDENTIAL and bool(_STUDENT_STATUS.search(req.jd_quote))


def _backstop(req: Requirement) -> Requirement:
    update: dict = {}
    quote = req.jd_quote
    # Universal soft skills are interview material whatever the LLM labeled them, and get one
    # clear name ("ambiguity" -> "Navigating ambiguity").
    if is_soft_skill(req.canonical_skill):
        if req.category not in (SkillCategory.SOFT_SKILL, SkillCategory.TRAIT):
            update["category"] = SkillCategory.SOFT_SKILL
        update["skill"] = display_name(req.canonical_skill)
    # "Inspired by our mission to improve healthcare": enthusiasm for the field, not knowledge of it.
    if req.category == SkillCategory.DOMAIN_KNOWLEDGE and _MISSION.search(quote) and not _EXPERIENCE.search(quote):
        update["category"] = SkillCategory.TRAIT
    # "Curiosity about DeFi/crypto": the interest phrase sits right before the skill.
    at = quote.lower().find(req.skill.lower())
    if at > 0 and _INTEREST.search(quote[max(0, at - 40) : at]) and req.category != SkillCategory.TRAIT:
        update["category"] = SkillCategory.TRAIT
    if req.priority == Priority.REQUIRED and _OPTIONAL.search(quote):
        update["priority"] = Priority.PREFERRED
    return req.model_copy(update=update) if update else req


_PURSUING = re.compile(r"\b(currently\s+)?(pursuing|enrolled|student)\b", re.I)


def _dedupe_eligibility(rules: list[EligibilityRequirement]) -> list[EligibilityRequirement]:
    """One rule per condition.

    - 'Currently pursuing a degree' and 'currently enrolled as a student' are one condition.
    - A rule that is another rule plus more ("…in CS or a related field, with an expected
      graduation date…") is the combined sentence the model already split into parts: drop it.
    """
    norm = {id(r): " ".join(r.description.lower().split()).rstrip(".") for r in rules}
    rules = [
        r
        for r in rules
        if not any(
            other is not r and len(norm[id(other)]) < len(norm[id(r)]) and norm[id(r)].startswith(norm[id(other)])
            for other in rules
        )
    ]
    has_pursuing_degree = any(r.kind == EligibilityKind.DEGREE_LEVEL and _PURSUING.search(r.description) for r in rules)
    out: list[EligibilityRequirement] = []
    seen: set[str] = set()
    for r in rules:
        key = " ".join(r.description.lower().split())
        if key in seen:
            continue
        # Drop an enrollment rule that adds nothing beyond "is a current student" when a
        # degree-level rule already says "currently pursuing". Keep ones with real extra
        # conditions (returning to school after the internship, completed 2 years, ...).
        if has_pursuing_degree and r.kind == EligibilityKind.ENROLLMENT and _only_says_enrolled(r.description):
            continue
        seen.add(key)
        out.append(r)
    return out


def _only_says_enrolled(description: str) -> bool:
    words = set(re.findall(r"[a-z]+", description.lower()))
    filler = {
        "currently", "enrolled", "enrollment", "as", "a", "an", "in", "student", "students", "pursuing",
        "degree", "program", "university", "college", "school", "full", "time", "full-time", "at", "accredited",
    }  # fmt: skip
    return bool(words) and words <= filler


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
