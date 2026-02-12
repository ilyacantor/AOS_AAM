"""
Drift Router — schema drift and fabric drift endpoints.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from ..db import (
    list_all_drift_events,
    get_drift_event,
    update_drift_status,
)

router = APIRouter(tags=["Drift"])


class DriftActionRequest(BaseModel):
    by: Optional[str] = "operator"
    notes: Optional[str] = None


@router.get("/api/drift")
async def get_all_drift_events(limit: Optional[int] = Query(None)):
    """List all drift events."""
    events = list_all_drift_events(limit=limit)
    return {"drift_events": events, "count": len(events)}


@router.post("/api/drift/{drift_id}/ack")
async def acknowledge_drift(drift_id: str, request: DriftActionRequest):
    """Acknowledge a drift event."""
    drift = get_drift_event(drift_id)
    if not drift:
        raise HTTPException(status_code=404, detail="Drift event not found")
    updated = update_drift_status(drift_id, "acknowledged", by=request.by, notes=request.notes)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to acknowledge drift event")
    return updated


@router.post("/api/drift/{drift_id}/suppress")
async def suppress_drift(drift_id: str, request: DriftActionRequest):
    """Suppress a drift event."""
    drift = get_drift_event(drift_id)
    if not drift:
        raise HTTPException(status_code=404, detail="Drift event not found")
    updated = update_drift_status(drift_id, "suppressed", by=request.by, notes=request.notes)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to suppress drift event")
    return updated


# Fabric Drift Router
fabric_drift_router = APIRouter(prefix="/api/fabric-drift", tags=["Fabric Drift"])


@fabric_drift_router.get("")
async def list_fabric_drift():
    """List all fabric plane drift events."""
    from ..main import drift_detector

    drifts = drift_detector.get_active_drifts()
    return {
        "drifts": [
            {
                "drift_id": d.drift_id,
                "plane_type": d.plane_type,
                "plane_vendor": d.plane_vendor,
                "drift_type": d.drift_type.value,
                "severity": d.severity.value,
                "detected_at": d.detected_at.isoformat(),
                "acknowledged": d.acknowledged,
                "suppressed": d.suppressed,
                "auto_heal_attempted": d.auto_heal_attempted,
                "auto_heal_success": d.auto_heal_success,
            }
            for d in drifts
        ],
        "count": len(drifts),
    }


@fabric_drift_router.get("/stats")
async def get_fabric_drift_stats():
    """Get fabric drift statistics."""
    from ..main import drift_detector
    return drift_detector.get_drift_stats()


@fabric_drift_router.get("/heal-history")
async def get_heal_history():
    """Get self-healing history."""
    from ..main import drift_detector
    return {"history": drift_detector.get_heal_history()}


@fabric_drift_router.post("/{drift_id}/ack")
async def acknowledge_fabric_drift(drift_id: str):
    """Acknowledge a fabric drift event."""
    from ..main import drift_detector

    success = drift_detector.acknowledge_drift(drift_id)
    if not success:
        raise HTTPException(status_code=404, detail="Drift event not found")
    return {"drift_id": drift_id, "acknowledged": True}


@fabric_drift_router.post("/{drift_id}/suppress")
async def suppress_fabric_drift(drift_id: str):
    """Suppress a fabric drift event."""
    from ..main import drift_detector

    success = drift_detector.suppress_drift(drift_id)
    if not success:
        raise HTTPException(status_code=404, detail="Drift event not found")
    return {"drift_id": drift_id, "suppressed": True}
