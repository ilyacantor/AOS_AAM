"""
Drift event operations
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb
from ..logger import get_logger

_log = get_logger("db.drift")


def _safe_json(raw, default):
    """Parse JSON, returning default and logging if the stored value is corrupt."""
    if not raw:
        return default
    try:
        result = json.loads(raw)
        return result if result is not None else default
    except (json.JSONDecodeError, TypeError) as exc:
        _log.error("Corrupt JSON in drift row (returning default): %s — raw=%r", exc, raw[:100])
        return default


def create_drift_event(pipe_id: str, drift_type: str, old_value: str, new_value: str, details: Optional[dict] = None) -> str:
    """Create a drift event"""
    drift_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    data = {
        "drift_id": drift_id,
        "pipe_id": pipe_id,
        "drift_type": drift_type,
        "old_value": old_value,
        "new_value": new_value,
        "details": json.dumps(details) if details else None,
        "detected_at": now,
    }

    sb.insert("drift_events", data)

    # --- EAV triple for drift event (non-fatal) ---
    try:
        from ..converters.triple_converter import (
            convert_drift_to_triples, generate_run_id, resolve_entity_id,
        )
        from .triple_writer import write_triples

        handoffs = sb.select("aod_handoff_log", order="processed_at.desc", limit=1)
        _snap = handoffs[0].get("snapshot_name") if handoffs else None
        _aod = handoffs[0].get("aod_run_id") if handoffs else None
        _eid = resolve_entity_id(_snap, _aod)
        if _eid:
            _ruuid, _rtag = generate_run_id()
            _dtriples = convert_drift_to_triples(data, _eid, _ruuid, _rtag)
            if _dtriples:
                write_triples(_dtriples)
    except Exception as _exc:
        _log.error("Drift triple conversion failed (non-fatal): %s", _exc)

    return drift_id


def _row_to_drift_event(row) -> dict:
    """Convert database row to drift event dict"""
    result = {
        "drift_id": row.get("drift_id"),
        "pipe_id": row.get("pipe_id"),
        "drift_type": row.get("drift_type"),
        "old_value": row.get("old_value"),
        "new_value": row.get("new_value"),
        "details": _safe_json(row.get("details"), None),
        "detected_at": row.get("detected_at"),
        "severity": row.get("severity", "medium"),
        "status": row.get("status", "open"),
        "acknowledged_at": row.get("acknowledged_at"),
        "acknowledged_by": row.get("acknowledged_by"),
        "suppressed_at": row.get("suppressed_at"),
        "suppressed_by": row.get("suppressed_by"),
        "notes": row.get("notes"),
    }
    return result


def get_drift_events(pipe_id: str) -> list[dict]:
    """Get drift events for a pipe"""
    rows = sb.select("drift_events", filters={"pipe_id": pipe_id}, order="detected_at.desc")
    return [_row_to_drift_event(row) for row in rows]


def list_all_drift_events(limit: Optional[int] = 500) -> list[dict]:
    """List all drift events"""
    kwargs = {"order": "detected_at.desc"}
    if limit:
        kwargs["limit"] = limit
    rows = sb.select("drift_events", **kwargs)
    return [_row_to_drift_event(row) for row in rows]
