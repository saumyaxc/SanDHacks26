"""Dev-only sanity check for the Gemini key, model, and our schemas.

Run from backend/:
    python -m scripts.check_gemini              # 2 calls
    python -m scripts.check_gemini --burst 15   # + N raw calls to find the rate limit

Prompts are inline because this is a throwaway script, not app code.
"""

import argparse
import logging
import time

from pydantic import BaseModel

from app.config import get_settings
from app.domain.schemas import RequirementsExtraction
from app.llm.gemini_client import GeminiClient, _status_code

TINY_JD = """Backend Engineer at Acme.
Requirements: 3+ years of Python. Experience with K8s. AWS is a plus."""


class Ping(BaseModel):
    message: str
    number: int


def timed(label: str, fn):
    start = time.perf_counter()
    result = fn()
    print(f"[{label}] {time.perf_counter() - start:.2f}s")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--burst", type=int, default=0, help="raw calls, SDK retry disabled")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()
    print(f"model: {settings.gemini_model}")
    client = GeminiClient(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.llm_timeout_seconds,
    )

    ping = timed("ping", lambda: client.complete_json(
        'Return JSON with message "pong" and number 42.', Ping
    ))
    print(ping)

    reqs = timed("requirements schema", lambda: client.complete_json(
        "Extract every requirement from this job description. Use ids req-1, req-2, ... "
        "Use short skill names. jd_quote must be copied verbatim.\n\n" + TINY_JD,
        RequirementsExtraction,
    ))
    for r in reqs.requirements:
        print(f"  {r.id}: {r.skill!r} -> {r.canonical_skill!r} ({r.category}, {r.priority})")

    if args.burst:
        print(f"\nburst: {args.burst} raw calls, no retries")
        for i in range(1, args.burst + 1):
            start = time.perf_counter()
            try:
                it = client._client.interactions.create(
                    model=settings.gemini_model, input="Say ok.", store=False
                )
                print(f"  {i:>3} ok   {time.perf_counter() - start:.2f}s  usage={getattr(it, 'usage', None)}")
            except Exception as e:
                print(f"  {i:>3} FAIL {_status_code(e)}  {time.perf_counter() - start:.2f}s  {str(e)[:200]}")
                if _status_code(e) == 429:
                    print(f"rate limited after {i - 1} successful calls")
                    break


if __name__ == "__main__":
    main()
