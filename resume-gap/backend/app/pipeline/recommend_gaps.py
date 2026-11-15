"""Stage 5: gap/transferable matches -> one weekend project + resource per skill.

Code decides which requirements get a recommendation; the LLM only writes them:
- Only gap/transferable matches, skipping any requirement another any_of_group
  member already satisfies.
- Credentials are skipped: a weekend project can't earn a degree or certification.
- Exactly one recommendation per target (validated, retried), returned required-first.
"""

from pathlib import Path

from app.domain.enums import Bucket, Priority, SkillCategory
from app.domain.schemas import (
    EvidenceExtraction,
    GapRecommendations,
    RecommendInput,
    Requirement,
    RequirementMatch,
)
from app.llm.base import LLMClient

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "recommend_gaps.md").read_text(encoding="utf-8")

_TARGET_BUCKETS = {Bucket.GAP, Bucket.TRANSFERABLE}


def recommend_gaps(data: RecommendInput, llm: LLMClient) -> GapRecommendations:
    requirements = {r.id: r for r in data.requirements.requirements}
    targets = _targets(data.matches.matches, requirements)
    if not targets:
        return GapRecommendations(recommendations=[])  # nothing missing; skip the LLM call

    prompt = _PROMPT.replace("{{GAPS}}", _format_gaps(targets, requirements)).replace(
        "{{CANDIDATE_SKILLS}}", _candidate_skills(data.evidence)
    )
    result = llm.complete_json(
        prompt,
        GapRecommendations,
        context={"requirement_ids": [m.requirement_id for m in targets]},
    )

    order = {m.requirement_id: i for i, m in enumerate(targets)}
    return GapRecommendations(recommendations=sorted(result.recommendations, key=lambda r: order[r.requirement_id]))


def _targets(matches: list[RequirementMatch], requirements: dict[str, Requirement]) -> list[RequirementMatch]:
    targets = [
        m
        for m in matches
        if m.bucket in _TARGET_BUCKETS
        and not m.satisfied_by
        and requirements[m.requirement_id].category != SkillCategory.CREDENTIAL
    ]
    # Required before preferred; JD order within each (sort is stable).
    return sorted(targets, key=lambda m: requirements[m.requirement_id].priority != Priority.REQUIRED)


def _format_gaps(targets: list[RequirementMatch], requirements: dict[str, Requirement]) -> str:
    lines = []
    for m in targets:
        r = requirements[m.requirement_id]
        note = f" | related: {m.rationale}" if m.bucket == Bucket.TRANSFERABLE else ""
        lines.append(f'{r.id} | {r.skill} | {r.category} | {r.priority} | {m.bucket}{note} | JD: "{r.jd_quote}"')
    return "\n".join(lines)


def _candidate_skills(evidence: EvidenceExtraction) -> str:
    skills = sorted({s.canonical_skill for item in evidence.items for s in item.skills})
    return ", ".join(skills) or "-"
