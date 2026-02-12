"""
Drift event operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# DRIFT OPERATIONS
# ============================================================================

def create_drift_event(pipe_id: str, drift_type: str, old_value: str, new_value: str, details: Optional[dict] = None) -> str:
    """Create a drift event"""
    conn = get_connection()
    cursor = conn.cursor()
    
    drift_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO drift_events (drift_id, pipe_id, drift_type, old_value, new_value, details, detected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (drift_id, pipe_id, drift_type, old_value, new_value, json.dumps(details) if details else None, now))
    
    conn.commit()
    conn.close()
    
    return drift_id


def _row_to_drift_event(row) -> dict:
    """Convert database row to drift event dict"""
    result = {
        "drift_id": row["drift_id"],
        "pipe_id": row["pipe_id"],
        "drift_type": row["drift_type"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "details": json.loads(row["details"]) if row["details"] else None,
        "detected_at": row["detected_at"]
    }
    keys = row.keys()
    if "severity" in keys:
        result["severity"] = row["severity"] or "medium"
    if "status" in keys:
        result["status"] = row["status"] or "open"
    if "acknowledged_at" in keys:
        result["acknowledged_at"] = row["acknowledged_at"]
    if "acknowledged_by" in keys:
        result["acknowledged_by"] = row["acknowledged_by"]
    if "suppressed_at" in keys:
        result["suppressed_at"] = row["suppressed_at"]
    if "suppressed_by" in keys:
        result["suppressed_by"] = row["suppressed_by"]
    if "notes" in keys:
        result["notes"] = row["notes"]
    return result


def get_drift_events(pipe_id: str) -> list[dict]:
    """Get drift events for a pipe"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM drift_events WHERE pipe_id = ? ORDER BY detected_at DESC",
        (pipe_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_drift_event(row) for row in rows]


def list_all_drift_events(limit: Optional[int] = None) -> list[dict]:
    """List all drift events"""
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM drift_events ORDER BY detected_at DESC"
    if limit:
        query += f" LIMIT {limit}"
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_drift_event(row) for row in rows]


