"""Stage 3: requirements x evidence -> one bucketed match per requirement.

Guarantees, enforced here rather than trusted to the LLM:
- Every non-gap match quotes a real resume line: the LLM picks an evidence_id,
  and the quote is copied from that evidence item (which stage 2 verified).
- For a `technology` requirement, code decides whether the resume has it: if any
  line names it (tag, text, or known alias), the best such line is used; if none
  does, the LLM may only choose transferable or gap. Concepts, soft skills,
  domain knowledge, and credentials are judged by the LLM.
- "Covered" means demonstrated: a skills-list line, or a coursework line for a
  non-credential, is downgraded to underemphasized.
- A requirement satisfied by another member of its any_of_group is marked satisfied_by.
"""

from pathlib import Path

from app.domain.enums import Bucket, ResumeSection, SkillCategory
from app.domain.skills import skill_names, text_names_any
from app.domain.schemas import (
    EvidenceItem,
    MatchDecision,
    MatchDecisions,
    MatchInput,
    MatchResult,
    Requirement,
    RequirementMatch,
)
from app.llm.base import LLMClient

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "match.md").read_text(encoding="utf-8")

# Best first: which buckets mean "the resume has this skill".
_SATISFYING = (Bucket.COVERED, Bucket.UNDEREMPHASIZED)

# Lower is stronger evidence: doing it beats a summary beats listing it.
_SECTION_RANK = {
    ResumeSection.EXPERIENCE: 0,
    ResumeSection.PROJECT: 0,
    ResumeSection.OTHER: 1,
    ResumeSection.EDUCATION: 2,
    ResumeSection.SKILLS: 2,
}


def match(data: MatchInput, llm: LLMClient) -> MatchResult:
    requirements = data.requirements.requirements
    items = data.evidence.items
    evidence = {e.id: e for e in items}

    prompt = _PROMPT.replace("{{REQUIREMENTS}}", _format_requirements(requirements)).replace(
        "{{EVIDENCE}}", _format_evidence(items)
    )
    decisions = llm.complete_json(
        prompt,
        MatchDecisions,
        context={"requirement_ids": [r.id for r in requirements], "evidence_ids": set(evidence)},
    )

    by_req = {d.requirement_id: d for d in decisions.decisions}
    matches = []
    for req in requirements:
        decision = by_req[req.id]
        ev = evidence.get(decision.evidence_id) if decision.bucket != Bucket.GAP else None
        bucket, rationale = decision.bucket, decision.rationale

        if req.category == SkillCategory.TECHNOLOGY:
            bucket, ev, rationale = _check_technology(req, decision, ev, items)

        matches.append(
            RequirementMatch(
                requirement_id=req.id,
                bucket=_enforce_strength(bucket, req, ev),
                evidence_id=ev.id if ev else None,
                evidence_quote=ev.line if ev else None,
                rationale=rationale,
            )
        )
    return MatchResult(matches=_apply_groups(matches, requirements))


def _check_technology(
    req: Requirement, decision: MatchDecision, ev: EvidenceItem | None, items: list[EvidenceItem]
) -> tuple[Bucket, EvidenceItem | None, str]:
    """Whether the resume has a named technology is a string fact, so code decides it."""
    named = sorted((e for e in items if _names_skill(req, e)), key=lambda e: _SECTION_RANK[e.section])

    if not named:
        if decision.bucket in _SATISFYING:
            note = f"(No line names {req.skill}; counted as related experience.)"
            return Bucket.TRANSFERABLE, ev, f"{decision.rationale} {note}"
        return decision.bucket, ev, decision.rationale

    best = named[0]
    # Keep the LLM's call when it already picked a naming line at least as strong as the best one.
    if decision.bucket in _SATISFYING and ev in named and _SECTION_RANK[ev.section] <= _SECTION_RANK[best.section]:
        return decision.bucket, ev, decision.rationale
    return Bucket.COVERED, best, _named_rationale(req, best)


def _named_rationale(req: Requirement, ev: EvidenceItem) -> str:
    if ev.section == ResumeSection.SKILLS:
        return f"{req.skill} is listed in your skills but not shown in use."
    if ev.section == ResumeSection.EDUCATION:
        return f"{req.skill} appears only in your education/coursework."
    return f"This {ev.section} line names {req.skill} directly."


def _names_skill(req: Requirement, ev: EvidenceItem) -> bool:
    """True if the evidence line names the requirement's skill by tag, text, or alias."""
    if req.canonical_skill in {s.canonical_skill for s in ev.skills}:
        return True
    return text_names_any(ev.line, skill_names(req.skill, req.canonical_skill))


def _format_requirements(requirements: list[Requirement]) -> str:
    lines = []
    for r in requirements:
        group = f" | any_of_group: {r.any_of_group}" if r.any_of_group else ""
        lines.append(f'{r.id} | {r.skill} ({r.canonical_skill}) | {r.category}{group} | JD: "{r.jd_quote}"')
    return "\n".join(lines)


def _format_evidence(items: list[EvidenceItem]) -> str:
    lines = []
    for e in items:
        tags = ", ".join(s.canonical_skill for s in e.skills) or "-"
        lines.append(f"{e.id} | {e.section} | {e.line} | tags: {tags}")
    return "\n".join(lines)


def _enforce_strength(bucket: Bucket, req: Requirement, ev: EvidenceItem | None) -> Bucket:
    if bucket != Bucket.COVERED or ev is None:
        return bucket
    if ev.section == ResumeSection.SKILLS:
        return Bucket.UNDEREMPHASIZED
    if ev.section == ResumeSection.EDUCATION and req.category != SkillCategory.CREDENTIAL:
        return Bucket.UNDEREMPHASIZED  # coursework lists aren't demonstrated use
    return bucket


def _apply_groups(matches: list[RequirementMatch], requirements: list[Requirement]) -> list[RequirementMatch]:
    group_of = {r.id: r.any_of_group for r in requirements if r.any_of_group}

    # For each group, the best satisfying member (covered beats underemphasized, then JD order).
    best: dict[str, RequirementMatch] = {}
    for bucket in _SATISFYING:
        for m in matches:
            group = group_of.get(m.requirement_id)
            if group and group not in best and m.bucket == bucket:
                best[group] = m

    out = []
    for m in matches:
        group = group_of.get(m.requirement_id)
        winner = best.get(group) if group else None
        if winner and m.bucket not in _SATISFYING:
            m = m.model_copy(update={"satisfied_by": winner.requirement_id})
        out.append(m)
    return out
