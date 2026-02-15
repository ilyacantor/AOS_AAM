"""
Candidate CRUD operations
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb

# ============================================================================
# CANDIDATE OPERATIONS
# ============================================================================

def create_candidate(candidate_data: dict) -> dict:
    """Create a new connection candidate"""
    candidate_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    execution_allowed = candidate_data.get("execution_allowed")
    if isinstance(execution_allowed, bool):
        pass
    elif execution_allowed is not None:
        execution_allowed = bool(execution_allowed)

    asset_key = candidate_data["asset_key"]
    sb.delete("connection_candidates", filters={"asset_key": asset_key})

    row = {
        "candidate_id": candidate_id,
        "asset_key": candidate_data["asset_key"],
        "vendor_name": candidate_data["vendor_name"],
        "display_name": candidate_data["display_name"],
        "category": candidate_data["category"],
        "governance_status": candidate_data.get("governance_status"),
        "findings": json.dumps(candidate_data.get("findings", [])),
        "sor_tagging": candidate_data.get("sor_tagging"),
        "evidence_refs": json.dumps(candidate_data.get("evidence_refs", [])),
        "signals_summary": candidate_data.get("signals_summary"),
        "known_endpoints": json.dumps(candidate_data.get("known_endpoints", [])),
        "preferred_modality": candidate_data.get("preferred_modality"),
        "priority_score": candidate_data.get("priority_score"),
        "status": candidate_data.get("status") or "new",
        "execution_allowed": execution_allowed,
        "action_type": candidate_data.get("action_type"),
        "blocking_findings": json.dumps(candidate_data.get("blocking_findings", [])),
        "connected_via_plane": candidate_data.get("connected_via_plane"),
        "aod_run_id": candidate_data.get("aod_run_id"),
        "aod_asset_id": candidate_data.get("aod_asset_id"),
        "fabric_plane_id": candidate_data.get("fabric_plane_id"),
        "created_at": now,
        "updated_at": now,
    }

    sb.insert("connection_candidates", row)

    return {
        "candidate_id": candidate_id,
        "status": "connected",
        "execution_allowed": execution_allowed,
        "action_type": candidate_data.get("action_type"),
        "created_at": now,
        "updated_at": now,
    }


def get_candidate(candidate_id: str) -> Optional[dict]:
    """Get a candidate by ID"""
    row = sb.select(
        "connection_candidates",
        filters={"candidate_id": candidate_id},
        single=True,
    )
    if row:
        return _row_to_candidate(row)
    return None


def list_candidates(status: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """List candidates with optional status filter, sorted by category"""
    filters = {}
    if status:
        filters["status"] = status

    rows = sb.select(
        "connection_candidates",
        filters=filters if filters else None,
        order="category.asc,created_at.desc",
        limit=limit,
    )

    return [_row_to_candidate(row) for row in rows]


def update_candidate_status(candidate_id: str, status: str) -> bool:
    """Update candidate status"""
    result = sb.update(
        "connection_candidates",
        {"status": status, "updated_at": datetime.utcnow().isoformat()},
        filters={"candidate_id": candidate_id},
    )
    return len(result) > 0


def _row_to_candidate(row) -> dict:
    """Convert database row to candidate dict"""
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
        "updated_at": row["updated_at"],
    }

    result["matched_pipe_id"] = row.get("matched_pipe_id")
    result["match_score"] = row.get("match_score")
    result["match_reason"] = row.get("match_reason")
    result["deferred_reason"] = row.get("deferred_reason")

    result["execution_allowed"] = row.get("execution_allowed")
    result["action_type"] = row.get("action_type")
    result["blocking_findings"] = json.loads(row["blocking_findings"]) if row.get("blocking_findings") else []
    result["connected_via_plane"] = row.get("connected_via_plane")
    result["aod_run_id"] = row.get("aod_run_id")
    result["aod_asset_id"] = row.get("aod_asset_id")
    result["fabric_plane_id"] = row.get("fabric_plane_id")

    return result
