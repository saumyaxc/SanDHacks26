"""The only place that knows the stage order.

    1 extract_requirements ┐
    2 extract_evidence     ┘ parallel (independent inputs)
    3 match
    4 suggest_rewrites     ┐
    5 recommend_gaps       ┘ parallel (both only read stages 1-3)

Five LLM calls in three rounds. Any stage's LLMError propagates to the caller.
`url_is_live` checks resource links in stage 5 (injected so tests never hit the network).
"""

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from app.domain.schemas import (
    AnalysisRequest,
    AnalysisResult,
    ExtractEvidenceInput,
    ExtractRequirementsInput,
    MatchInput,
    RecommendInput,
    RewriteInput,
)
from app.llm.base import LLMClient
from app.pipeline.extract_evidence import extract_evidence
from app.pipeline.extract_requirements import extract_requirements
from app.pipeline.match import match
from app.pipeline.recommend_gaps import UrlChecker, recommend_gaps
from app.pipeline.suggest_rewrites import suggest_rewrites


def run_analysis(
    request: AnalysisRequest,
    llm: LLMClient,
    url_is_live: UrlChecker,
    known_skills: list[str] | None = None,
) -> AnalysisResult:
    """`known_skills`: canonical names from past analyses, so new ones reuse the same names."""
    known = known_skills or []

    with ThreadPoolExecutor(max_workers=2) as pool:
        reqs_f = pool.submit(
            extract_requirements, ExtractRequirementsInput(jd_text=request.jd_text, known_skills=known), llm
        )
        evidence_f = pool.submit(
            extract_evidence, ExtractEvidenceInput(resume_text=request.resume_text, known_skills=known), llm
        )
        requirements, evidence = reqs_f.result(), evidence_f.result()

    matches = match(MatchInput(requirements=requirements, evidence=evidence), llm)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rewrites_f = pool.submit(
            suggest_rewrites, RewriteInput(requirements=requirements, evidence=evidence, matches=matches), llm
        )
        recs_f = pool.submit(
            recommend_gaps,
            RecommendInput(requirements=requirements, evidence=evidence, matches=matches),
            llm,
            url_is_live,
        )
        rewrites, recommendations = rewrites_f.result(), recs_f.result()

    return AnalysisResult(
        id=uuid.uuid4().hex,
        session_id=request.session_id,
        created_at=datetime.now(UTC),
        jd_text=request.jd_text,
        resume_label=request.resume_label,
        resume_hash=_fingerprint(request.resume_text),
        requirements=requirements,
        evidence=evidence,
        matches=matches,
        rewrites=rewrites,
        recommendations=recommendations,
    )


def _fingerprint(text: str) -> str:
    """Same resume (ignoring whitespace and case) -> same short hash."""
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:16]
