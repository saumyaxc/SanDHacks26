"""Run stage 1 against real JDs with real Gemini, for eyeballing quality.

Put JDs in tests/fixtures/jds/*.txt, then from backend/:
    python -m scripts.run_extract_requirements            # all fixtures
    python -m scripts.run_extract_requirements acme.txt   # just one
"""

import argparse
import logging
import time
from pathlib import Path

from app.config import get_settings
from app.domain.quotes import quote_in_text
from app.domain.schemas import ExtractRequirementsInput
from app.domain.skills import ALIASES
from app.llm.base import LLMError
from app.llm.gemini_client import GeminiClient
from app.pipeline.extract_requirements import extract_requirements

JD_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "jds"
_KNOWN_CANONICAL = set(ALIASES.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="fixture file names (default: all)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    paths = [JD_DIR / f for f in args.files] if args.files else sorted(JD_DIR.glob("*.txt"))
    if not paths:
        raise SystemExit(f"No JDs found. Add .txt files to {JD_DIR}")

    settings = get_settings()
    llm = GeminiClient(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.llm_timeout_seconds,
    )
    print(f"model: {settings.gemini_model}\n")

    for path in paths:
        jd_text = path.read_text(encoding="utf-8")
        start = time.perf_counter()
        try:
            result = extract_requirements(ExtractRequirementsInput(jd_text=jd_text), llm)
        except LLMError as e:
            print(f"== {path.name}  FAILED: {e}\n")
            continue
        elapsed = time.perf_counter() - start

        bad_quotes = [r for r in result.requirements if not quote_in_text(r.jd_quote, jd_text)]
        passthrough = sorted(
            {r.canonical_skill for r in result.requirements if r.canonical_skill not in _KNOWN_CANONICAL}
        )
        n = len(result.requirements)

        print(f"== {path.name}  ({elapsed:.1f}s)")
        print(f"role: {result.role_title} @ {result.company or '?'}")
        print(f"{n} requirements, {n - len(bad_quotes)}/{n} quotes verbatim\n")
        for r in result.requirements:
            pri = "REQ " if r.priority == "required" else "pref"
            years = f" ({r.years_required}y)" if r.years_required else ""
            group = f" [{r.any_of_group}]" if r.any_of_group else ""
            flag = "  ! quote not in JD" if r in bad_quotes else ""
            print(f"  {r.id:<7}{pri} {r.category:<17}{r.skill!r} -> {r.canonical_skill!r}{group}{years}{flag}")
        for r in bad_quotes:
            print(f"\n  ! {r.id} quote: {r.jd_quote!r}")
        print(f"\n  new canonical names (not in seed vocabulary): {', '.join(passthrough) or '-'}\n")


if __name__ == "__main__":
    main()
