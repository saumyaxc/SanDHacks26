"""The contract. Every pipeline stage takes one of these in and returns one out.

Models marked [LLM OUTPUT] are sent to Gemini as response schemas, so keep
them to plain types (str/int/list/enum/nested model). Put rules in validators,
not Field(...) constraints — validators never reach the LLM, and a failure
triggers the client's retry.
"""

import hashlib
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, computed_field, model_validator

from .enums import (
    INTERVIEW_CATEGORIES,
    Bucket,
    EligibilityKind,
    EligibilityStatus,
    Priority,
    ResourceType,
    ResumeSection,
    SkillCategory,
)
from .scoring import MatchScore, match_score
from .skills import normalize_skill

MAX_INPUT_CHARS = 20_000


class _Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


def _check_unique_ids(ids: list[str], what: str) -> None:
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate {what} ids: {sorted(dupes)}")


# ---------- Stage 1: extract requirements ----------


class ExtractRequirementsInput(_Base):
    jd_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    # Canonical skills seen in earlier analyses; shown to the LLM so it reuses them.
    known_skills: list[str] = Field(default_factory=list)


class Requirement(_Base):
    id: str  # e.g. "req-1"
    skill: str  # short skill name as written in the JD, e.g. "K8s"
    canonical_skill: str  # LLM-proposed standard name; always re-normalized below
    category: SkillCategory
    priority: Priority
    years_required: int | None = None
    # Shared label for "one of X, Y, Z" options; any one member satisfies the group.
    any_of_group: str | None = None
    jd_quote: str  # the JD line this came from

    @model_validator(mode="after")
    def _normalize_canonical(self) -> "Requirement":
        self.canonical_skill = normalize_skill(self.canonical_skill or self.skill)
        return self


class EligibilityRequirement(_Base):
    """A hard condition on the candidate (degree level, enrollment, graduation dates, work
    authorization). Not a skill: it's checked, never scored, ranked, or turned into a project."""

    id: str
    kind: EligibilityKind
    description: str  # short and specific: "Pursuing a Bachelor's degree", "Graduating Dec 2026 - Jun 2027"
    jd_quote: str


class RequirementsExtraction(_Base):
    """[LLM OUTPUT]"""

    role_title: str
    company: str | None = None
    requirements: list[Requirement]
    eligibility: list[EligibilityRequirement] = []
    # The model's honest way out: text that isn't a job posting gets False, not invented requirements.
    is_job_description: bool = True

    @model_validator(mode="after")
    def _validate(self) -> "RequirementsExtraction":
        if self.is_job_description and not self.requirements:
            raise ValueError("no requirements extracted; if this isn't a job posting, set is_job_description to false")
        _check_unique_ids([r.id for r in self.requirements], "requirement")
        _check_unique_ids([e.id for e in self.eligibility], "eligibility")
        return self


# ---------- Stage 2: extract evidence ----------


class ExtractEvidenceInput(_Base):
    resume_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    # Canonical skills seen in earlier analyses; shown to the LLM so it reuses them.
    known_skills: list[str] = Field(default_factory=list)


class SkillMention(_Base):
    skill: str  # as written in the resume
    canonical_skill: str  # LLM-proposed standard name; always re-normalized below

    @model_validator(mode="after")
    def _normalize_canonical(self) -> "SkillMention":
        self.canonical_skill = normalize_skill(self.canonical_skill or self.skill)
        return self


class EvidenceItem(_Base):
    id: str  # e.g. "ev-1"
    section: ResumeSection
    line: str  # exact resume line, verbatim (checked in pipeline/extract_evidence.py)
    skills: list[SkillMention]  # skills this line explicitly names


class EvidenceExtraction(_Base):
    """[LLM OUTPUT]"""

    items: list[EvidenceItem]

    @model_validator(mode="after")
    def _validate(self) -> "EvidenceExtraction":
        if not self.items:
            raise ValueError("no evidence extracted")
        _check_unique_ids([i.id for i in self.items], "evidence")
        return self


# ---------- Stage 3: match ----------


class MatchInput(_Base):
    requirements: RequirementsExtraction
    evidence: EvidenceExtraction


