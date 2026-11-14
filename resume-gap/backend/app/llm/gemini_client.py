"""Gemini provider via the google-genai Interactions API.

Handles transport-level retries only; bad-JSON retry lives in LLMClient.complete_json.

The SDK's built-in retry is disabled: by default it silently backs off on 429s,
which looked like a ~60s hang during testing. We retry here so rate limits
either recover quickly or fail fast with LLMRateLimitError.
"""

import logging
import time

from google import genai
from google.genai import types
from pydantic import BaseModel

from .base import LLMClient, LLMError, LLMRateLimitError

log = logging.getLogger(__name__)

_SERVER_ERROR_STATUS = {500, 503}
_SERVER_ERROR_BACKOFF_SECONDS = (2.0, 5.0)  # waits before retry 1 and retry 2
_MAX_RATE_LIMIT_WAIT_SECONDS = 10.0  # longer than this -> fail fast instead of waiting


def _status_code(e: Exception) -> int | None:
    # The SDK raises different error classes per API surface; both carry a status.
    for attr in ("status_code", "code"):
        value = getattr(e, attr, None)
        if isinstance(value, int):
            return value
    return None


def _retry_after(e: Exception) -> float | None:
    headers = getattr(e, "headers", None)
    if headers is None:
        return None
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


class GeminiClient(LLMClient):
    def __init__(self, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self._model = model
        self._timeout_seconds = timeout_seconds

    def _generate(self, prompt: str, schema: type[BaseModel]) -> str:
        response_format = {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema.model_json_schema(),
        }
        server_error_retries = 0
        rate_limit_retried = False

        while True:
            try:
                interaction = self._client.interactions.create(
                    model=self._model,
                    input=prompt,
                    response_format=response_format,
                    store=False,  # don't retain resumes server-side
                    timeout=self._timeout_seconds,
                )
                # Empty output becomes a validation error upstream, which triggers the JSON retry.
                return interaction.output_text or ""
            except Exception as e:
                status = _status_code(e)

                if status == 429:
                    wait = _retry_after(e)
                    if not rate_limit_retried and wait is not None and wait <= _MAX_RATE_LIMIT_WAIT_SECONDS:
                        log.warning("Gemini 429, retrying once in %.1fs", wait)
                        rate_limit_retried = True
                        time.sleep(wait)
                        continue
                    raise LLMRateLimitError("Gemini rate limit hit", retry_after_seconds=wait) from e

                if status in _SERVER_ERROR_STATUS and server_error_retries < len(_SERVER_ERROR_BACKOFF_SECONDS):
                    wait = _SERVER_ERROR_BACKOFF_SECONDS[server_error_retries]
                    server_error_retries += 1
                    log.warning("Gemini %s, retry %d in %.1fs", status, server_error_retries, wait)
                    time.sleep(wait)
                    continue

                raise LLMError(f"Gemini call failed ({status or type(e).__name__}): {e}") from e
