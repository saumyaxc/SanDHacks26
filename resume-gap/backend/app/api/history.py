from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.base import AnalysisRepository
from app.dependencies import get_repo
from app.domain.schemas import AnalysisResult, AnalysisSummary, GapRanking
from app.services.gap_ranking import rank_gaps

router = APIRouter()


@router.get("/sessions/{session_id}/analyses", response_model=list[AnalysisSummary])
def list_analyses(
    session_id: str,
    limit: int = Query(50, ge=1, le=200),
    repo: AnalysisRepository = Depends(get_repo),
) -> list[AnalysisSummary]:
    """Newest first. An unknown session is just an empty history."""
    return [AnalysisSummary.from_result(r) for r in repo.list_for_session(session_id, limit)]


@router.get("/sessions/{session_id}/gaps", response_model=GapRanking)
def ranked_gaps(session_id: str, repo: AnalysisRepository = Depends(get_repo)) -> GapRanking:
    """Skill gaps across every job this session analyzed, most worth learning first."""
    return rank_gaps(repo.list_for_session(session_id, limit=200))


@router.get("/analyses/{analysis_id}", response_model=AnalysisResult)
def get_analysis(analysis_id: str, repo: AnalysisRepository = Depends(get_repo)) -> AnalysisResult:
    # No auth by design: ids are random 128-bit uuids, so knowing one is the access check.
    result = repo.get(analysis_id)
    if result is None:
        raise HTTPException(404, "analysis not found")
    return result
