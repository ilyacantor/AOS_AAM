"""
Candidates Router — CRUD and match/defer operations for connection candidates.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..db import (
    get_candidate,
    update_candidate_deferred,
)
from ..services.matching_service import match_candidate as match_candidate_service

router = APIRouter(prefix="/api/candidates", tags=["Candidates"])


class MatchRequest(BaseModel):
    pipe_id: Optional[str] = None


class DeferRequest(BaseModel):
    reason: str


@router.post("/{candidate_id}/match")
async def match_candidate(candidate_id: str, request: MatchRequest):
    """
    Attempt to match candidate to a pipe.

    Enforces AOD governance:
    - If execution_allowed=False, blocks auto-matching
    - If action_type="inventory_only", blocks auto-matching
    - Respects blocking_findings from AOD
    """
    try:
        result = match_candidate_service(candidate_id, request.pipe_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{candidate_id}/defer")
async def defer_candidate(candidate_id: str, request: DeferRequest):
    """Defer a candidate with a reason."""
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    updated = update_candidate_deferred(candidate_id, request.reason)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to defer candidate")

    return {
        "candidate_id": candidate_id,
        "status": "deferred",
        "deferred_reason": request.reason,
    }
