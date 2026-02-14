"""
TEE request operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# TEE REQUEST OPERATIONS (v1 Practical Interface)
# ============================================================================

def list_tee_requests(status: Optional[str] = None) -> list[dict]:
    """List tee requests with optional status filter"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if status:
        cursor.execute(
            "SELECT * FROM tee_requests WHERE status = ? ORDER BY requested_at DESC",
            (status,)
        )
    else:
        cursor.execute("SELECT * FROM tee_requests ORDER BY requested_at DESC")
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "tee_id": row["tee_id"],
        "pipe_id": row["pipe_id"],
        "target_system": row["target_system"],
        "tee_type": row["tee_type"],
        "configuration": json.loads(row["configuration"]) if row["configuration"] else {},
        "status": row["status"],
        "requested_at": row["requested_at"],
        "approved_at": row["approved_at"],
        "verified_at": row["verified_at"]
    } for row in rows]


def get_drift_event(drift_id: str) -> Optional[dict]:
    """Get a drift event by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drift_events WHERE drift_id = ?", (drift_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return _row_to_drift_event(row)
    return None


def get_tee_request(tee_id: str) -> Optional[dict]:
    """Get a single TEE request by ID"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tee_requests WHERE tee_id = ?", (tee_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "tee_id": row["tee_id"],
            "pipe_id": row["pipe_id"],
            "target_system": row["target_system"],
            "tee_type": row["tee_type"],
            "configuration": json.loads(row["configuration"]) if row["configuration"] else {},
            "status": row["status"],
            "requested_at": row["requested_at"],
            "approved_at": row["approved_at"],
            "verified_at": row["verified_at"]
        }
    return None


def create_tee_request(tee_data: dict) -> dict:
    """Create a new tee request"""
    conn = get_connection()
    cursor = conn.cursor()
    
    tee_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO tee_requests (
            tee_id, pipe_id, target_system, tee_type, configuration, status, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        tee_id,
        tee_data["pipe_id"],
        tee_data["target_system"],
        tee_data.get("tee_type", "api_proxy"),
        json.dumps(tee_data.get("configuration", {})),
        "requested",
        now
    ))
    
    conn.commit()
    conn.close()
    
    return {
        "tee_id": tee_id,
        "pipe_id": tee_data["pipe_id"],
        "target_system": tee_data["target_system"],
        "tee_type": tee_data.get("tee_type", "api_proxy"),
        "configuration": tee_data.get("configuration", {}),
        "status": "requested",
        "requested_at": now,
        "approved_at": None,
        "verified_at": None
    }


def update_tee_request_status(tee_id: str, status: str) -> Optional[dict]:
    """Update tee request status (requested, approved, verified)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    if status == "approved":
        cursor.execute("""
            UPDATE tee_requests SET status = ?, approved_at = ? WHERE tee_id = ?
        """, (status, now, tee_id))
    elif status == "verified":
        cursor.execute("""
            UPDATE tee_requests SET status = ?, verified_at = ? WHERE tee_id = ?
        """, (status, now, tee_id))
    else:
        cursor.execute("""
            UPDATE tee_requests SET status = ? WHERE tee_id = ?
        """, (status, tee_id))
    
    affected = cursor.rowcount
    conn.commit()
    
    if affected > 0:
        cursor.execute("SELECT * FROM tee_requests WHERE tee_id = ?", (tee_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "tee_id": row["tee_id"],
                "pipe_id": row["pipe_id"],
                "target_system": row["target_system"],
                "tee_type": row["tee_type"],
                "configuration": json.loads(row["configuration"]) if row["configuration"] else {},
                "status": row["status"],
                "requested_at": row["requested_at"],
                "approved_at": row["approved_at"],
                "verified_at": row["verified_at"]
            }
    
    conn.close()
    return None


