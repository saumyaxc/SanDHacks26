"""Run stages 1-3 (requirements, evidence, match) on real fixtures with real Gemini.

From backend/:
    python -m scripts.run_match                                  # every JD vs the first resume
    python -m scripts.run_match --jd jd1.txt --resume mine.txt   # one pair

Calls: 1 evidence extraction + 2 per JD.
"""

import argparse
import logging
import time
from collections import Counter
from pathlib import Path

from app.config import get_settings
from app.domain.enums import Bucket
from app.domain.schemas import ExtractEvidenceInput, ExtractRequirementsInput, MatchInput
from app.llm.base import LLMError
from app.llm.gemini_client import GeminiClient
from app.pipeline.extract_evidence import extract_evidence
from app.pipeline.extract_requirements import extract_requirements
from app.pipeline.match import match

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_QUOTE_WIDTH = 60
_ORDER = [Bucket.COVERED, Bucket.UNDEREMPHASIZED, Bucket.TRANSFERABLE, Bucket.GAP]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jd", action="append", help="JD fixture name (repeatable; default: all)")
    parser.add_argument("--resume", help="resume fixture name (default: first)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="  ! %(message)s")
    jd_paths = [FIXTURES / "jds" / j for j in args.jd] if args.jd else sorted((FIXTURES / "jds").glob("*.txt"))
    resumes = sorted((FIXTURES / "resumes").glob("*.txt"))
    resume_path = FIXTURES / "resumes" / args.resume if args.resume else (resumes[0] if resumes else None)
    if not jd_paths or resume_path is None:
        raise SystemExit("Need at least one JD in fixtures/jds/ and one resume in fixtures/resumes/")

    settings = get_settings()
    llm = GeminiClient(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.llm_timeout_seconds,
    )
    print(f"model: {settings.gemini_model}   resume: {resume_path.name}\n")

    start = time.perf_counter()
    try:
        evidence = extract_evidence(ExtractEvidenceInput(resume_text=resume_path.read_text(encoding="utf-8")), llm)
    except LLMError as e:
        raise SystemExit(f"evidence extraction FAILED: {e}")
    print(f"evidence: {len(evidence.items)} items ({time.perf_counter() - start:.1f}s)\n")

    for jd_path in jd_paths:
        start = time.perf_counter()
        try:
            reqs = extract_requirements(ExtractRequirementsInput(jd_text=jd_path.read_text(encoding="utf-8")), llm)
            result = match(MatchInput(requirements=reqs, evidence=evidence), llm)
        except LLMError as e:
            print(f"== {jd_path.name}  FAILED: {e}\n")
            continue
        elapsed = time.perf_counter() - start

        counts = Counter(m.bucket for m in result.matches)
        summary = "  ".join(f"{b.value} {counts.get(b, 0)}" for b in _ORDER)
        print(f"== {jd_path.name}  {reqs.role_title}  ({elapsed:.1f}s)")
        print(f"   {summary}\n")

        req_by_id = {r.id: r for r in reqs.requirements}
        for m in result.matches:
            r = req_by_id[m.requirement_id]
            pri = "REQ " if r.priority == "required" else "pref"
            group = f" [{r.any_of_group}]" if r.any_of_group else ""
            sat = f"  (satisfied by {m.satisfied_by})" if m.satisfied_by else ""
            print(f"  {r.id:<7}{pri} {r.canonical_skill + group:<34}{m.bucket.upper():<16}{m.evidence_id or '':<6}{sat}")
            if m.evidence_quote:
                q = m.evidence_quote
                print(f"  {'':<12}\"{q if len(q) <= _QUOTE_WIDTH else q[: _QUOTE_WIDTH - 3] + '...'}\"")
            print(f"  {'':<12}{m.rationale}")
        print()


if __name__ == "__main__":
    main()
