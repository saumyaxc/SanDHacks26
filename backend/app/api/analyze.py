import hashlib
import json
import logging
import math

from fastapi import APIRouter, Depends, HTTPException

from app.db.base import AnalysisRepository
from app.dependencies import get_llm, get_repo, get_url_checker
from app.domain.redact import redact_resume
from app.domain.schemas import AnalysisRequest, AnalysisResult
from app.llm.base import LLMClient, LLMError, LLMRateLimitError
from app.pipeline.extract_requirements import NotAJobDescription
from app.pipeline.orchestrator import run_analysis
from app.pipeline.recommend_gaps import UrlChecker

log = logging.getLogger(__name__)

router = APIRouter()

# Bump when prompts or pipeline logic change, so stored results aren't served as cache hits.
_CACHE_VERSION = "14"


def input_hash(request: AnalysisRequest) -> str:
    """Same JD + resume (ignoring line endings and outer whitespace) -> same hash."""

    def norm(text: str) -> str:
        return text.replace("\r\n", "\n").strip()

    payload = json.dumps([_CACHE_VERSION, norm(request.jd_text), norm(request.resume_text)])
    return hashlib.sha256(payload.encode()).hexdigest()


# Sync on purpose: the pipeline blocks on LLM calls, so FastAPI runs it in a worker thread.
@router.post("/analyze", response_model=AnalysisResult)
def analyze(
    request: AnalysisRequest,
    llm: LLMClient = Depends(get_llm),
    repo: AnalysisRepository = Depends(get_repo),
    url_is_live: UrlChecker = Depends(get_url_checker),
) -> AnalysisResult:
    # Pasted resumes get the same contact-info removal as uploads, before anything else sees them.
    resume_text = redact_resume(request.resume_text).text
    if not resume_text.strip():
        raise HTTPException(422, "The resume is empty after removing contact details.")
    request = request.model_copy(update={"resume_text": resume_text})

    key = input_hash(request)
    if cached := repo.find_by_hash(request.session_id, key):
        log.info("cache hit for session %s -> %s", request.session_id, cached.id)
        return cached

    try:
        result = run_analysis(request, llm, url_is_live, known_skills=repo.known_skills(request.session_id))
    except NotAJobDescription as e:
        raise HTTPException(422, str(e))
    except LLMRateLimitError as e:
        log.warning("rate limited: %s", e)
        headers = {"Retry-After": str(math.ceil(e.retry_after_seconds))} if e.retry_after_seconds else None
        raise HTTPException(429, "The AI model is rate-limited right now. Try again in a minute.", headers=headers)
    except LLMError as e:
        log.exception("analysis failed")
        raise HTTPException(502, f"The AI model failed to produce a valid analysis: {e}")

    repo.save(result, key)
    return result
