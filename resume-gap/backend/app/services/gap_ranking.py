"""Rank skill gaps across a session's analyses: what to learn first for the jobs you want.

Pure function over AnalysisResults, so it works the same for any repository.

Rules:
- One vote per job: the same posting (AnalysisResult.job_key) analyzed again, e.g. with a
  different resume, counts only its newest analysis.
- A gap/transferable match scores 2 if required, 1 if preferred; transferable counts half.
- Skills are grouped by canonical_skill, which is why extraction reuses known names.
- Skills the user dismissed are hidden (and listed in `dismissed` so they can be restored).
- Each gap carries the newest project recommendation made for it, if any.
- Skipped: credentials (a project can't earn a degree), soft skills and traits (interview
  material, not learnable gaps), group members another option
  already satisfies, and skills your NEWEST analysis mentioning them shows as covered
  (you've since fixed them).
"""

from collections import Counter

from app.domain.enums import INTERVIEW_CATEGORIES, Bucket, Priority, SkillCategory
from app.domain.schemas import AnalysisResult, GapOccurrence, GapRanking, GapRecommendation, RankedGap

_WEIGHT = {Priority.REQUIRED: 2.0, Priority.PREFERRED: 1.0}
_BUCKET_FACTOR = {Bucket.GAP: 1.0, Bucket.TRANSFERABLE: 0.5}
_SATISFYING = {Bucket.COVERED, Bucket.UNDEREMPHASIZED}


def rank_gaps(results: list[AnalysisResult], dismissed: list[str] | None = None) -> GapRanking:
    jobs = _latest_per_job(results)  # newest first
    hidden = set(dismissed or [])
    recommendation: dict[str, GapRecommendation] = {}

    occurrences: dict[str, list[GapOccurrence]] = {}
    names: dict[str, Counter[str]] = {}
    categories: dict[str, SkillCategory] = {}
    resolved: set[str] = set()  # skills whose newest mention is satisfied
    seen: set[str] = set()

    for result in jobs:
        reqs = {r.id: r for r in result.requirements.requirements}
        recs = {r.requirement_id: r for r in result.recommendations.recommendations}
        for m in result.matches.matches:
            req = reqs[m.requirement_id]
            skill = req.canonical_skill
            if req.category == SkillCategory.CREDENTIAL or req.category in INTERVIEW_CATEGORIES or m.satisfied_by:
                continue
            first_mention = skill not in seen
            seen.add(skill)
            if m.bucket in _SATISFYING:
                if first_mention:
                    resolved.add(skill)
                continue
            if m.requirement_id in recs:
                recommendation.setdefault(skill, recs[m.requirement_id])  # newest wins (newest-first loop)
            occurrences.setdefault(skill, []).append(
                GapOccurrence(
                    analysis_id=result.id,
                    requirement_id=m.requirement_id,
                    role_title=result.requirements.role_title,
                    company=result.requirements.company,
                    bucket=m.bucket,
                    priority=req.priority,
                )
            )
            names.setdefault(skill, Counter())[req.skill] += 1
            categories.setdefault(skill, req.category)

    gaps = [
        RankedGap(
            canonical_skill=skill,
            skill=names[skill].most_common(1)[0][0],
            category=categories[skill],
            score=sum(_WEIGHT[o.priority] * _BUCKET_FACTOR[o.bucket] for o in occs),
            job_count=len(occs),
            required_count=sum(o.priority == Priority.REQUIRED for o in occs),
            occurrences=occs,
            recommendation=recommendation.get(skill),
        )
        for skill, occs in occurrences.items()
        if skill not in resolved and skill not in hidden
    ]
    gaps.sort(key=lambda g: (-g.score, -g.job_count, g.canonical_skill))
    return GapRanking(analysis_count=len(jobs), gaps=gaps, dismissed=sorted(hidden))


def _latest_per_job(results: list[AnalysisResult]) -> list[AnalysisResult]:
    newest_first = sorted(results, key=lambda r: r.created_at, reverse=True)
    latest: dict[str, AnalysisResult] = {}
    for r in newest_first:
        latest.setdefault(r.job_key, r)  # same rule the history list groups by
    return list(latest.values())
