from datetime import UTC, datetime, timedelta

from app.domain.schemas import (
    AnalysisResult,
    EvidenceExtraction,
    GapRecommendations,
    MatchResult,
    RequirementsExtraction,
    RewriteSuggestions,
)
from app.services.gap_ranking import rank_gaps

_EV = {"id": "ev-1", "section": "experience", "line": "Built things", "skills": []}
_T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _result(
    rid: str,
    role: str,
    rows: list[tuple],
    days: int = 0,
    company: str | None = "Acme",
) -> AnalysisResult:
    """rows: (skill, bucket, priority="required", category="technology", satisfied_by=None)."""
    reqs, matches = [], []
    for i, row in enumerate(rows, start=1):
        defaults = ("required", "technology", None)
        skill, bucket, *rest = row
        priority, category, satisfied_by = (*rest, *defaults[len(rest) :])
        req_id = f"req-{i}"
        reqs.append(
            {
                "id": req_id,
                "skill": skill,
                "canonical_skill": skill,
                "category": category,
                "priority": priority,
                "jd_quote": "q",
            }
        )
        has_ev = bucket != "gap"
        matches.append(
            {
                "requirement_id": req_id,
                "bucket": bucket,
                "evidence_id": "ev-1" if has_ev else None,
                "evidence_quote": "Built things" if has_ev else None,
                "rationale": "r",
                "satisfied_by": satisfied_by,
            }
        )
    return AnalysisResult(
        id=rid,
        session_id="s",
        created_at=_T0 + timedelta(days=days),
        requirements=RequirementsExtraction(role_title=role, company=company, requirements=reqs),
        evidence=EvidenceExtraction(items=[_EV]),
        matches=MatchResult(matches=matches),
        rewrites=RewriteSuggestions(rewrites=[]),
        recommendations=GapRecommendations(recommendations=[]),
    )


def test_ranks_by_weighted_score_across_jobs():
    results = [
        _result("a", "Job A", [("docker", "gap"), ("aws", "gap", "preferred")]),
        _result("b", "Job B", [("docker", "gap"), ("aws", "transferable")], days=1),
        _result("c", "Job C", [("kubernetes", "gap", "preferred")], days=2),
    ]
    ranking = rank_gaps(results)
    # docker 2+2=4; aws 1 + 2*0.5=2; kubernetes 1
    assert [(g.canonical_skill, g.score, g.job_count) for g in ranking.gaps] == [
        ("docker", 4.0, 2),
        ("aws", 2.0, 2),
        ("kubernetes", 1.0, 1),
    ]
    assert ranking.analysis_count == 3
    assert [o.analysis_id for o in ranking.gaps[0].occurrences] == ["b", "a"]  # newest first


def test_skill_fixed_in_newest_mention_drops_out():
    results = [
        _result("old", "Job A", [("docker", "gap")]),
        _result("new", "Job B", [("docker", "covered")], days=1),
    ]
    assert rank_gaps(results).gaps == []


def test_skill_that_regressed_is_still_ranked():
    results = [
        _result("old", "Job A", [("docker", "covered")]),
        _result("new", "Job B", [("docker", "gap")], days=1),
    ]
    assert [g.canonical_skill for g in rank_gaps(results).gaps] == ["docker"]


def test_reanalyzed_job_counts_once_using_newest():
    results = [
        _result("v1", "Job A", [("docker", "gap"), ("aws", "gap")]),
        _result("v2", " job a ", [("docker", "gap"), ("aws", "covered")], days=1),
    ]
    ranking = rank_gaps(results)
    assert ranking.analysis_count == 1
    assert [(g.canonical_skill, g.job_count) for g in ranking.gaps] == [("docker", 1)]


def test_skips_credentials_and_group_satisfied_members():
    results = [
        _result(
            "a",
            "Job A",
            [
                ("computer science degree", "gap", "required", "credential"),
                ("typescript", "gap", "required", "technology", "req-3"),
                ("python", "covered"),
            ],
        )
    ]
    assert rank_gaps(results).gaps == []


def test_display_name_is_most_common_spelling():
    a = _result("a", "Job A", [("kubernetes", "gap")])
    b = _result("b", "Job B", [("kubernetes", "gap")], days=1)
    c = _result("c", "Job C", [("kubernetes", "gap")], days=2)
    for r, raw in ((a, "K8s"), (b, "Kubernetes"), (c, "Kubernetes")):
        r.requirements.requirements[0].skill = raw
    assert rank_gaps([a, b, c]).gaps[0].skill == "Kubernetes"
