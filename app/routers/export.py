"""
Export Router — DCL export, push tracking, and stats endpoints.
"""
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional
from datetime import datetime

from ..db import list_declared_pipes, get_pipe_stats, list_candidates, record_dcl_push, list_dcl_pushes, get_dcl_push

router = APIRouter(tags=["Export"])


@router.get("/api/export/dcl/declared-pipes")
async def export_for_dcl(aod_run_id: Optional[str] = Query(None)):
    """Export all declared pipes in DCL format. Reads from the declared_pipes
    table which is populated during inference/matching."""
    pipes = list_declared_pipes()
    if aod_run_id:
        pipes = [p for p in pipes if p.get("provenance", {}).get("aod_run_id") == aod_run_id]
    return {
        "export_version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "pipe_count": len(pipes),
        "pipes": pipes,
    }


@router.post("/api/export/dcl/push")
async def push_to_dcl(request: Request):
    """
    Export pipes to DCL and record the push for reconciliation.
    Returns the export payload and a push_id for tracking.

    Optional body: {"aod_run_id": "...", "notes": "..."}
    """
    body = {}
    raw = await request.body()
    if raw:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="Request body is not valid JSON")

    aod_run_id = body.get("aod_run_id")
    notes = body.get("notes")

    pipes = list_declared_pipes()
    if aod_run_id:
        pipes = [p for p in pipes if p.get("provenance", {}).get("aod_run_id") == aod_run_id]

    export_payload = {
        "export_version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "pipe_count": len(pipes),
        "pipes": pipes,
    }

    push_record = record_dcl_push(
        pipe_count=len(pipes),
        payload=export_payload,
        aod_run_id=aod_run_id,
        notes=notes,
    )

    return {
        "push": push_record,
        "export": export_payload,
    }


@router.get("/api/export/dcl/pushes")
async def get_push_history(limit: int = Query(25)):
    """List recent DCL push records (without full payload)."""
    return list_dcl_pushes(limit=limit)


@router.get("/api/export/dcl/pushes/{push_id}")
async def get_push_detail(push_id: str):
    """Get a specific DCL push including the full payload that was sent."""
    result = get_dcl_push(push_id)
    if not result:
        raise HTTPException(status_code=404, detail="Push not found")
    return result


@router.get("/api/export/dcl/pushes/{push_id}/download")
async def download_push_payload(push_id: str):
    """Download the full payload from a specific DCL push as a JSON file."""
    import json as _json
    from starlette.responses import Response

    result = get_dcl_push(push_id)
    if not result:
        raise HTTPException(status_code=404, detail="Push not found")
    filename = f"dcl_push_{push_id[:8]}.json"
    return Response(
        content=_json.dumps(result["payload"], indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/dcl/export-pipes", tags=["DCL Export"])
async def export_pipes_for_dcl(aod_run_id: Optional[str] = Query(None)):
    """Export pipe definitions grouped by fabric plane for DCL consumption.
    
    Note: Most pipes may be UNMAPPED if no fabric planes are assigned.
    Use /api/export/dcl/declared-pipes for the flat canonical export.
    """
    from ..dcl_export import build_dcl_export

    export_data = build_dcl_export(aod_run_id=aod_run_id)
    return export_data.model_dump()


@router.get("/api/stats", tags=["Stats"])
async def get_stats():
    """Get statistics about pipes by fabric_plane and modality."""
    stats = get_pipe_stats()
    candidates = list_candidates()
    stats["total_candidates"] = len(candidates)
    stats["candidates_by_status"] = {}
    for c in candidates:
        status = c.get("status", "new")
        stats["candidates_by_status"][status] = stats["candidates_by_status"].get(status, 0) + 1
    return stats
