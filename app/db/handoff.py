"""
AOD handoff log operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# AOD HANDOFF OPERATIONS
# ============================================================================

def create_handoff_log(handoff_data: dict) -> dict:
    """Create a log entry for an AOD handoff"""
    conn = get_connection()
    cursor = conn.cursor()

    handoff_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    cursor.execute("""
        INSERT INTO aod_handoff_log (
            handoff_id, aod_run_id, snapshot_name, candidates_received, candidates_accepted,
            candidates_rejected, rejected_reasons, policy_version,
            handoff_timestamp, processed_at, aod_fabric_planes, aod_sor_vendors
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        handoff_id,
        handoff_data["aod_run_id"],
        handoff_data.get("snapshot_name"),
        handoff_data["candidates_received"],
        handoff_data["candidates_accepted"],
        handoff_data["candidates_rejected"],
        json.dumps(handoff_data.get("rejected_reasons", [])),
        handoff_data.get("policy_version"),
        handoff_data.get("handoff_timestamp", now),
        now,
        json.dumps(handoff_data.get("aod_fabric_planes", [])),
        json.dumps(handoff_data.get("aod_sor_vendors", []))
    ))

    conn.commit()
    conn.close()

    return {
        "handoff_id": handoff_id,
        "aod_run_id": handoff_data["aod_run_id"],
        "snapshot_name": handoff_data.get("snapshot_name"),
        "processed_at": now
    }


def get_handoff_log(handoff_id: str) -> Optional[dict]:
    """Get a handoff log entry by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM aod_handoff_log WHERE handoff_id = ?", (handoff_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "handoff_id": row["handoff_id"],
            "aod_run_id": row["aod_run_id"],
            "snapshot_name": row["snapshot_name"] if "snapshot_name" in row.keys() else None,
            "candidates_received": row["candidates_received"],
            "candidates_accepted": row["candidates_accepted"],
            "candidates_rejected": row["candidates_rejected"],
            "rejected_reasons": json.loads(row["rejected_reasons"]) if row["rejected_reasons"] else [],
            "policy_version": row["policy_version"],
            "handoff_timestamp": row["handoff_timestamp"],
            "processed_at": row["processed_at"]
        }
    return None


def list_handoff_logs(aod_run_id: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """List handoff logs with optional run_id filter"""
    conn = get_connection()
    cursor = conn.cursor()

    if aod_run_id:
        query = "SELECT * FROM aod_handoff_log WHERE aod_run_id = ? ORDER BY processed_at DESC"
        params = [aod_run_id]
    else:
        query = "SELECT * FROM aod_handoff_log ORDER BY processed_at DESC"
        params = []
    
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [{
        "handoff_id": row["handoff_id"],
        "aod_run_id": row["aod_run_id"],
        "snapshot_name": row["snapshot_name"] if "snapshot_name" in row.keys() else None,
        "candidates_received": row["candidates_received"],
        "candidates_accepted": row["candidates_accepted"],
        "candidates_rejected": row["candidates_rejected"],
        "policy_version": row["policy_version"],
        "handoff_timestamp": row["handoff_timestamp"],
        "processed_at": row["processed_at"]
    } for row in rows]


