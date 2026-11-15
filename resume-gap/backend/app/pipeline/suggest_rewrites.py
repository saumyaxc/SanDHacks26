"""Stage 4: underemphasized/transferable matches -> honest rewrites of real resume lines.

Guarantees, enforced here rather than trusted to the LLM:
- Only lines that already back an underemphasized/transferable match are rewritten,
  and only experience/project/other lines (rewording a skills list or coursework adds nothing).
- original_line is copied from the evidence item, never LLM-written.
- A rewrite is dropped if it adds a number, or names a technology from the JD that the
  original line didn't already name — the two most common ways a "rewrite" becomes invention.
- At most one rewrite per line.
- Soft skills and traits never get rewrites: they're cover-letter/interview material.
- A rewrite must contain the keyword of every requirement it claims to surface; a missing
  named technology (TypeScript from a JavaScript line) is never a rewrite target, since
  the keyword can't be added honestly.
- A rewrite that surfaces a transferable concept (e.g. naming OOP for a Python app) states
  something the line only implies, so code marks it needs_confirmation ("only if true").
"""

import logging
import re
from pathlib import Path

from app.domain.enums import INTERVIEW_CATEGORIES, Bucket, ResumeSection, SkillCategory
from app.domain.quotes import normalize_for_quote
from app.domain.schemas import (
    EvidenceItem,
    Requirement,
    RequirementMatch,
    Rewrite,
    RewriteDraft,
    RewriteDrafts,
    RewriteInput,
    RewriteSuggestions,
)
from app.domain.skills import is_named_product, skill_names, text_names_any
from app.llm.base import LLMClient

log = logging.getLogger(__name__)

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "suggest_rewrites.md").read_text(encoding="utf-8")

_TARGET_BUCKETS = {Bucket.UNDEREMPHASIZED, Bucket.TRANSFERABLE}
_REWRITABLE_SECTIONS = {ResumeSection.EXPERIENCE, ResumeSection.PROJECT, ResumeSection.OTHER}
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def suggest_rewrites(data: RewriteInput, llm: LLMClient) -> RewriteSuggestions:
    requirements = {r.id: r for r in data.requirements.requirements}
    evidence = {e.id: e for e in data.evidence.items}

    targets = _targets(data.matches.matches, evidence, requirements)
    if not targets:
        return RewriteSuggestions(rewrites=[])  # nothing to surface; skip the LLM call

    prompt = _PROMPT.replace("{{TARGETS}}", _format_targets(targets, evidence, requirements))
    drafts = llm.complete_json(
        prompt,
        RewriteDrafts,
        context={
            "evidence_ids": set(targets),
            "requirement_ids": {m.requirement_id for ms in targets.values() for m in ms},
        },
    )

    # Only specific named products can be checked for "added by the rewrite" by name.
    technologies = [
        r for r in requirements.values() if r.category == SkillCategory.TECHNOLOGY and is_named_product(r.canonical_skill)
    ]
    bucket_of = {m.requirement_id: m.bucket for ms in targets.values() for m in ms}
    rewrites: list[Rewrite] = []
    seen: set[str] = set()
    for draft in drafts.rewrites:
        ev = evidence[draft.evidence_id]
        if draft.evidence_id in seen:
            continue
        problem = _honesty_problem(draft, ev, technologies) or _missing_keyword(draft, requirements)
        if problem:
            log.warning("dropping rewrite for %s: %s\n    %r", ev.id, problem, draft.suggested_line)
            continue
        seen.add(ev.id)
        rewrites.append(
            Rewrite(
                evidence_id=ev.id,
                original_line=ev.line,
                suggested_line=draft.suggested_line,
                requirement_ids=list(dict.fromkeys(draft.requirement_ids)),
                reason=draft.reason,
                needs_confirmation=any(
                    bucket_of.get(rid) == Bucket.TRANSFERABLE and not _is_specific_tech(requirements[rid])
                    for rid in draft.requirement_ids
                ),
            )
        )
    return RewriteSuggestions(rewrites=rewrites)


def _targets(
    matches: list[RequirementMatch], evidence: dict[str, EvidenceItem], requirements: dict[str, Requirement]
) -> dict[str, list[RequirementMatch]]:
    """evidence_id -> the matches that line could surface better, in resume order."""
    by_line: dict[str, list[RequirementMatch]] = {}
    for m in matches:
        if m.bucket not in _TARGET_BUCKETS or m.satisfied_by or m.evidence_id is None:
            continue
        req = requirements[m.requirement_id]
        if req.category in INTERVIEW_CATEGORIES:
            continue  # soft skills/traits are shown in interviews, not reworded into bullets
        if m.bucket == Bucket.TRANSFERABLE and _is_specific_tech(req):
            continue  # can't honestly add "TypeScript" to a JavaScript line: that's a project, not a rewrite
        if evidence[m.evidence_id].section in _REWRITABLE_SECTIONS:
            by_line.setdefault(m.evidence_id, []).append(m)
    return {eid: by_line[eid] for eid in evidence if eid in by_line}


def _is_specific_tech(req: Requirement) -> bool:
    return req.category == SkillCategory.TECHNOLOGY and is_named_product(req.canonical_skill)


def _missing_keyword(draft: RewriteDraft, requirements: dict[str, Requirement]) -> str | None:
    """A rewrite exists to surface a keyword, so it must contain it (as the JD writes it, or an alias)."""
    for rid in draft.requirement_ids:
        req = requirements[rid]
        names = skill_names(req.skill, req.canonical_skill)
        if not text_names_any(draft.suggested_line, names):
            return f"doesn't include the keyword {req.skill!r}"
    return None


def _honesty_problem(draft: RewriteDraft, ev: EvidenceItem, technologies: list[Requirement]) -> str | None:
    if normalize_for_quote(draft.suggested_line) == normalize_for_quote(ev.line):
        return "identical to original"
    added_numbers = set(_NUMBER.findall(draft.suggested_line)) - set(_NUMBER.findall(ev.line))
    if added_numbers:
        return f"adds numbers {sorted(added_numbers)}"
    for req in technologies:
        names = skill_names(req.skill, req.canonical_skill)
        if text_names_any(draft.suggested_line, names) and not text_names_any(ev.line, names):
            return f"adds {req.skill}, which the original line doesn't name"
    return None


def _format_targets(
    targets: dict[str, list[RequirementMatch]],
    evidence: dict[str, EvidenceItem],
    requirements: dict[str, Requirement],
) -> str:
    blocks = []
    for eid, matches in targets.items():
        ev = evidence[eid]
        lines = [f"{ev.id} | {ev.section} | {ev.line}"]
        for m in matches:
            r = requirements[m.requirement_id]
            lines.append(f"  - {r.id} | {r.skill} | {r.category} | {m.bucket}: {m.rationale}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
