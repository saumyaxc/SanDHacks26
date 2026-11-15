"""Run stages 1-3 (requirements, evidence, match) on real fixtures with real Gemini.

From backend/:
    python -m scripts.run_match                                  # every JD vs the first resume
    python -m scripts.run_match --jd jd1.txt --resume mine.txt   # one pair
    python -m scripts.run_match --jd jd1.txt --full              # also rewrites + recommendations

Calls: 1 evidence extraction + 2 per JD (+ up to 2 more per JD with --full).
"""

import argparse
import logging
import time
from collections import Counter
from pathlib import Path

from app.config import get_settings
from app.domain.enums import Bucket
from app.domain.schemas import (
    ExtractEvidenceInput,
    ExtractRequirementsInput,
    MatchInput,
    RecommendInput,
    RewriteInput,
)
from app.llm.base import LLMError
from app.llm.gemini_client import GeminiClient
from app.pipeline.extract_evidence import extract_evidence
from app.pipeline.extract_requirements import extract_requirements
from app.pipeline.match import match
from app.pipeline.recommend_gaps import recommend_gaps
from app.services.link_check import url_is_live
from app.pipeline.suggest_rewrites import suggest_rewrites

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_QUOTE_WIDTH = 60
_ORDER = [Bucket.COVERED, Bucket.UNDEREMPHASIZED, Bucket.TRANSFERABLE, Bucket.GAP]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jd", action="append", help="JD fixture name (repeatable; default: all)")
    parser.add_argument("--resume", help="resume fixture name (default: first)")
    parser.add_argument("--full", action="store_true", help="also run rewrites and recommendations")
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
            if args.full:
                rewrites = suggest_rewrites(RewriteInput(requirements=reqs, evidence=evidence, matches=result), llm)
                recs = recommend_gaps(
                    RecommendInput(requirements=reqs, evidence=evidence, matches=result), llm, url_is_live
                )
        except LLMError as e:
            print(f"== {jd_path.name}  FAILED: {e}\n")
            continue
        elapsed = time.perf_counter() - start

        counts = Counter(m.bucket for m in result.matches)
        summary = "  ".join(f"{b.value} {counts.get(b, 0)}" for b in _ORDER)
        print(f"== {jd_path.name}  {reqs.role_title}  ({elapsed:.1f}s)")
        print(f"   {summary}")
        print(f"   match {result_score(reqs, evidence, result)}\n")
        rules = {e.id: e for e in reqs.eligibility}
        for check in result.eligibility:
            rule = rules[check.eligibility_id]
            print(f"  ELIG {check.status.upper():<8} {rule.kind}: {rule.description}")
            print(f"  {'':<14}{check.rationale}")
        if result.eligibility:
            print()

        req_by_id = {r.id: r for r in reqs.requirements}
        for m in result.matches:
            r = req_by_id[m.requirement_id]
            pri = "REQ " if r.priority == "required" else "pref"
            group = f" [{r.any_of_group}]" if r.any_of_group else ""
            sat = f"  (satisfied by {m.satisfied_by})" if m.satisfied_by else ""
            cat = " (trait)" if r.category == "trait" else ""
            print(f"  {r.id:<7}{pri} {r.canonical_skill + group + cat:<34} {m.bucket.upper():<16}{m.evidence_id or '':<6}{sat}")
            if m.evidence_quote:
                q = m.evidence_quote
                print(f"  {'':<12}\"{q if len(q) <= _QUOTE_WIDTH else q[: _QUOTE_WIDTH - 3] + '...'}\"")
            print(f"  {'':<12}{m.rationale}")
        print()

        if not args.full:
            continue
        print(f"   rewrites ({len(rewrites.rewrites)})")
        for rw in rewrites.rewrites:
            flag = "  [ONLY IF TRUE]" if rw.needs_confirmation else ""
            print(f"  {rw.evidence_id:<7}for {', '.join(rw.requirement_ids)}{flag}")
            print(f"  {'':<7}- {rw.original_line}")
            print(f"  {'':<7}+ {rw.suggested_line}")
            print(f"  {'':<7}  {rw.reason}")
        print(f"\n   recommendations ({len(recs.recommendations)})")
        for rec in recs.recommendations:
            r = req_by_id[rec.requirement_id]
            print(f"  {r.id:<7}{r.canonical_skill}")
            for p in rec.projects:
                print(f"  {'':<7}- {p.title} ({p.estimated_hours}h): {p.description}")
            mark = "VERIFIED" if rec.resource_url_verified else "search"
            print(f"  {'':<7}[{rec.resource_type}] {rec.resource_title}  ({mark}) {rec.resource_url}")
        print()


def result_score(reqs, evidence, matches) -> str:
    # Build a throwaway AnalysisResult just to reuse the real scoring.
    from datetime import UTC, datetime

    from app.domain.schemas import AnalysisResult, GapRecommendations, RewriteSuggestions

    r = AnalysisResult(
        id="x",
        session_id="x",
        created_at=datetime.now(UTC),
        requirements=reqs,
        evidence=evidence,
        matches=matches,
        rewrites=RewriteSuggestions(rewrites=[]),
        recommendations=GapRecommendations(recommendations=[]),
    )
    s = r.match_score
    return f"{s.percent}% ({s.verdict}), required {s.required_met}/{s.required_total}"


if __name__ == "__main__":
    main()
