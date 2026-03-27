"""
AOD handoff log operations
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def create_handoff_log(handoff_data: dict) -> dict:
    """Create a log entry for an AOD handoff"""
    handoff_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    data = {
        "handoff_id": handoff_id,
        "aod_run_id": handoff_data["aod_run_id"],
        "tenant_id": handoff_data.get("tenant_id"),
        "entity_id": handoff_data.get("entity_id"),
        "snapshot_name": handoff_data.get("snapshot_name"),
        "candidates_received": handoff_data["candidates_received"],
        "candidates_accepted": handoff_data["candidates_accepted"],
        "candidates_rejected": handoff_data["candidates_rejected"],
        "rejected_reasons": json.dumps(handoff_data.get("rejected_reasons", [])),
        "policy_version": handoff_data.get("policy_version"),
        "handoff_timestamp": handoff_data.get("handoff_timestamp", now),
        "processed_at": now,
        "aod_fabric_planes": json.dumps(handoff_data.get("aod_fabric_planes", [])),
        "aod_sor_vendors": json.dumps(handoff_data.get("aod_sor_vendors", [])),
        "reconciliation_manifest": json.dumps(handoff_data.get("reconciliation_manifest")) if handoff_data.get("reconciliation_manifest") else None,
    }

    sb.insert("aod_handoff_log", data)

    return {
        "handoff_id": handoff_id,
        "aod_run_id": handoff_data["aod_run_id"],
        "snapshot_name": handoff_data.get("snapshot_name"),
        "processed_at": now,
    }


def get_handoff_log(handoff_id: str) -> Optional[dict]:
    """Get a handoff log entry by ID"""
    row = sb.select(
        "aod_handoff_log",
        filters={"handoff_id": handoff_id},
        single=True,
    )

    if row:
        return {
            "handoff_id": row["handoff_id"],
            "aod_run_id": row["aod_run_id"],
            "tenant_id": row.get("tenant_id"),
            "entity_id": row.get("entity_id"),
            "snapshot_name": row.get("snapshot_name"),
            "candidates_received": row["candidates_received"],
            "candidates_accepted": row["candidates_accepted"],
            "candidates_rejected": row["candidates_rejected"],
            "rejected_reasons": json.loads(row["rejected_reasons"]) if row.get("rejected_reasons") else [],
            "policy_version": row.get("policy_version"),
            "handoff_timestamp": row.get("handoff_timestamp"),
            "processed_at": row.get("processed_at"),
        }
    return None


def list_handoff_logs(aod_run_id: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """List handoff logs with optional run_id filter"""
    filters = {}
    if aod_run_id:
        filters["aod_run_id"] = aod_run_id

    rows = sb.select(
        "aod_handoff_log",
        filters=filters if filters else None,
        order="processed_at.desc",
        limit=limit,
    )

    return [{
        "handoff_id": row["handoff_id"],
        "aod_run_id": row["aod_run_id"],
        "tenant_id": row.get("tenant_id"),
        "entity_id": row.get("entity_id"),
        "snapshot_name": row.get("snapshot_name"),
        "candidates_received": row["candidates_received"],
        "candidates_accepted": row["candidates_accepted"],
        "candidates_rejected": row["candidates_rejected"],
        "policy_version": row.get("policy_version"),
        "handoff_timestamp": row.get("handoff_timestamp"),
        "processed_at": row.get("processed_at"),
    } for row in rows]
