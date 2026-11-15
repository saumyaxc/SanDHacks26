import logging
import math

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_llm
from app.domain.schemas import AnalysisRequest, AnalysisResult
from app.llm.base import LLMClient, LLMError, LLMRateLimitError
from app.pipeline.orchestrator import run_analysis

log = logging.getLogger(__name__)

router = APIRouter()


# Sync on purpose: the pipeline blocks on LLM calls, so FastAPI runs it in a worker thread.
@router.post("/analyze", response_model=AnalysisResult)
def analyze(request: AnalysisRequest, llm: LLMClient = Depends(get_llm)) -> AnalysisResult:
    try:
        return run_analysis(request, llm)
    except LLMRateLimitError as e:
        log.warning("rate limited: %s", e)
        headers = {"Retry-After": str(math.ceil(e.retry_after_seconds))} if e.retry_after_seconds else None
        raise HTTPException(429, "The AI model is rate-limited right now. Try again in a minute.", headers=headers)
    except LLMError as e:
        log.exception("analysis failed")
        raise HTTPException(502, f"The AI model failed to produce a valid analysis: {e}")
