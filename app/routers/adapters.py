"""
Adapters Router — fabric plane adapter management.
"""
from fastapi import APIRouter, HTTPException

from ..models import FabricPlane
from ..adapters.base import AdapterStatus
from ..adapters.factory import get_adapter_for_plane

router = APIRouter(prefix="/api/adapters", tags=["Fabric Adapters"])


def _get_globals():
    from ..main import adapter_registry, preset_loader, drift_detector
    return adapter_registry, preset_loader, drift_detector


@router.get("")
async def list_adapters():
    """List all registered fabric plane adapters and their status."""
    adapter_registry, preset_loader, _ = _get_globals()
    result = []
    for plane_type, adapter in adapter_registry.items():
        health = await adapter.check_health()
        result.append({
            "plane_type": plane_type,
            "vendor": adapter.plane_vendor,
            "status": health.status.value,
            "last_check": health.last_check.isoformat(),
            "latency_ms": health.latency_ms,
        })
    return {"adapters": result, "count": len(result), "current_preset": preset_loader.current_config.name}


@router.post("/{plane_type}/connect")
async def connect_adapter(plane_type: str):
    """Connect to a fabric plane."""
    adapter_registry, preset_loader, _ = _get_globals()

    if plane_type not in adapter_registry:
        try:
            plane_enum = FabricPlane(plane_type.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid plane type: {plane_type}")
        config = preset_loader.current_config.adapter_config.get(plane_type.lower(), {})
        adapter = get_adapter_for_plane(plane_enum, config)
        if not adapter:
            raise HTTPException(status_code=400, detail=f"Could not create adapter for {plane_type}")
        adapter_registry[plane_type] = adapter

    adapter = adapter_registry[plane_type]
    success = await adapter.connect()
    health = await adapter.check_health()
    return {
        "plane_type": plane_type,
        "connected": success,
        "status": health.status.value,
        "vendor": adapter.plane_vendor,
    }


@router.post("/{plane_type}/disconnect")
async def disconnect_adapter(plane_type: str):
    """Disconnect from a fabric plane."""
    adapter_registry, _, _ = _get_globals()
    if plane_type not in adapter_registry:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {plane_type}")
    adapter = adapter_registry[plane_type]
    success = await adapter.disconnect()
    return {"plane_type": plane_type, "disconnected": success}


@router.get("/{plane_type}/health")
async def check_adapter_health(plane_type: str):
    """Check health of a fabric plane adapter."""
    adapter_registry, _, drift_detector = _get_globals()
    if plane_type not in adapter_registry:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {plane_type}")
    adapter = adapter_registry[plane_type]
    health = await adapter.check_health()
    drift_event = drift_detector.detect_connection_drift(
        plane_type=plane_type,
        plane_vendor=adapter.plane_vendor,
        is_connected=(health.status == AdapterStatus.CONNECTED),
    )
    return {
        "plane_type": plane_type,
        "vendor": adapter.plane_vendor,
        "status": health.status.value,
        "latency_ms": health.latency_ms,
        "last_check": health.last_check.isoformat(),
        "metrics": health.metrics,
        "drift_detected": drift_event is not None,
        "drift_id": drift_event.drift_id if drift_event else None,
    }


@router.post("/{plane_type}/discover")
async def discover_from_adapter(plane_type: str):
    """Discover pipes from a fabric plane adapter."""
    adapter_registry, preset_loader, _ = _get_globals()
    if plane_type not in adapter_registry:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {plane_type}")
    adapter = adapter_registry[plane_type]
    health = await adapter.check_health()
    if health.status != AdapterStatus.CONNECTED:
        raise HTTPException(status_code=400, detail=f"Adapter not connected. Status: {health.status.value}")
    policies = preset_loader.get_governance_policies()
    adapter.apply_governance_policy(policies)
    observations = await adapter.discover_pipes()
    return {
        "plane_type": plane_type,
        "observations_count": len(observations),
        "observations": observations,
        "governance_applied": list(policies.keys()),
    }


@router.post("/{plane_type}/self-heal")
async def trigger_self_heal(plane_type: str):
    """Trigger self-healing for a fabric plane adapter."""
    adapter_registry, _, drift_detector = _get_globals()
    if plane_type not in adapter_registry:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {plane_type}")
    adapter = adapter_registry[plane_type]
    drifts = drift_detector.get_drift_by_plane(plane_type)
    if not drifts:
        return {"message": "No active drifts to heal", "healed": 0}
    healed = 0
    results = []
    for drift in drifts:
        success = await drift_detector.attempt_self_heal(drift, adapter)
        if success:
            healed += 1
        results.append({"drift_id": drift.drift_id, "drift_type": drift.drift_type.value, "healed": success})
    return {"healed": healed, "total_drifts": len(drifts), "results": results}
