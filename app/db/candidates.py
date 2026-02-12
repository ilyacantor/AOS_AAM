"""
Candidate CRUD operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# CANDIDATE OPERATIONS
# ============================================================================

def create_candidate(candidate_data: dict) -> dict:
    """Create a new connection candidate"""
    conn = get_connection()
    cursor = conn.cursor()

    candidate_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # Handle AOD execution_allowed (convert bool to int for SQLite)
    # Default None — AOD must explicitly grant permission, not permissive-by-default
    execution_allowed = candidate_data.get("execution_allowed")
    if execution_allowed is None:
        execution_allowed = None  # stored as NULL — operator must review
    elif isinstance(execution_allowed, bool):
        execution_allowed = 1 if execution_allowed else 0

    # Deduplication: Delete existing candidate with same asset_key to prevent duplicates
    asset_key = candidate_data["asset_key"]
    cursor.execute("DELETE FROM connection_candidates WHERE asset_key = ?", (asset_key,))

    cursor.execute("""
        INSERT INTO connection_candidates (
            candidate_id, asset_key, vendor_name, display_name, category,
            governance_status, findings, sor_tagging, evidence_refs,
            signals_summary, known_endpoints, preferred_modality, priority_score,
            status, execution_allowed, action_type, blocking_findings,
            connected_via_plane, aod_run_id, aod_asset_id, fabric_plane_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        candidate_id,
        candidate_data["asset_key"],
        candidate_data["vendor_name"],
        candidate_data["display_name"],
        candidate_data["category"],
        candidate_data.get("governance_status"),
        json.dumps(candidate_data.get("findings", [])),
        candidate_data.get("sor_tagging"),
        json.dumps(candidate_data.get("evidence_refs", [])),
        candidate_data.get("signals_summary"),
        json.dumps(candidate_data.get("known_endpoints", [])),
        candidate_data.get("preferred_modality"),
        candidate_data.get("priority_score"),
        candidate_data.get("status", "new"),
        execution_allowed,
        candidate_data.get("action_type"),
        json.dumps(candidate_data.get("blocking_findings", [])),
        candidate_data.get("connected_via_plane"),
        candidate_data.get("aod_run_id"),
        candidate_data.get("aod_asset_id"),
        candidate_data.get("fabric_plane_id"),
        now,
        now
    ))

    conn.commit()
    conn.close()

    return {
        "candidate_id": candidate_id,
        "status": "connected",
        "execution_allowed": bool(execution_allowed) if execution_allowed is not None else None,
        "action_type": candidate_data.get("action_type"),
        "created_at": now,
        "updated_at": now
    }


def get_candidate(candidate_id: str) -> Optional[dict]:
    """Get a candidate by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM connection_candidates WHERE candidate_id = ?", (candidate_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return _row_to_candidate(row)
    return None


def list_candidates(status: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """List candidates with optional status filter, sorted by category"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if status:
        query = "SELECT * FROM connection_candidates WHERE status = ? ORDER BY category ASC, created_at DESC"
        params = [status]
    else:
        query = "SELECT * FROM connection_candidates ORDER BY category ASC, created_at DESC"
        params = []
    
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_candidate(row) for row in rows]


def update_candidate_status(candidate_id: str, status: str) -> bool:
    """Update candidate status"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE connection_candidates SET status = ?, updated_at = ? WHERE candidate_id = ?",
        (status, datetime.utcnow().isoformat(), candidate_id)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def _row_to_candidate(row) -> dict:
    """Convert database row to candidate dict"""
    keys = row.keys()

    result = {
        "candidate_id": row["candidate_id"],
        "asset_key": row["asset_key"],
        "vendor_name": row["vendor_name"],
        "display_name": row["display_name"],
        "category": row["category"],
        "governance_status": row["governance_status"],
        "findings": json.loads(row["findings"]) if row["findings"] else [],
        "sor_tagging": row["sor_tagging"],
        "evidence_refs": json.loads(row["evidence_refs"]) if row["evidence_refs"] else [],
        "signals_summary": row["signals_summary"],
        "known_endpoints": json.loads(row["known_endpoints"]) if row["known_endpoints"] else [],
        "preferred_modality": row["preferred_modality"],
        "priority_score": row["priority_score"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }

    # Match/defer fields
    if "matched_pipe_id" in keys:
        result["matched_pipe_id"] = row["matched_pipe_id"]
    if "match_score" in keys:
        result["match_score"] = row["match_score"]
    if "match_reason" in keys:
        result["match_reason"] = row["match_reason"]
    if "deferred_reason" in keys:
        result["deferred_reason"] = row["deferred_reason"]

    # AOD Handoff fields
    if "execution_allowed" in keys:
        result["execution_allowed"] = bool(row["execution_allowed"]) if row["execution_allowed"] is not None else None
    if "action_type" in keys:
        result["action_type"] = row["action_type"]
    if "blocking_findings" in keys:
        result["blocking_findings"] = json.loads(row["blocking_findings"]) if row["blocking_findings"] else []
    if "connected_via_plane" in keys:
        result["connected_via_plane"] = row["connected_via_plane"]
    if "aod_run_id" in keys:
        result["aod_run_id"] = row["aod_run_id"]
    if "aod_asset_id" in keys:
        result["aod_asset_id"] = row["aod_asset_id"]
    if "fabric_plane_id" in keys:
        result["fabric_plane_id"] = row["fabric_plane_id"]

    return result


