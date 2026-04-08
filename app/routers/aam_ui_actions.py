"""
AAM UI Action Endpoints — new-architecture topology page actions.

These routes back the three sidebar buttons on /ui/topology:
  - Run Discovery       → POST /api/aam/discovery/run
  - Validate Credentials → POST /api/aam/credentials/validate
  - Start Ingest        → POST /api/aam/ingest/start

Plus the supporting status/health probes the page reads on mount:
  - GET /api/aam/discovery/manifest-status  (drives "Run Discovery" enabled state)
  - GET /api/aam/health/summary             (drives the Health stat tile)

These are STUB handlers per the audit prompt. They return
{"status": "ok", "message": "stub"} (200) and DO NOT call any of the old
pipeline handlers (/api/handoff/aod/fetch, /api/aam/infer,
/api/export/dcl/push, /api/runners/dispatch-batch, etc.).

Identity note (I1–I2): these are UI action acknowledgements, not pipeline
stage responses, so they do not carry tenant_id/entity_id. Real
implementations that touch pipeline state will be required to carry the
identity pair when those wires are built.
"""
from fastapi import APIRouter

from ..db import list_pipes
from ..db.fabric_planes import get_fabric_planes

router = APIRouter(prefix="/api/aam", tags=["AAM UI Actions"])


@router.get("/discovery/manifest-status")
async def discovery_manifest_status():
    """Return whether a vendor manifest is loaded for this tenant.

    Used by the topology page to gate the Run Discovery button. The
    closest existing concept to a "vendor manifest" is the
    fabric_planes table — at least one row means AOD has handed off
    a manifest at some point.
    """
    planes = get_fabric_planes()
    return {
        "manifest_loaded": len(planes) > 0,
        "plane_count": len(planes),
    }


@router.post("/discovery/run")
async def discovery_run():
    """STUB — real impl will trigger MCP discovery."""
    return {"status": "ok", "message": "stub"}


@router.post("/credentials/validate")
async def credentials_validate():
    """STUB — real impl will probe each transport shim per fabric plane."""
    return {
        "status": "ok",
        "message": "stub",
        "results": [
            {"plane": "ipaas", "status": "connected"},
            {"plane": "api_gateway", "status": "connected"},
            {"plane": "event_bus", "status": "connected"},
            {"plane": "warehouse", "status": "connected"},
        ],
    }


@router.post("/ingest/start")
async def ingest_start():
    """STUB — real impl will start transport shim → DCL ingest workers."""
    return {
        "status": "ok",
        "message": "stub",
        "ingest_state": "active",
    }


@router.get("/health/summary")
async def health_summary():
    """STUB — real impl will aggregate AdapterStatus / FabricDriftType.

    Returns the four sub-counts the topology Health tile renders:
    reachable / degraded / unreachable / auth_expired.
    """
    return {
        "status": "ok",
        "reachable": 0,
        "degraded": 0,
        "unreachable": 0,
        "auth_expired": 0,
    }


@router.get("/pipes/count")
async def pipes_count():
    """Return the count of declared pipes for instrumentation tile gating.

    "Active" pipes here = all pipes returned by list_pipes(). The
    declared_pipes table has no is_active column today; pipes are
    canonically backed by connection_candidates and have no explicit
    deactivation mechanism. When deactivation is added, this query
    will gain a status filter.
    """
    pipes = list_pipes()
    return {"count": len(pipes)}
