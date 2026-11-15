"""The only place that decides which LLM client (and later, which repository) is used.

Routes depend on these functions via FastAPI's Depends; tests swap them with
app.dependency_overrides.
"""

from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMClient
from app.llm.fake_client import FakeLLMClient
from app.llm.gemini_client import GeminiClient


@lru_cache
def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "gemini":
        return GeminiClient(
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_model,
            settings.llm_timeout_seconds,
        )
    return FakeLLMClient()
