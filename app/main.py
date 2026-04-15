"""
AAM (Adaptive API Mesh) - FastAPI Backend

Inventory reusable data pipes and make their behavior explicit.
AOD emits intent → AAM declares pipes → DCL unifies meaning.
"""
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from .config import settings
from .logger import get_logger
from .constants import SOR_CATEGORIES
from .ui.styles import NAV_STYLE, NAV_HTML

_log = get_logger("main")

from .db import (
    init_db,
    create_candidate,
    get_candidate,
    list_candidates,
    update_candidate_status,
    create_pipe,
    get_pipe,
    list_pipes,
    get_pipe_versions,
    get_drift_events,
    list_all_drift_events,
    list_collectors,
    get_unprocessed_observations,
    mark_observation_processed,
    create_collector_run,
    complete_collector_run,
    get_collector_run,
    list_collector_runs,
    update_drift_status,
    update_candidate_match,
    update_candidate_deferred,
    list_tee_requests,
    update_tee_request_status,
    create_tee_request,
    get_tee_request,
    get_drift_event,
    create_drift_event,
    clear_all_data,
    reset_aod_state,
    get_pipe_stats,
    create_observation,
    get_topology_data,
    get_topology_for_pipe,
    get_topology_for_fabric_plane,
    create_handoff_log,
    get_handoff_log,
    list_handoff_logs,
    save_policy_manifest,
    get_active_policy_manifest,
    list_policy_manifests,
    get_candidates_by_aod_run,
    get_aod_reconciliation,
    get_latest_aod_run,
    get_canonical_stats,
    store_fabric_plane
)
from .inference import infer_pipes_from_observations
from .models import (
    ConnectionCandidateCreate,
    CandidateIntakeResponse,
    CandidateStatus,
    ExportResponse,
    FabricPlane,
    AODActionType,
    AODHandoffRequest,
    AODHandoffResponse,
    AODPolicyManifest
)
from .fabric_drift import FabricDriftDetector, FabricDriftType
from .adapters.factory import get_adapter_for_plane
from .adapters.base import AdapterStatus, PlaneHealth
from .pii_redaction import redact_pii_from_observation


# ---------------------------------------------------------------------------
# App factory + lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    init_db()
    # Initialize the triple write ledger (SQLite, AAM-local)
    from .db.ledger import init_ledger_db
    init_ledger_db()
    # Log operating mode at startup
    from .utils.operating_mode import get_operating_mode
    mode = get_operating_mode()
    _log.info("AAM operating mode: %s", mode.value)
    from .services.runner_worker import start_worker, stop_worker
    await start_worker()
    yield
    await stop_worker()


app = FastAPI(
    title="AAM - Adaptive API Mesh",
    description="Inventory reusable data pipes and make their behavior explicit. AOD emits intent → AAM declares pipes → DCL unifies meaning.",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

# Serve static assets (favicon, etc.)
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Global component instances (accessed by routers via `from ..main import ...`)
drift_detector = FabricDriftDetector()
adapter_registry: dict = {}  # plane_type -> adapter instance


# ---------------------------------------------------------------------------
# Include all API routers
# ---------------------------------------------------------------------------
from .routers.handoff import router as handoff_router, fabric_router
from .routers.candidates import router as candidates_router
from .routers.pipes import router as pipes_router
from .routers.collectors import router as collectors_router
from .routers.drift import router as drift_router, fabric_drift_router
from .routers.tee import router as tee_router
from .routers.adapters import router as adapters_router
from .routers.topology import router as topology_router
from .routers.export import router as export_router
from .routers.admin import router as admin_router
from .routers.ui_pages import router as ui_pages_router
from .routers.runners import router as runners_router
from .routers.dcl_ingest import router as dcl_ingest_router
from .routers.mai import router as mai_router
from .routers.controls import router as controls_router
from .routers.controls_ui import router as controls_ui_router
from .routers.aam_ui_actions import router as aam_ui_actions_router

app.include_router(handoff_router)
app.include_router(fabric_router)
app.include_router(candidates_router)
app.include_router(pipes_router)
app.include_router(collectors_router)
app.include_router(drift_router)
app.include_router(fabric_drift_router)
app.include_router(tee_router)
app.include_router(adapters_router)
app.include_router(topology_router)
app.include_router(export_router)
app.include_router(admin_router)
app.include_router(runners_router)
app.include_router(dcl_ingest_router)
app.include_router(mai_router)
app.include_router(controls_router)
app.include_router(controls_ui_router)
app.include_router(aam_ui_actions_router)
app.include_router(ui_pages_router)


# ---------------------------------------------------------------------------
# Root + docs (small inline handlers)
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Redirect to Topology visualization"""
    return RedirectResponse(url="/ui/topology")


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
async def custom_swagger_ui():
    """Custom Swagger UI with navigation"""
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>AAM</title>
    {NAV_STYLE}
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
    <style>
        .swagger-ui .topbar {{ display: none; }}
        .swagger-ui {{ background: #0f172a; }}
        .swagger-ui .info {{ margin: 20px 0; }}
    </style>
</head>
<body>
    {NAV_HTML.format(pipes_active="", candidates_active="", drift_active="", guide_active="", docs_active=" active")}
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        SwaggerUIBundle({{
            url: '/openapi.json',
            dom_id: '#swagger-ui',
            presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
            layout: "BaseLayout",
            deepLinking: true
        }});
    </script>
</body>
</html>
""")


@app.get("/redoc", response_class=HTMLResponse, include_in_schema=False)
async def custom_redoc():
    """Custom ReDoc with navigation"""
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>AAM</title>
    {NAV_STYLE}
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
    <style>
        body {{ margin: 0; padding: 0; }}
    </style>
</head>
<body>
    {NAV_HTML.format(pipes_active="", candidates_active="", drift_active="", guide_active="", docs_active="")}
    <redoc spec-url='/openapi.json'></redoc>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>
""")


# ---------------------------------------------------------------------------
# Legacy candidate intake endpoints (kept for backward compatibility)
# ---------------------------------------------------------------------------

@app.get("/health")
@app.get("/api/health")
async def health_check():
    """Quick health check"""
    return {"status": "healthy", "service": "aam", "version": "0.1.0"}


@app.post("/api/aam/candidates", tags=["Candidate Intake"])
async def intake_candidate(candidate: ConnectionCandidateCreate):
    """Original single-candidate intake (pre-AOD handoff)."""
    candidate_dict = candidate.model_dump()
    result = create_candidate(candidate_dict)
    return CandidateIntakeResponse(**result)


@app.get("/api/aam/candidates", tags=["Candidate Intake"])
async def list_all_candidates(
    status: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
):
    """List candidates with optional status filter."""
    candidates = list_candidates(status=status, limit=limit)
    return {"candidates": candidates, "count": len(candidates)}


@app.get("/api/aam/candidates/{candidate_id}", tags=["Candidate Intake"])
async def get_single_candidate(candidate_id: str):
    """Get a specific candidate."""
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@app.post("/api/handoff/aod/reset", tags=["AOD Handoff"])
async def reset_aod():
    """Reset AOD handoff state (dev/test only)."""
    result = reset_aod_state()
    return {"message": "AOD handoff state reset", **result}