class MatchDecision(_Base):
    requirement_id: str
    bucket: Bucket
    evidence_id: str | None = None  # strongest supporting line; null for gap
    rationale: str

    @model_validator(mode="after")
    def _validate(self) -> "MatchDecision":
        if self.bucket == Bucket.GAP:
            self.evidence_id = None  # a gap has no evidence by definition
        elif not self.evidence_id:
            raise ValueError(f"{self.requirement_id}: bucket '{self.bucket}' requires evidence_id")
        return self


class EligibilityDecision(_Base):
    eligibility_id: str
    status: EligibilityStatus
    evidence_id: str | None = None  # the education line it was judged from, if any
    rationale: str


class MatchDecisions(_Base):
    """[LLM OUTPUT] The LLM picks evidence by id only; code copies the quote.

    Validation context (passed by pipeline/match.py):
      requirement_ids: every requirement must get exactly one decision
      eligibility_ids: every eligibility rule must get exactly one decision
      evidence_ids: every evidence_id must exist
    """

    decisions: list[MatchDecision]
    eligibility: list[EligibilityDecision] = []

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> "MatchDecisions":
        ctx = info.context or {}
        got = [d.requirement_id for d in self.decisions]
        _check_unique_ids(got, "requirement")

        if (expected := ctx.get("requirement_ids")) is not None:
            missing = sorted(set(expected) - set(got))
            unknown = sorted(set(got) - set(expected))
            if missing or unknown:
                raise ValueError(f"decisions must cover each requirement once; missing={missing} unknown={unknown}")

        if (expected := ctx.get("eligibility_ids")) is not None:
            got_elig = [e.eligibility_id for e in self.eligibility]
            _check_unique_ids(got_elig, "eligibility")
            missing = sorted(set(expected) - set(got_elig))
            unknown = sorted(set(got_elig) - set(expected))
            if missing or unknown:
                raise ValueError(f"eligibility must cover each rule once; missing={missing} unknown={unknown}")

        if (evidence_ids := ctx.get("evidence_ids")) is not None:
            used = {d.evidence_id for d in self.decisions} | {e.evidence_id for e in self.eligibility}
            bad = sorted(i for i in used if i and i not in evidence_ids)
            if bad:
                raise ValueError(f"unknown evidence ids: {bad}")
        return self


class RequirementMatch(_Base):
    requirement_id: str
    bucket: Bucket
    evidence_id: str | None = None
    evidence_quote: str | None = None  # copied by code from the evidence line; never LLM-written
    rationale: str
    # Set on every other member once one member of the any_of_group is covered/underemphasized:
    # the job only needs one, so the rest are optional.
    satisfied_by: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "RequirementMatch":
        if self.bucket == Bucket.GAP:
            self.evidence_id = None
            self.evidence_quote = None
        elif not self.evidence_id or not self.evidence_quote:
            raise ValueError(
                f"{self.requirement_id}: bucket '{self.bucket}' requires evidence_id and evidence_quote"
            )
        return self


class EligibilityCheck(_Base):
    eligibility_id: str
    status: EligibilityStatus
    evidence_id: str | None = None
    evidence_quote: str | None = None  # copied by code from the evidence line
    rationale: str


class MatchResult(_Base):
    """Final stage-3 output, built in pipeline/match.py (not an LLM schema)."""

    matches: list[RequirementMatch]
    eligibility: list[EligibilityCheck] = []


# ---------- Stage 4: suggest rewrites ----------


class RewriteInput(_Base):
    requirements: RequirementsExtraction
    evidence: EvidenceExtraction
    matches: MatchResult


class RewriteDraft(_Base):
    evidence_id: str
    suggested_line: str
    requirement_ids: list[str]  # which requirements this rewrite surfaces
    reason: str


class RewriteDrafts(_Base):
    """[LLM OUTPUT] May be empty if nothing is worth rephrasing. Code copies the original line.

    Validation context (passed by pipeline/suggest_rewrites.py):
      evidence_ids: lines the LLM was allowed to rewrite
      requirement_ids: requirements a rewrite may claim to surface
    """

    rewrites: list[RewriteDraft]

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> "RewriteDrafts":
        ctx = info.context or {}
        if (evidence_ids := ctx.get("evidence_ids")) is not None:
            bad = sorted({r.evidence_id for r in self.rewrites} - set(evidence_ids))
            if bad:
                raise ValueError(f"rewrites may only target the listed lines; unknown evidence ids: {bad}")
        if (requirement_ids := ctx.get("requirement_ids")) is not None:
            bad = sorted({i for r in self.rewrites for i in r.requirement_ids} - set(requirement_ids))
            if bad:
                raise ValueError(f"unknown or non-target requirement ids: {bad}")
        if any(not r.requirement_ids for r in self.rewrites):
            raise ValueError("every rewrite needs at least one requirement_id")
        return self


