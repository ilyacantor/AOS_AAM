"""
DCL Push Tracking — records each export pushed to DCL for reconciliation.
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from .connection import get_connection


def init_dcl_pushes_table():
    """Create the dcl_pushes table if it doesn't exist."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dcl_pushes (
            push_id TEXT PRIMARY KEY,
            aod_run_id TEXT,
            pushed_at TEXT NOT NULL,
            pipe_count INTEGER NOT NULL DEFAULT 0,
            payload_hash TEXT,
            payload TEXT,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def record_dcl_push(
    pipe_count: int,
    payload: dict,
    aod_run_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Record a DCL push with full payload for later reconciliation."""
    import hashlib
    push_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    payload_json = json.dumps(payload, default=str, sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()[:16]

    conn = get_connection()
    conn.execute(
        """INSERT INTO dcl_pushes (push_id, aod_run_id, pushed_at, pipe_count, payload_hash, payload, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (push_id, aod_run_id, now, pipe_count, payload_hash, payload_json, notes),
    )
    conn.commit()
    conn.close()

    return {
        "push_id": push_id,
        "pushed_at": now,
        "pipe_count": pipe_count,
        "payload_hash": payload_hash,
        "aod_run_id": aod_run_id,
    }


def list_dcl_pushes(limit: int = 25) -> list[dict]:
    """List recent DCL pushes (without full payload)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT push_id, aod_run_id, pushed_at, pipe_count, payload_hash, notes
           FROM dcl_pushes ORDER BY pushed_at DESC LIMIT ?""",
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_dcl_push(push_id: str) -> Optional[dict]:
    """Get a specific DCL push including full payload."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dcl_pushes WHERE push_id = ?", (push_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    if result.get("payload"):
        result["payload"] = json.loads(result["payload"])
    return result
