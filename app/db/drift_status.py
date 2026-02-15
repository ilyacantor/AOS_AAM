"""
Drift status operations (v1)
"""
from datetime import datetime
from typing import Optional

from . import supabase_client as sb
from .drift import _row_to_drift_event


def update_drift_status(drift_id: str, status: str, by: Optional[str] = None, notes: Optional[str] = None) -> Optional[dict]:
    """Update drift event status (open, acknowledged, suppressed, resolved)"""
    now = datetime.utcnow().isoformat()

    update_data = {"status": status}

    if status == "acknowledged":
        update_data["acknowledged_at"] = now
        update_data["acknowledged_by"] = by
    elif status == "suppressed":
        update_data["suppressed_at"] = now
        update_data["suppressed_by"] = by

    if notes is not None:
        update_data["notes"] = notes

    result = sb.update("drift_events", update_data, filters={"drift_id": drift_id})

    if result:
        row = sb.select("drift_events", filters={"drift_id": drift_id}, single=True)
        if row:
            return _row_to_drift_event(row)

    return None
