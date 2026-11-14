"""LLM interface. Pipeline code depends only on this file, never on a provider."""

import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

_MAX_ERROR_CHARS = 2000


class LLMError(Exception):
    """The provider failed, or returned invalid output even after a retry."""


class LLMRateLimitError(LLMError):
    """Provider quota hit. The API layer maps this to HTTP 429."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMClient(ABC):
    def complete_json[T: BaseModel](self, prompt: str, schema: type[T]) -> T:
        """Call the model and return a validated `schema` instance.

        On invalid JSON or a failed validator, retries once with the error
        appended to the prompt. Raises LLMError if the retry also fails.
        """
        attempt_prompt = prompt
        error: ValidationError | None = None

        for attempt in (1, 2):
            raw = self._generate(attempt_prompt, schema)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                error = e
                log.warning("%s attempt %d invalid: %s", schema.__name__, attempt, e)
                attempt_prompt = (
                    f"{prompt}\n\n"
                    "Your previous response failed validation with this error:\n"
                    f"{str(e)[:_MAX_ERROR_CHARS]}\n"
                    "Return only corrected JSON matching the schema."
                )

        raise LLMError(f"{schema.__name__}: invalid output after retry: {error}") from error

    @abstractmethod
    def _generate(self, prompt: str, schema: type[BaseModel]) -> str:
        """Return the raw JSON text produced by the model."""
