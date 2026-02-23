"""
DCL Push Tracking — records each export pushed to DCL for reconciliation.
"""
import json
import hashlib
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def record_dcl_push(
    pipe_count: int,
    payload: dict,
    aod_run_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Record a DCL push with full payload for later reconciliation."""
    push_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    payload_json = json.dumps(payload, default=str, sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()[:16]

    sb.insert("dcl_pushes", {
        "push_id": push_id,
        "aod_run_id": aod_run_id,
        "pushed_at": now,
        "pipe_count": pipe_count,
        "payload_hash": payload_hash,
        "payload": payload_json,
        "notes": notes,
    })

    return {
        "push_id": push_id,
        "pushed_at": now,
        "pipe_count": pipe_count,
        "payload_hash": payload_hash,
        "aod_run_id": aod_run_id,
    }


def list_dcl_pushes(limit: int = 25) -> list[dict]:
    """List recent DCL pushes (without full payload)."""
    rows = sb.select(
        "dcl_pushes",
        columns="push_id,aod_run_id,pushed_at,pipe_count,payload_hash,notes",
        order="pushed_at.desc",
        limit=limit,
    )
    return rows


def has_dcl_push_for_run(aod_run_id: str) -> bool:
    """Check whether export-pipes has been pushed to DCL for a given AOD run."""
    rows = sb.select(
        "dcl_pushes",
        columns="push_id",
        filters={"aod_run_id": aod_run_id},
        limit=1,
    )
    return len(rows) > 0


def get_dcl_push(push_id: str) -> Optional[dict]:
    """Get a specific DCL push including full payload."""
    row = sb.select("dcl_pushes", filters={"push_id": push_id}, single=True)
    if not row:
        return None
    if row.get("payload"):
        row["payload"] = json.loads(row["payload"])
    return row
