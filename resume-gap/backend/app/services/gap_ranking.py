"""Rank skill gaps across a session's analyses: what to learn first for the jobs you want.

Pure function over AnalysisResults, so it works the same for any repository.

Rules:
- One vote per job: the same (role, company) analyzed again counts only its newest analysis.
- A gap/transferable match scores 2 if required, 1 if preferred; transferable counts half.
- Skills are grouped by canonical_skill, which is why extraction reuses known names.
- Skipped: credentials (a project can't earn a degree), traits (interest/mindset aren't
  learnable gaps), group members another option
  already satisfies, and skills your NEWEST analysis mentioning them shows as covered
  (you've since fixed them).
"""

from collections import Counter

from app.domain.enums import Bucket, Priority, SkillCategory
from app.domain.schemas import AnalysisResult, GapOccurrence, GapRanking, RankedGap

_WEIGHT = {Priority.REQUIRED: 2.0, Priority.PREFERRED: 1.0}
_BUCKET_FACTOR = {Bucket.GAP: 1.0, Bucket.TRANSFERABLE: 0.5}
_SATISFYING = {Bucket.COVERED, Bucket.UNDEREMPHASIZED}


def rank_gaps(results: list[AnalysisResult]) -> GapRanking:
    jobs = _latest_per_job(results)  # newest first

    occurrences: dict[str, list[GapOccurrence]] = {}
    names: dict[str, Counter[str]] = {}
    categories: dict[str, SkillCategory] = {}
    resolved: set[str] = set()  # skills whose newest mention is satisfied
    seen: set[str] = set()

    for result in jobs:
        reqs = {r.id: r for r in result.requirements.requirements}
        for m in result.matches.matches:
            req = reqs[m.requirement_id]
            skill = req.canonical_skill
            if req.category in (SkillCategory.CREDENTIAL, SkillCategory.TRAIT) or m.satisfied_by:
                continue
            first_mention = skill not in seen
            seen.add(skill)
            if m.bucket in _SATISFYING:
                if first_mention:
                    resolved.add(skill)
                continue
            occurrences.setdefault(skill, []).append(
                GapOccurrence(
                    analysis_id=result.id,
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
        )
        for skill, occs in occurrences.items()
        if skill not in resolved
    ]
    gaps.sort(key=lambda g: (-g.score, -g.job_count, g.canonical_skill))
    return GapRanking(analysis_count=len(jobs), gaps=gaps)


def _latest_per_job(results: list[AnalysisResult]) -> list[AnalysisResult]:
    newest_first = sorted(results, key=lambda r: r.created_at, reverse=True)
    latest: dict[tuple[str, str], AnalysisResult] = {}
    for r in newest_first:
        key = (r.requirements.role_title.strip().lower(), (r.requirements.company or "").strip().lower())
        latest.setdefault(key, r)
    return list(latest.values())
