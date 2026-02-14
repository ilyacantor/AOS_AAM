"""
Candidate match/defer operations (v1)
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection
from .candidates import _row_to_candidate

# ============================================================================
# CANDIDATE MATCH OPERATIONS (v1 Practical Interface)
# ============================================================================

def update_candidate_match(candidate_id: str, pipe_id: str, score: float, reason: str,
                           fabric_plane: str = None) -> Optional[dict]:
    """Update candidate with match information and propagate plane linkage.

    When a candidate matches a pipe, the pipe's fabric_plane (e.g. API_GATEWAY)
    is written back to connected_via_plane so the topology view can resolve it.
    Also links fabric_plane_id to the corresponding fabric_planes row (if one
    exists for this plane type) so DCL export and JOIN-based queries work.
    """
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.utcnow().isoformat()

    # Look up matching fabric_planes row by plane_type so we can set
    # fabric_plane_id (the FK used by DCL export and topology JOINs).
    fabric_plane_id = None
    if fabric_plane and fabric_plane != "UNMAPPED":
        cursor.execute(
            "SELECT plane_id FROM fabric_planes WHERE plane_type = ? LIMIT 1",
            (fabric_plane,)
        )
        fp_row = cursor.fetchone()
        if fp_row:
            fabric_plane_id = fp_row[0]

    cursor.execute("""
        UPDATE connection_candidates
        SET matched_pipe_id = ?, match_score = ?, match_reason = ?,
            status = 'connected', updated_at = ?,
            connected_via_plane = COALESCE(?, connected_via_plane),
            fabric_plane_id = COALESCE(?, fabric_plane_id)
        WHERE candidate_id = ?
    """, (pipe_id, score, reason, now, fabric_plane, fabric_plane_id, candidate_id))
    
    affected = cursor.rowcount
    conn.commit()
    
    if affected > 0:
        cursor.execute("SELECT * FROM connection_candidates WHERE candidate_id = ?", (candidate_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return _row_to_candidate(row)
    
    conn.close()
    return None


def update_candidate_deferred(candidate_id: str, reason: str) -> Optional[dict]:
    """Update candidate as deferred with reason"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        UPDATE connection_candidates 
        SET deferred_reason = ?, status = 'deferred', updated_at = ?
        WHERE candidate_id = ?
    """, (reason, now, candidate_id))
    
    affected = cursor.rowcount
    conn.commit()
    
    if affected > 0:
        cursor.execute("SELECT * FROM connection_candidates WHERE candidate_id = ?", (candidate_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return _row_to_candidate(row)
    
    conn.close()
    return None


