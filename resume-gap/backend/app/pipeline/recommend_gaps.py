"""Stage 5: gap/transferable matches -> 1-3 weekend projects + one checked resource per skill.

Code decides which requirements get a recommendation; the LLM only writes them:
- Only gap/transferable matches, skipping any requirement another any_of_group
  member already satisfies.
- Credentials are skipped: a weekend project can't earn a degree or certification.
- Exactly one recommendation per target (validated, retried), returned required-first.
- Every resource link works: the LLM's URL is shown only if `url_is_live` confirms it;
  otherwise the link is a web search for the resource title, flagged as unverified.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote_plus

from app.domain.enums import Bucket, Priority, SkillCategory
from app.domain.schemas import (
    EvidenceExtraction,
    GapRecommendation,
    GapRecommendationDraft,
    GapRecommendationDrafts,
    GapRecommendations,
    RecommendInput,
    Requirement,
    RequirementMatch,
)
from app.llm.base import LLMClient

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "recommend_gaps.md").read_text(encoding="utf-8")

_TARGET_BUCKETS = {Bucket.GAP, Bucket.TRANSFERABLE}
_MAX_LINK_CHECKS_IN_PARALLEL = 8

UrlChecker = Callable[[str], bool]


def recommend_gaps(data: RecommendInput, llm: LLMClient, url_is_live: UrlChecker) -> GapRecommendations:
    requirements = {r.id: r for r in data.requirements.requirements}
    targets = _targets(data.matches.matches, requirements)
    if not targets:
        return GapRecommendations(recommendations=[])  # nothing missing; skip the LLM call

    prompt = _PROMPT.replace("{{GAPS}}", _format_gaps(targets, requirements)).replace(
        "{{CANDIDATE_SKILLS}}", _candidate_skills(data.evidence)
    )
    drafts = llm.complete_json(
        prompt,
        GapRecommendationDrafts,
        context={"requirement_ids": [m.requirement_id for m in targets]},
    ).recommendations

    urls = [d.resource_url for d in drafts if d.resource_url]
    with ThreadPoolExecutor(max_workers=_MAX_LINK_CHECKS_IN_PARALLEL) as pool:
        live = dict(zip(urls, pool.map(url_is_live, urls)))

    order = {m.requirement_id: i for i, m in enumerate(targets)}
    finished = [_finish(d, live) for d in drafts]
    return GapRecommendations(recommendations=sorted(finished, key=lambda r: order[r.requirement_id]))


def _finish(draft: GapRecommendationDraft, live: dict[str, bool]) -> GapRecommendation:
    verified = bool(draft.resource_url and live.get(draft.resource_url))
    return GapRecommendation(
        requirement_id=draft.requirement_id,
        projects=draft.projects,
        resource_type=draft.resource_type,
        resource_title=draft.resource_title,
        resource_url=draft.resource_url if verified else search_url(draft.resource_title),
        resource_url_verified=verified,
    )


def search_url(query: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(query)}"


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
