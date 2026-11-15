"""Stage 3: requirements x evidence -> one bucketed match per requirement.

Guarantees, enforced here rather than trusted to the LLM:
- Every non-gap match quotes a real resume line: the LLM picks an evidence_id,
  and the quote is copied from that evidence item (which stage 2 verified).
- A named tool/technical skill is only covered/underemphasized if the evidence
  line actually names it (text, tags, or a known alias); otherwise it's transferable.
- "Covered" means demonstrated: a skills-list line, or a coursework line for a
  non-credential, is downgraded to underemphasized.
- A requirement satisfied by another member of its any_of_group is marked satisfied_by.
"""

import re
from pathlib import Path

from app.domain.enums import Bucket, ResumeSection, SkillCategory
from app.domain.quotes import normalize_for_quote
from app.domain.skills import ALIASES, normalize_skill
from app.domain.schemas import (
    EvidenceItem,
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

# Categories where "has the skill" must be backed by the line naming it.
# Soft skills, domain knowledge, and credentials are judged by the LLM alone.
_NAME_CHECKED = {SkillCategory.TOOL, SkillCategory.TECHNICAL_SKILL}


def match(data: MatchInput, llm: LLMClient) -> MatchResult:
    requirements = data.requirements.requirements
    evidence = {e.id: e for e in data.evidence.items}

    prompt = _PROMPT.replace("{{REQUIREMENTS}}", _format_requirements(requirements)).replace(
        "{{EVIDENCE}}", _format_evidence(data.evidence.items)
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

        if ev is not None and bucket in _SATISFYING and req.category in _NAME_CHECKED and not _names_skill(req, ev):
            bucket = Bucket.TRANSFERABLE
            rationale = f"{rationale} (Line doesn't name {req.canonical_skill}; counted as related experience.)"

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


def _names_skill(req: Requirement, ev: EvidenceItem) -> bool:
    """True if the evidence line names the requirement's skill by tag, text, or alias."""
    if req.canonical_skill in {s.canonical_skill for s in ev.skills}:
        return True
    text = normalize_for_quote(ev.line)
    names = {req.canonical_skill, normalize_skill(req.skill), req.skill.lower()}
    names |= {alias for alias, canonical in ALIASES.items() if canonical == req.canonical_skill}
    return any(_contains_term(text, normalize_for_quote(n)) for n in names)


def _contains_term(text: str, term: str) -> bool:
    # Whole-term match: "go" must not match "going"; works for "c++", "node.js", "ci/cd".
    return bool(term) and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


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
