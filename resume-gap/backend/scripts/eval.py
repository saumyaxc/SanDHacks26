"""Score the pipeline against hand-checked answers, so prompt/model changes are measured.

1. Create a labels file pre-filled with what the pipeline says today:
       python -m scripts.eval init --jd jd4.txt
   -> tests/fixtures/labels/jd4.json. Open it and fix every "expected" that's wrong.
      Allowed: covered, underemphasized, transferable, gap, interview, not_a_requirement
      ("interview" = soft skill/trait: cover-letter material, not graded.)

2. Score everything that has a labels file (re-runs the pipeline):
       python -m scripts.eval
       python -m scripts.eval --jd jd4.txt

Labels hold skill names and JD wording only — never resume lines — so they're safe to commit.
Calls per JD: 1 evidence (shared) + 2 (requirements, match).
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from app.config import get_settings
from app.domain.enums import INTERVIEW_CATEGORIES
from app.domain.redact import redact_resume  # same cleaning as the API
from app.domain.schemas import (
    EvidenceExtraction,
    ExtractEvidenceInput,
    ExtractRequirementsInput,
    MatchInput,
    MatchResult,
    RequirementsExtraction,
)
from app.domain.skills import normalize_skill
from app.llm.base import LLMError
from app.llm.gemini_client import GeminiClient
from app.pipeline.extract_evidence import extract_evidence
from app.pipeline.extract_requirements import extract_requirements
from app.pipeline.match import match

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
LABELS = FIXTURES / "labels"
ALLOWED = {"covered", "underemphasized", "transferable", "gap", "interview", "not_a_requirement"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["init", "score"], default="score")
    parser.add_argument("--jd", action="append", dest="jds", default=[], help="JD fixture name (repeatable)")
    parser.add_argument("--resume", help="resume fixture name (default: first)")
    args = parser.parse_args()

    resume_path = _resume(args.resume)
    llm = _llm()
    evidence = _evidence(resume_path, llm)

    if args.command == "init":
        if not args.jds:
            sys.exit("Usage: python -m scripts.eval init --jd jd4.txt [--jd jd5.txt ...]")
        for jd in args.jds:
            _init(jd, resume_path.name, evidence, llm)
        return

    label_files = [LABELS / f"{Path(j).stem}.json" for j in args.jds] if args.jds else sorted(LABELS.glob("*.json"))
    if not label_files:
        sys.exit("No labels yet. Start with: python -m scripts.eval init --jd jd1.txt")
    totals: Counter[str] = Counter()
    for path in label_files:
        _score(path, evidence, llm, totals)
    if len(label_files) > 1:
        print(f"== TOTAL  {_pct(totals['correct'], totals['labeled'])} correct "
              f"({totals['correct']}/{totals['labeled']}), {totals['missing']} missing, {totals['extra']} unlabeled")


def _run(jd_name: str, evidence: EvidenceExtraction, llm) -> tuple[RequirementsExtraction, MatchResult]:
    jd_text = (FIXTURES / "jds" / jd_name).read_text(encoding="utf-8")
    reqs = extract_requirements(ExtractRequirementsInput(jd_text=jd_text), llm)
    return reqs, match(MatchInput(requirements=reqs, evidence=evidence), llm)


def _answer(req, bucket: str) -> str:
    return "interview" if req.category in INTERVIEW_CATEGORIES else bucket


def _init(jd_name: str, resume_name: str, evidence, llm) -> None:
    out = LABELS / f"{Path(jd_name).stem}.json"
    if out.exists():
        sys.exit(f"{out.name} already exists; edit it, or delete it to start over.")
    reqs, result = _run(jd_name, evidence, llm)
    by_req = {r.id: r for r in reqs.requirements}
    labels = [
        {
            "skill": by_req[m.requirement_id].canonical_skill,
            "category": by_req[m.requirement_id].category.value,
            "jd_says": by_req[m.requirement_id].jd_quote,
            "pipeline_said": _answer(by_req[m.requirement_id], m.bucket.value),
            "expected": _answer(by_req[m.requirement_id], m.bucket.value),
        }
        for m in result.matches
    ]
    LABELS.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"jd": jd_name, "resume": resume_name, "labels": labels}, indent=2) + "\n")
    print(f"wrote {out.relative_to(FIXTURES.parents[1])}: {len(labels)} requirements. "
          f"Fix each wrong 'expected', then run: python -m scripts.eval --jd {jd_name}")


def _score(path: Path, evidence, llm, totals: Counter) -> None:
    spec = json.loads(path.read_text())
    expected = {normalize_skill(item["skill"]): item["expected"] for item in spec["labels"]}
    bad = sorted({v for v in expected.values() if v not in ALLOWED})
    if bad:
        sys.exit(f"{path.name}: unknown expected values {bad}; allowed: {sorted(ALLOWED)}")

    try:
        reqs, result = _run(spec["jd"], evidence, llm)
    except LLMError as e:
        print(f"== {spec['jd']}  FAILED: {e}\n")
        return
    by_req = {r.id: r for r in reqs.requirements}
    got = {by_req[m.requirement_id].canonical_skill: _answer(by_req[m.requirement_id], m.bucket.value)
           for m in result.matches}

    should_exist = {k: v for k, v in expected.items() if v != "not_a_requirement"}
    labeled = [k for k in should_exist if k in got]
    wrong = [(k, should_exist[k], got[k]) for k in labeled if got[k] != should_exist[k]]
    missing = [k for k in should_exist if k not in got]
    false_reqs = [k for k, v in expected.items() if v == "not_a_requirement" and k in got]
    extra = [k for k in got if k not in expected]
    correct = len(labeled) - len(wrong)

    print(f"== {spec['jd']}  {_pct(correct, len(labeled))} correct ({correct}/{len(labeled)})")
    for skill, want, have in wrong:
        print(f"   WRONG    {skill:<38} expected {want:<16} got {have}")
    for skill in missing:
        print(f"   MISSING  {skill:<38} expected {should_exist[skill]} (not extracted, or named differently)")
    for skill in false_reqs:
        print(f"   NOT REQ  {skill:<38} extracted, but labeled not_a_requirement")
    for skill in extra:
        print(f"   UNLABELED {skill:<37} got {got[skill]} (add it to the labels file)")
    print()
    totals.update(correct=correct, labeled=len(labeled), missing=len(missing), extra=len(extra))


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "n/a"


def _resume(name: str | None) -> Path:
    if name:
        return FIXTURES / "resumes" / name
    resumes = sorted((FIXTURES / "resumes").glob("*.txt"))
    if not resumes:
        sys.exit("Need a resume in tests/fixtures/resumes/")
    return resumes[0]


def _llm():
    s = get_settings()
    return GeminiClient(s.gemini_api_key.get_secret_value(), s.gemini_model, s.llm_timeout_seconds)


def _evidence(resume_path: Path, llm) -> EvidenceExtraction:
    try:
        return extract_evidence(ExtractEvidenceInput(resume_text=redact_resume(resume_path.read_text(encoding="utf-8")).text), llm)
    except LLMError as e:
        sys.exit(f"evidence extraction FAILED: {e}")


if __name__ == "__main__":
    main()