class Rewrite(_Base):
    evidence_id: str
    original_line: str  # copied by code from the evidence line; never LLM-written
    suggested_line: str
    requirement_ids: list[str]
    reason: str
    # True when the rewrite names something the line implies but doesn't state (e.g. OOP for a
    # Python app). Shown as "only if true": the candidate must confirm it before using it.
    needs_confirmation: bool = False


class RewriteSuggestions(_Base):
    """Final stage-4 output, built in pipeline/suggest_rewrites.py (not an LLM schema)."""

    rewrites: list[Rewrite]


# ---------- Stage 5: recommend gap projects ----------

MIN_PROJECT_HOURS = 2
MAX_PROJECT_HOURS = 16  # "a weekend"


class RecommendInput(_Base):
    requirements: RequirementsExtraction
    evidence: EvidenceExtraction  # so projects can build on the candidate's existing stack
    matches: MatchResult


MAX_PROJECTS_PER_GAP = 3


class ProjectIdea(_Base):
    title: str
    description: str  # what to build and what it demonstrates
    estimated_hours: int

    @model_validator(mode="after")
    def _validate(self) -> "ProjectIdea":
        if not MIN_PROJECT_HOURS <= self.estimated_hours <= MAX_PROJECT_HOURS:
            raise ValueError(
                f"'{self.title}': estimated_hours must be {MIN_PROJECT_HOURS}-{MAX_PROJECT_HOURS} (a weekend)"
            )
        return self


def _check_projects(requirement_id: str, projects: list[ProjectIdea]) -> None:
    if not 1 <= len(projects) <= MAX_PROJECTS_PER_GAP:
        raise ValueError(f"{requirement_id}: give 1-{MAX_PROJECTS_PER_GAP} projects, got {len(projects)}")


class GapRecommendationDraft(_Base):
    requirement_id: str
    projects: list[ProjectIdea]
    resource_type: ResourceType
    resource_title: str  # e.g. "Kubernetes 'Hello Minikube' tutorial"
    resource_url: str | None = None  # LLM's proposed official URL; unverified, null if unsure

    @model_validator(mode="after")
    def _validate(self) -> "GapRecommendationDraft":
        _check_projects(self.requirement_id, self.projects)
        if self.resource_url is not None and not self.resource_url.startswith("https://"):
            raise ValueError(f"{self.requirement_id}: resource_url must be an https:// URL or null")
        return self


class GapRecommendationDrafts(_Base):
    """[LLM OUTPUT] URLs here are unverified; pipeline/recommend_gaps.py checks them.

    Validation context (passed by pipeline/recommend_gaps.py):
      requirement_ids: every target requirement must get exactly one recommendation
    """

    recommendations: list[GapRecommendationDraft]

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> "GapRecommendationDrafts":
        got = [r.requirement_id for r in self.recommendations]
        _check_unique_ids(got, "requirement")
        if (expected := (info.context or {}).get("requirement_ids")) is not None:
            missing = sorted(set(expected) - set(got))
            unknown = sorted(set(got) - set(expected))
            if missing or unknown:
                raise ValueError(f"need one recommendation per listed requirement; missing={missing} unknown={unknown}")
        return self


class GapRecommendation(_Base):
    requirement_id: str
    projects: list[ProjectIdea]
    resource_type: ResourceType
    resource_title: str
    # Always a working link: the verified official URL, or a web search for resource_title.
    resource_url: str
    resource_url_verified: bool  # False -> resource_url is a search link, and the UI says so


class GapRecommendations(_Base):
    """Final stage-5 output, built in pipeline/recommend_gaps.py (not an LLM schema)."""

    recommendations: list[GapRecommendation]


# ---------- Whole analysis (API + storage) ----------


class AnalysisRequest(_Base):
    session_id: str = Field(min_length=1)
    jd_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    resume_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    resume_label: str = Field(default="", max_length=200)  # e.g. the PDF's file name, for history tabs


