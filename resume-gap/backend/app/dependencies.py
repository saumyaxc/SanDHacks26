"""The only place that decides which LLM client, repository, and link checker are used.

Routes depend on these functions via FastAPI's Depends; tests swap them with
app.dependency_overrides.
"""

from functools import lru_cache

from app.config import get_settings
from app.db.base import AnalysisRepository
from app.db.memory_repo import MemoryRepository
from app.llm.base import LLMClient
from app.llm.fake_client import FakeLLMClient
from app.llm.gemini_client import GeminiClient
from app.pipeline.recommend_gaps import UrlChecker
from app.services.link_check import url_is_live


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


@lru_cache
def get_repo() -> AnalysisRepository:
    # One shared instance: the in-memory store lives as long as the process.
    return MemoryRepository()


def get_url_checker() -> UrlChecker:
    return url_is_live
