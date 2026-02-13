"""
TEE Router — tee request management endpoints.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from ..db import (
    get_candidate,
    get_pipe_or_candidate,
    create_tee_request,
    list_tee_requests,
)
from ..services.tee_service import validate_tee_transition

router = APIRouter(prefix="/api/tee", tags=["Tee Requests"])


class TeeRequestCreate(BaseModel):
    pipe_id: Optional[str] = None
    candidate_id: Optional[str] = None
    target_system: str
    tee_type: str = "api_proxy"
    configuration: dict = {}
    notes: Optional[str] = None


class TeeVerificationRequest(BaseModel):
    status: str
    verification_method: Optional[str] = None
    verification_evidence: Optional[str] = None
    verified_by: Optional[str] = None


@router.post("/requests")
async def create_tee_request_endpoint(request: TeeRequestCreate):
    """Create a new tee request."""
    pipe_id = request.pipe_id

    if request.candidate_id and not pipe_id:
        candidate = get_candidate(request.candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if candidate.get("matched_pipe_id"):
            pipe_id = candidate["matched_pipe_id"]
        else:
            raise HTTPException(
                status_code=400,
                detail="Candidate has no matched pipe. Provide pipe_id or match the candidate first.",
            )

    if not pipe_id:
        raise HTTPException(status_code=400, detail="Either pipe_id or a matched candidate_id is required")

    pipe = get_pipe_or_candidate(pipe_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipe not found")

    tee_data = {
        "pipe_id": pipe_id,
        "target_system": request.target_system,
        "tee_type": request.tee_type,
        "configuration": request.configuration,
    }
    result = create_tee_request(tee_data)
    return result


@router.get("/requests")
async def get_tee_requests(status: Optional[str] = Query(None)):
    """List tee requests."""
    requests = list_tee_requests(status=status)
    return {"tee_requests": requests, "count": len(requests)}


@router.post("/requests/{tee_id}/status")
async def update_tee_status(tee_id: str, request: TeeVerificationRequest):
    """
    Update TEE request status with workflow enforcement.

    Workflow: requested -> approved -> verified
    """
    try:
        updated, tee_req = validate_tee_transition(
            tee_id, request.status, request.verification_method
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    response = dict(updated)
    if request.status == "verified":
        pipe = get_pipe_or_candidate(tee_req["pipe_id"])
        response["verification"] = {
            "method": request.verification_method,
            "evidence": request.verification_evidence,
            "verified_by": request.verified_by,
            "pipe_status": "active" if pipe else "unknown",
        }

    return response
