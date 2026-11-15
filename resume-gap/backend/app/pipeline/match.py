"""Stage 3: requirements x evidence -> one bucketed match per requirement.

Guarantees, enforced here rather than trusted to the LLM:
- Every non-gap match quotes a real resume line: the LLM picks an evidence_id,
  and the quote is copied from that evidence item (which stage 2 verified).
- For a specific named technology (python, react — see skills.is_named_product), code
  decides whether the resume has it: if any line names it (tag, text, or alias), the
  best such line is used; if none does, the LLM may only choose transferable or gap.
  Generic "technologies" ("search systems", "AI coding tools") can't be name-matched,
  so they're judged like concepts, by the LLM.
- "Covered" means demonstrated: a skills-list line, or a coursework line for a named
  technology, is downgraded to underemphasized. A concept backed by coursework
  (algorithms, CS fundamentals) counts as covered: that's how fundamentals are shown.
- Once any member of an any_of_group is covered/underemphasized, every OTHER member is
  marked satisfied_by: the job needs only one, so the rest are optional.
- Eligibility checks quote real lines too, and work authorization is always "unknown":
  it must never be guessed from a resume. Education dates are parsed in code
  (domain/education.py) and handed to the LLM as a timeline, not left to its arithmetic.
"""

from datetime import date
from pathlib import Path

