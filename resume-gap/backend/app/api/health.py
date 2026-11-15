from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    # No LLM call here: health must stay cheap and must not burn rate-limit quota.
    settings = get_settings()
    return {"status": "ok", "llm_provider": settings.llm_provider}
