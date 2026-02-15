"""
Candidate match/defer operations (v1)
"""
from datetime import datetime
from typing import Optional

from . import supabase_client as sb
from .candidates import _row_to_candidate


def update_candidate_match(candidate_id: str, pipe_id: str, score: float, reason: str,
                           fabric_plane: str = None) -> Optional[dict]:
    """Update candidate with match information and propagate plane linkage.

    When a candidate matches a pipe, the pipe's fabric_plane (e.g. API_GATEWAY)
    is written back to connected_via_plane so the topology view can resolve it.
    Also links fabric_plane_id to the corresponding fabric_planes row (if one
    exists for this plane type) so DCL export and JOIN-based queries work.
    """
    now = datetime.utcnow().isoformat()

    fabric_plane_id = None
    if fabric_plane and fabric_plane != "UNMAPPED":
        fp_row = sb.select(
            "fabric_planes",
            filters={"plane_type": fabric_plane},
            limit=1,
            single=True,
        )
        if fp_row:
            fabric_plane_id = fp_row.get("plane_id")

    update_data = {
        "matched_pipe_id": pipe_id,
        "match_score": score,
        "match_reason": reason,
        "status": "connected",
        "updated_at": now,
    }
    if fabric_plane:
        update_data["connected_via_plane"] = fabric_plane
    if fabric_plane_id:
        update_data["fabric_plane_id"] = fabric_plane_id

    sb.update(
        "connection_candidates",
        update_data,
        filters={"candidate_id": candidate_id},
    )

    row = sb.select(
        "connection_candidates",
        filters={"candidate_id": candidate_id},
        single=True,
    )
    if row:
        return _row_to_candidate(row)
    return None


def update_candidate_deferred(candidate_id: str, reason: str) -> Optional[dict]:
    """Update candidate as deferred with reason"""
    now = datetime.utcnow().isoformat()

    sb.update(
        "connection_candidates",
        {
            "deferred_reason": reason,
            "status": "deferred",
            "updated_at": now,
        },
        filters={"candidate_id": candidate_id},
    )

    row = sb.select(
        "connection_candidates",
        filters={"candidate_id": candidate_id},
        single=True,
    )
    if row:
        return _row_to_candidate(row)
    return None
