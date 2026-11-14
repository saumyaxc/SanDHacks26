"""Run stage 2 against real resumes with real Gemini, for eyeballing quality.

Put resumes in tests/fixtures/resumes/*.txt (gitignored), then from backend/:
    python -m scripts.run_extract_evidence              # all fixtures
    python -m scripts.run_extract_evidence mine.txt     # just one

Lines the LLM didn't copy verbatim are dropped by the stage and logged as
"dropping evidence not found verbatim" warnings above the results.
"""

import argparse
import logging
import time
from pathlib import Path

from app.config import get_settings
from app.domain.schemas import ExtractEvidenceInput
from app.domain.skills import known_canonical_skills
from app.llm.base import LLMError
from app.llm.gemini_client import GeminiClient
from app.pipeline.extract_evidence import extract_evidence

RESUME_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "resumes"
_LINE_WIDTH = 70


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="fixture file names (default: all)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="  ! %(message)s")
    paths = [RESUME_DIR / f for f in args.files] if args.files else sorted(RESUME_DIR.glob("*.txt"))
    if not paths:
        raise SystemExit(f"No resumes found. Add .txt files to {RESUME_DIR}")

    settings = get_settings()
    llm = GeminiClient(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.llm_timeout_seconds,
    )
    print(f"model: {settings.gemini_model}\n")
    seed = known_canonical_skills()

    for path in paths:
        print(f"== {path.name}")
        start = time.perf_counter()
        try:
            result = extract_evidence(ExtractEvidenceInput(resume_text=path.read_text(encoding="utf-8")), llm)
        except (LLMError, ValueError) as e:
            print(f"  FAILED: {e}\n")
            continue
        print(f"{len(result.items)} evidence items ({time.perf_counter() - start:.1f}s)\n")

        for item in result.items:
            line = item.line if len(item.line) <= _LINE_WIDTH else item.line[: _LINE_WIDTH - 3] + "..."
            print(f"  {item.id:<6}{item.section:<11}{line}")
            skills = ", ".join(
                s.canonical_skill if s.skill.lower() == s.canonical_skill else f"{s.skill} -> {s.canonical_skill}"
                for s in item.skills
            )
            print(f"  {'':<17}[{skills or 'no skills'}]")

        new = sorted({s.canonical_skill for i in result.items for s in i.skills} - seed)
        print(f"\n  new canonical names (not in seed vocabulary): {', '.join(new) or '-'}\n")


if __name__ == "__main__":
    main()
