"""
Export Router — DCL export and stats endpoints.
"""
from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime

from ..db import list_pipes, get_pipe_stats, list_candidates

router = APIRouter(tags=["Export"])


@router.get("/api/export/dcl/declared-pipes")
async def export_for_dcl():
    """Export all pipes in DCL format."""
    pipes = list_pipes()
    return {
        "export_version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "pipe_count": len(pipes),
        "pipes": pipes,
    }


@router.get("/api/dcl/export-pipes", tags=["DCL Export"])
async def export_pipes_for_dcl(aod_run_id: Optional[str] = Query(None)):
    """Export pipe definitions grouped by fabric plane for DCL consumption."""
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
