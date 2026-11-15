from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# resume-gap/.env, regardless of the working directory.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    llm_provider: Literal["fake", "gemini"] = "fake"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: float = 30.0
    # Neon Postgres connection string. Empty -> in-memory storage (lost on restart).
    database_url: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def _require_key_for_gemini(self) -> "Settings":
        if self.llm_provider == "gemini" and not self.gemini_api_key.get_secret_value():
            raise ValueError("LLM_PROVIDER=gemini but GEMINI_API_KEY is empty")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
