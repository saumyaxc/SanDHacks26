"""The contract. Every pipeline stage takes one of these in and returns one out.

Models marked [LLM OUTPUT] are sent to Gemini as response schemas, so keep
them to plain types (str/int/list/enum/nested model). Put rules in validators,
not Field(...) constraints — validators never reach the LLM, and a failure
triggers the client's retry.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from .enums import Bucket, Priority, ResourceType, ResumeSection, SkillCategory
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


class Requirement(_Base):
    id: str  # e.g. "req-1"
    skill: str  # short skill name as written in the JD, e.g. "K8s"
    category: SkillCategory
    priority: Priority
    years_required: int | None = None
    jd_quote: str  # the JD line this came from

    @computed_field
    @property
    def canonical_skill(self) -> str:
        return normalize_skill(self.skill)


class RequirementsExtraction(_Base):
    """[LLM OUTPUT]"""

    role_title: str
    company: str | None = None
    requirements: list[Requirement]

    @model_validator(mode="after")
    def _validate(self) -> "RequirementsExtraction":
        if not self.requirements:
            raise ValueError("no requirements extracted")
        _check_unique_ids([r.id for r in self.requirements], "requirement")
        return self


# ---------- Stage 2: extract evidence ----------


class ExtractEvidenceInput(_Base):
    resume_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)


class EvidenceItem(_Base):
    id: str  # e.g. "ev-1"
    section: ResumeSection
    line: str  # exact resume line, verbatim
    skills: list[str]  # skills this line demonstrates, as written

    @computed_field
    @property
    def canonical_skills(self) -> list[str]:
        return [normalize_skill(s) for s in self.skills]


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


class RequirementMatch(_Base):
    requirement_id: str
    bucket: Bucket
    evidence_id: str | None = None
    evidence_quote: str | None = None  # exact resume line; required unless bucket == gap
    rationale: str

    @model_validator(mode="after")
    def _validate(self) -> "RequirementMatch":
        if self.bucket == Bucket.GAP:
            # A gap has no evidence by definition; drop anything the LLM invented.
            self.evidence_id = None
            self.evidence_quote = None
        elif not self.evidence_id or not self.evidence_quote:
            raise ValueError(
                f"{self.requirement_id}: bucket '{self.bucket}' requires evidence_id and evidence_quote"
            )
        return self


class MatchResult(_Base):
    """[LLM OUTPUT] Verbatim-quote and one-match-per-requirement checks
    need the inputs, so they live in pipeline/match.py, not here."""

    matches: list[RequirementMatch]


# ---------- Stage 4: suggest rewrites ----------


class RewriteInput(_Base):
    requirements: RequirementsExtraction
    evidence: EvidenceExtraction
    matches: MatchResult


class Rewrite(_Base):
    evidence_id: str
    original_line: str  # verbatim resume line being rephrased
    suggested_line: str
    requirement_ids: list[str]  # which requirements this rewrite surfaces
    reason: str

    @model_validator(mode="after")
    def _validate(self) -> "Rewrite":
        if self.suggested_line == self.original_line:
            raise ValueError(f"{self.evidence_id}: rewrite is identical to original")
        return self


class RewriteSuggestions(_Base):
    """[LLM OUTPUT] May be empty if nothing is worth rephrasing."""

    rewrites: list[Rewrite]


# ---------- Stage 5: recommend gap projects ----------


class RecommendInput(_Base):
    requirements: RequirementsExtraction
    matches: MatchResult


class GapRecommendation(_Base):
    requirement_id: str
    project_title: str
    project_description: str  # weekend-scoped
    estimated_hours: int
    resource_type: ResourceType
    resource_suggestion: str  # e.g. "Official Kubernetes 'Hello Minikube' tutorial"


class GapRecommendations(_Base):
    """[LLM OUTPUT]"""

    recommendations: list[GapRecommendation]


# ---------- Whole analysis (API + storage) ----------


class AnalysisRequest(_Base):
    session_id: str = Field(min_length=1)
    jd_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    resume_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)


class AnalysisResult(_Base):
    id: str
    session_id: str
    created_at: datetime
    requirements: RequirementsExtraction
    evidence: EvidenceExtraction
    matches: MatchResult
    rewrites: RewriteSuggestions
    recommendations: GapRecommendations
