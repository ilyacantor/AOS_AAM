"""
TEE request operations
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb
from .drift import _row_to_drift_event
from ..logger import get_logger

_log = get_logger("db.tee")


def _safe_json(raw, default):
    """Parse JSON, returning default and logging if the stored value is corrupt."""
    if not raw:
        return default
    try:
        result = json.loads(raw)
        return result if result is not None else default
    except (json.JSONDecodeError, TypeError) as exc:
        _log.error("Corrupt JSON in tee row (returning default): %s — raw=%r", exc, raw[:100])
        return default


def list_tee_requests(status: Optional[str] = None) -> list[dict]:
    """List tee requests with optional status filter"""
    filters = {}
    if status:
        filters["status"] = status

    rows = sb.select(
        "tee_requests",
        filters=filters if filters else None,
        order="requested_at.desc",
    )

    return [{
        "tee_id": row["tee_id"],
        "pipe_id": row["pipe_id"],
        "target_system": row["target_system"],
        "tee_type": row["tee_type"],
        "configuration": _safe_json(row["configuration"], {}),
        "status": row["status"],
        "requested_at": row["requested_at"],
        "approved_at": row["approved_at"],
        "verified_at": row["verified_at"],
    } for row in rows]


def get_drift_event(drift_id: str) -> Optional[dict]:
    """Get a drift event by ID"""
    row = sb.select("drift_events", filters={"drift_id": drift_id}, single=True)

    if row:
        return _row_to_drift_event(row)
    return None


def get_tee_request(tee_id: str) -> Optional[dict]:
    """Get a single TEE request by ID"""
    row = sb.select("tee_requests", filters={"tee_id": tee_id}, single=True)

    if row:
        return {
            "tee_id": row["tee_id"],
            "pipe_id": row["pipe_id"],
            "target_system": row["target_system"],
            "tee_type": row["tee_type"],
            "configuration": _safe_json(row["configuration"], {}),
            "status": row["status"],
            "requested_at": row["requested_at"],
            "approved_at": row["approved_at"],
            "verified_at": row["verified_at"],
        }
    return None


def create_tee_request(tee_data: dict) -> dict:
    """Create a new tee request"""
    tee_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    sb.insert("tee_requests", {
        "tee_id": tee_id,
        "pipe_id": tee_data["pipe_id"],
        "target_system": tee_data["target_system"],
        "tee_type": tee_data.get("tee_type", "api_proxy"),
        "configuration": json.dumps(tee_data.get("configuration", {})),
        "status": "requested",
        "requested_at": now,
    })

    return {
        "tee_id": tee_id,
        "pipe_id": tee_data["pipe_id"],
        "target_system": tee_data["target_system"],
        "tee_type": tee_data.get("tee_type", "api_proxy"),
        "configuration": tee_data.get("configuration", {}),
        "status": "requested",
        "requested_at": now,
        "approved_at": None,
        "verified_at": None,
    }


_TEE_STATUSES = frozenset({"requested", "approved", "verified"})


def update_tee_request_status(tee_id: str, status: str) -> Optional[dict]:
    """Update tee request status (requested, approved, verified)"""
    if status not in _TEE_STATUSES:
        raise ValueError(f"Invalid TEE request status {status!r}. Must be one of: {sorted(_TEE_STATUSES)}")
    now = datetime.utcnow().isoformat()

    update_data = {"status": status}
    if status == "approved":
        update_data["approved_at"] = now
    elif status == "verified":
        update_data["verified_at"] = now

    sb.update("tee_requests", update_data, filters={"tee_id": tee_id})

    row = sb.select("tee_requests", filters={"tee_id": tee_id}, single=True)
    if row:
        return {
            "tee_id": row["tee_id"],
            "pipe_id": row["pipe_id"],
            "target_system": row["target_system"],
            "tee_type": row["tee_type"],
            "configuration": _safe_json(row["configuration"], {}),
            "status": row["status"],
            "requested_at": row["requested_at"],
            "approved_at": row["approved_at"],
            "verified_at": row["verified_at"],
        }

    return None