from app.domain.education import (
    Program,
    education_timeline,
    format_timeline,
    judge_dates_for_level,
    judge_degree_rule,
    student_levels,
)
from app.domain.enums import (
    INTERVIEW_CATEGORIES,
    Bucket,
    EligibilityKind,
    EligibilityStatus,
    ResumeSection,
    SkillCategory,
)
from app.domain.skills import is_named_product, skill_names, text_names_any
from app.domain.schemas import (
    EligibilityCheck,
    EligibilityRequirement,
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


def match(data: MatchInput, llm: LLMClient, today: date | None = None) -> MatchResult:
    requirements = data.requirements.requirements
    rules = data.requirements.eligibility
    items = data.evidence.items
    evidence = {e.id: e for e in items}

    today = today or date.today()
    programs = education_timeline(items, today)
    prompt = (
        _PROMPT.replace("{{TODAY}}", today.isoformat())
        .replace("{{EDUCATION_TIMELINE}}", format_timeline(programs))
        .replace("{{REQUIREMENTS}}", _format_requirements(requirements))
        .replace("{{ELIGIBILITY}}", _format_eligibility(rules))
        .replace("{{EVIDENCE}}", _format_evidence(items))
    )
    decisions = llm.complete_json(
        prompt,
        MatchDecisions,
        context={
            "requirement_ids": [r.id for r in requirements],
            "eligibility_ids": [e.id for e in rules],
            "evidence_ids": set(evidence),
        },
    )

    by_req = {d.requirement_id: d for d in decisions.decisions}
    matches = []
    for req in requirements:
        decision = by_req[req.id]
        ev = evidence.get(decision.evidence_id) if decision.bucket != Bucket.GAP else None
        bucket, rationale = decision.bucket, decision.rationale

        if req.category == SkillCategory.TECHNOLOGY and is_named_product(req.canonical_skill):
            bucket, ev, rationale = _check_technology(req, decision, ev, items)
        elif _is_concept_coursework(req, ev) and bucket == Bucket.UNDEREMPHASIZED:
            bucket = Bucket.COVERED  # coursework is how fundamentals are normally shown

        bucket = _enforce_strength(bucket, req, ev)
        if req.category in INTERVIEW_CATEGORIES and ev is not None:
            bucket = Bucket.COVERED  # interview material isn't graded: a line is either an example or not

        matches.append(
            RequirementMatch(
                requirement_id=req.id,
                bucket=bucket,
                evidence_id=ev.id if ev else None,
                evidence_quote=ev.line if ev else None,
                rationale=rationale,
            )
        )
    return MatchResult(
        matches=_apply_groups(matches, requirements),
        eligibility=_eligibility_checks(rules, decisions, evidence, programs),
    )


def _eligibility_checks(
    rules: list[EligibilityRequirement],
    decisions: MatchDecisions,
    evidence: dict[str, EvidenceItem],
    programs: list[Program],
) -> list[EligibilityCheck]:
    by_id = {d.eligibility_id: d for d in decisions.eligibility}
    # Which students the job is for ("sophomore and junior undergraduates" -> bachelor's).
    # Date rules then refer to THAT degree: an MS ending in 2028 doesn't meet "graduating in
    # 2028" for a job that wants undergraduates.
    wanted_levels: set[str] = set()
    for rule in rules:
        wanted_levels |= student_levels(f"{rule.description} {rule.jd_quote}")
    checks = []
    for rule in rules:
        d = by_id[rule.id]
        ev = evidence.get(d.evidence_id) if d.evidence_id else None
        status, rationale = d.status, d.rationale
        if rule.kind != EligibilityKind.WORK_AUTHORIZATION:
            # Degree level vs. current program is decided in code when the wording names one
            # ("rising senior pursuing a BS" is not met by an MS student). It applies to every
            # kind: "Rising junior or senior graduating in 2027" is a graduation rule, but an MS
            # student fails it whatever the dates say.
            judged = judge_degree_rule(f"{rule.description} {rule.jd_quote}", programs)
            is_level_rule = rule.kind in (EligibilityKind.DEGREE_LEVEL, EligibilityKind.ENROLLMENT)
            if judged is not None and (is_level_rule or judged[0] == "not_met"):
                status = EligibilityStatus(judged[0])
                rationale = judged[1]
                ev = evidence.get(judged[2])
            elif rule.kind == EligibilityKind.GRADUATION_WINDOW and status == EligibilityStatus.MET:
                wrong_degree = judge_dates_for_level(wanted_levels, programs)
                if wrong_degree is not None:
                    status = EligibilityStatus.NOT_MET
                    rationale, ev_id = wrong_degree
                    ev = evidence.get(ev_id) if ev_id else None
        if rule.kind == EligibilityKind.WORK_AUTHORIZATION:
            status = EligibilityStatus.UNKNOWN
            rationale = "Resumes don't show work authorization. Check this yourself before applying."
            ev = None
        checks.append(
            EligibilityCheck(
                eligibility_id=rule.id,
                status=status,
                evidence_id=ev.id if ev else None,
                evidence_quote=ev.line if ev else None,
                rationale=rationale,
            )
        )
    return checks


def _check_technology(
    req: Requirement, decision: MatchDecision, ev: EvidenceItem | None, items: list[EvidenceItem]
) -> tuple[Bucket, EvidenceItem | None, str]:
    """Whether the resume has a named technology is a string fact, so code decides it."""
    named = sorted((e for e in items if _names_skill(req, e)), key=lambda e: _SECTION_RANK[e.section])

    if not named:
        if decision.bucket in _SATISFYING:
            # The LLM claimed coverage that no line supports. Its sentence argued for that claim,
            # so it can't be kept; code writes the rationale instead.
            return (
                Bucket.TRANSFERABLE,
                ev,
                f"Your resume doesn't name {req.skill}; this line is the closest related experience.",
            )
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


def _format_eligibility(rules: list[EligibilityRequirement]) -> str:
    return "\n".join(f'{e.id} | {e.kind} | {e.description} | JD: "{e.jd_quote}"' for e in rules) or "(none)"


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
        if _is_concept_coursework(req, ev):
            return bucket  # concepts like algorithms are normally shown through coursework
        return Bucket.UNDEREMPHASIZED  # a technology in a course list isn't demonstrated use
    return bucket


def _is_concept_coursework(req: Requirement, ev: EvidenceItem | None) -> bool:
    """A concept backed by an education line: coursework is the normal evidence for fundamentals.

    The line need not repeat the JD's wording: "computer science fundamentals" is shown by a
    list of CS courses that never says "fundamentals". Specific named technologies are
    excluded: "Java" in a course list is still only underemphasized.
    """
    if ev is None or ev.section != ResumeSection.EDUCATION:
        return False
    return req.category == SkillCategory.CONCEPT or (
        req.category == SkillCategory.TECHNOLOGY and not is_named_product(req.canonical_skill)
    )


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
        if winner and m.requirement_id != winner.requirement_id:
            m = m.model_copy(update={"satisfied_by": winner.requirement_id})
        out.append(m)
    return out
