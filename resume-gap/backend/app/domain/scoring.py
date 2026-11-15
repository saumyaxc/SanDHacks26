"""Overall match % for one analysis. Pure arithmetic over buckets; no LLM involved.

- Each requirement earns credit by bucket (below) and is weighted 2 if required, 1 if preferred.
- An any_of_group counts once, at its best member's credit (knowing 1 of 3 listed languages
  is a full match, not 33%).
- percent = weighted credit / total weight.
- Soft skills and traits are excluded (see INTERVIEW_CATEGORIES): they're judged in interviews,
  so they don't count for or against you here. Credentials (degrees, certifications) are
  excluded too: they're qualifications, shown alongside the eligibility checks.
- Failing an eligibility rule overrides the verdict: skills don't matter if you can't apply.

Verdict thresholds are deliberately simple and shown with the number, not instead of it.
"""

from typing import Literal

from pydantic import BaseModel

from .enums import Bucket, Priority

CREDIT = {
    Bucket.COVERED: 1.0,
    Bucket.UNDEREMPHASIZED: 0.8,  # you have it; the resume just undersells it
    Bucket.TRANSFERABLE: 0.4,
    Bucket.GAP: 0.0,
}
_WEIGHT = {Priority.REQUIRED: 2.0, Priority.PREFERRED: 1.0}
_HAS_IT = 0.8  # credit at or above this counts as "you have this requirement"

Verdict = Literal["strong", "tailor", "stretch", "not_eligible"]


class MatchScore(BaseModel):  # plain BaseModel: schemas.py imports this module
    percent: int  # 0-100
    required_met: int  # required requirements (groups count once) you have
    required_total: int
    skills_counted: int = 0  # requirements in the four buckets, each "any one of these" list once
    verdict: Verdict  # not_eligible if any rule is failed; else strong >= 75, tailor >= 50, else stretch


def match_score(units: list[tuple[Priority, list[Bucket]]], ineligible: bool = False) -> MatchScore:
    """units: one entry per requirement or any_of_group: (priority, member buckets), traits excluded."""
    total = earned = 0.0
    required_met = required_total = 0
    for priority, buckets in units:
        credit = max(CREDIT[b] for b in buckets)
        weight = _WEIGHT[priority]
        total += weight
        earned += weight * credit
        if priority == Priority.REQUIRED:
            required_total += 1
            required_met += credit >= _HAS_IT
    percent = round(100 * earned / total) if total else 0
    verdict: Verdict = (
        "not_eligible" if ineligible else "strong" if percent >= 75 else "tailor" if percent >= 50 else "stretch"
    )
    return MatchScore(
        percent=percent,
        required_met=required_met,
        required_total=required_total,
        skills_counted=len(units),
        verdict=verdict,
    )
