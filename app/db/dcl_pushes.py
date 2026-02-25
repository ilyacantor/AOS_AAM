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


def get_exported_pipe_ids(aod_run_id: str) -> set[str]:
    """Return the set of pipe_ids from the most recent DCL push for this run.

    Used by dispatch to verify that every pipe being dispatched was actually
    included in the last export — prevents NO_MATCHING_PIPE errors at Farm/DCL.
    """
    rows = sb.select(
        "dcl_pushes",
        columns="payload",
        filters={"aod_run_id": aod_run_id},
        order="pushed_at.desc",
        limit=1,
    )
    if not rows or not rows[0].get("payload"):
        return set()

    raw = rows[0]["payload"]
    payload = json.loads(raw) if isinstance(raw, str) else raw

    pipe_ids: set[str] = set()
    # The export payload nests pipes under fabric_planes[].connections[]
    for plane in payload.get("fabric_planes", []):
        for conn in plane.get("connections", []):
            pid = conn.get("pipe_id")
            if pid:
                pipe_ids.add(pid)
    return pipe_ids


def record_dcl_export_attempt(
    aod_run_id: Optional[str],
    pipe_count: int,
    dcl_ok: bool,
    dcl_status: Optional[int] = None,
    dcl_body: Optional[str] = None,
    dcl_error: Optional[str] = None,
) -> dict:
    """Record every DCL export attempt (success AND failure) for diagnostics.

    Unlike record_dcl_push() which only records successes, this captures
    the HTTP status, response body, and error string so operators can
    diagnose why an export failed without searching stderr logs.
    """
    attempt_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    row = {
        "attempt_id": attempt_id,
        "aod_run_id": aod_run_id,
        "pipe_count": pipe_count,
        "dcl_ok": dcl_ok,
        "dcl_status": dcl_status,
        "dcl_body": (dcl_body or "")[:2000] if dcl_body else None,
        "dcl_error": dcl_error,
        "created_at": now,
    }
    sb.insert("dcl_export_attempts", row)
    return row


def get_last_export_attempt(aod_run_id: Optional[str] = None) -> Optional[dict]:
    """Return the most recent DCL export attempt, optionally filtered by run."""
    filters = {"aod_run_id": aod_run_id} if aod_run_id else None
    rows = sb.select(
        "dcl_export_attempts",
        filters=filters,
        order="created_at.desc",
        limit=1,
    )
    return rows[0] if rows else None


def get_dcl_push(push_id: str) -> Optional[dict]:
    """Get a specific DCL push including full payload."""
    row = sb.select("dcl_pushes", filters={"push_id": push_id}, single=True)
    if not row:
        return None
    if row.get("payload"):
        row["payload"] = json.loads(row["payload"])
    return row