class ParsedResume(_Base):
    """Resume text extracted from an upload, with contact details already removed."""

    text: str
    removed: list[str]  # kinds removed, e.g. ["name", "email", "link"]


class AnalysisResult(_Base):
    id: str
    session_id: str
    created_at: datetime
    # The job posting itself (public text), so past jobs can be re-read or re-analyzed.
    # Raw resume text is never stored; only the extracted, verified lines in `evidence`.
    jd_text: str = ""
    resume_label: str = ""  # which resume this was run with ("resume.pdf", "pasted text")
    # Fingerprint of the cleaned resume text: tells "same resume, run again" from "a different
    # resume" when grouping a job's analyses. Not reversible to the text.
    resume_hash: str = ""
    requirements: RequirementsExtraction
    evidence: EvidenceExtraction
    matches: MatchResult
    rewrites: RewriteSuggestions
    recommendations: GapRecommendations

    @computed_field
    @property
    def job_key(self) -> str:
        """Same job posting -> same key, so analyses of one job group together (history, ranking).

        The saved JD text when there is one (whitespace/case-insensitive); otherwise role + company.
        """
        if self.jd_text.strip():
            normalized = " ".join(self.jd_text.lower().split())
            return "jd:" + hashlib.sha256(normalized.encode()).hexdigest()[:16]
        company = (self.requirements.company or "").strip().lower()
        return f"role:{self.requirements.role_title.strip().lower()}|{company}"

    # Computed (not stored): recalculated on every load, so old saved analyses get it too.
    @computed_field
    @property
    def match_score(self) -> MatchScore:
        reqs = {r.id: r for r in self.requirements.requirements}
        units: dict[str, tuple[Priority, list[Bucket]]] = {}
        for m in self.matches.matches:
            req = reqs[m.requirement_id]
            if req.category in INTERVIEW_CATEGORIES:
                continue  # soft skills and traits are interview material, not resume gaps
            if req.category == SkillCategory.CREDENTIAL:
                continue  # a degree is a qualification (shown with eligibility), not a skill
            key = req.any_of_group or req.id
            priority, buckets = units.get(key, (req.priority, []))
            if req.priority == Priority.REQUIRED:
                priority = Priority.REQUIRED  # a group is required if any member is
            units[key] = (priority, [*buckets, m.bucket])
        ineligible = any(e.status == EligibilityStatus.NOT_MET for e in self.matches.eligibility)
        return match_score(list(units.values()), ineligible=ineligible)


class AnalysisSummary(_Base):
    """One row in a session's history list; the full result is fetched by id."""

    id: str
    created_at: datetime
    role_title: str
    company: str | None
    bucket_counts: dict[Bucket, int]
    match_percent: int
    job_key: str  # equal for analyses of the same job posting
    resume_label: str
    resume_hash: str

    @classmethod
    def from_result(cls, result: AnalysisResult) -> "AnalysisSummary":
        counts = {b: 0 for b in Bucket}
        for m in result.matches.matches:
            counts[m.bucket] += 1
        return cls(
            id=result.id,
            created_at=result.created_at,
            role_title=result.requirements.role_title,
            company=result.requirements.company,
            bucket_counts=counts,
            match_percent=result.match_score.percent,
            job_key=result.job_key,
            resume_label=result.resume_label,
            resume_hash=result.resume_hash,
        )


# ---------- Cross-JD gap ranking ----------


class GapOccurrence(_Base):
    analysis_id: str
    requirement_id: str
    role_title: str
    company: str | None
    bucket: Bucket  # gap or transferable
    priority: Priority


class RankedGap(_Base):
    canonical_skill: str
    skill: str  # display name: the most common way JDs wrote it
    category: SkillCategory
    score: float  # higher = worth learning first
    job_count: int
    required_count: int
    occurrences: list[GapOccurrence]  # newest first
    # Projects + resource from the newest analysis that recommended any for this skill.
    recommendation: GapRecommendation | None = None


class GapRanking(_Base):
    """Built by services/gap_ranking.py from a session's analyses (not an LLM schema)."""

    analysis_count: int  # distinct jobs considered
    gaps: list[RankedGap]
    dismissed: list[str] = []  # canonical skills the user hid; offered for restore
