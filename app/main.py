"""
AAM (Adaptive API Mesh) - FastAPI Backend

Inventory reusable data pipes and make their behavior explicit.
AOD emits intent → AAM declares pipes → DCL unifies meaning.
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

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
    get_drift_event
)
from .collectors.mock import run_mock_collector
from .inference import infer_pipes_from_observations
from .models import (
    ConnectionCandidateCreate,
    CandidateIntakeResponse,
    CandidateStatus,
    ExportResponse
)

app = FastAPI(
    title="AAM - Adaptive API Mesh",
    description="Inventory reusable data pipes and make their behavior explicit. AOD emits intent → AAM declares pipes → DCL unifies meaning.",
    version="0.1.0",
    docs_url=None,
    redoc_url=None
)


@app.on_event("startup")
async def startup_event():
    init_db()


NAV_STYLE = """
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Quicksand', sans-serif; background: #0f172a; color: #ffffff; }
    .nav {
        background: rgba(30, 41, 59, 0.9);
        border-bottom: 1px solid #334155;
        padding: 12px 24px;
        display: flex;
        align-items: center;
        gap: 24px;
        position: sticky;
        top: 0;
        z-index: 1000;
        backdrop-filter: blur(8px);
    }
    .nav-brand {
        font-size: 1.1rem;
        font-weight: 700;
        background: linear-gradient(135deg, #22d3ee, #0891b2);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        text-decoration: none;
    }
    .nav-links { display: flex; gap: 8px; }
    .nav-link {
        color: #ffffff;
        text-decoration: none;
        padding: 8px 16px;
        border-radius: 6px;
        font-weight: 500;
        transition: all 0.2s ease;
        border: 1px solid transparent;
    }
    .nav-link:hover {
        color: #22d3ee;
        background: rgba(34, 211, 238, 0.1);
        border-color: rgba(34, 211, 238, 0.3);
    }
    .nav-link.active {
        color: #22d3ee;
        background: rgba(34, 211, 238, 0.2);
        border-color: rgba(34, 211, 238, 0.3);
    }
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
"""

NAV_HTML = """
<nav class="nav">
    <a href="/" class="nav-brand">AAM</a>
    <div class="nav-links">
        <a href="/" class="nav-link{home_active}">Home</a>
        <a href="/docs" class="nav-link{docs_active}">API Docs</a>
        <a href="/redoc" class="nav-link{redoc_active}">ReDoc</a>
    </div>
</nav>
"""


@app.get("/", response_class=HTMLResponse)
async def root():
    """Landing page with AAM branding"""
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>AAM - Adaptive API Mesh</title>
    {NAV_STYLE}
    <style>
        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 80px 20px;
            text-align: center;
        }}
        h1 {{
            font-size: 3rem;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #22d3ee, #0891b2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .subtitle {{
            font-size: 1.25rem;
            color: #94a3b8;
            margin-bottom: 40px;
        }}
        .tagline {{
            font-size: 1.5rem;
            color: #e2e8f0;
            line-height: 1.6;
            margin-bottom: 48px;
            font-weight: 500;
        }}
        .flow {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 16px;
            margin-bottom: 48px;
            flex-wrap: wrap;
        }}
        .flow-item {{
            background: rgba(30, 41, 59, 0.6);
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 16px 24px;
            font-weight: 600;
        }}
        .flow-arrow {{
            color: #22d3ee;
            font-size: 1.5rem;
        }}
        .cta {{
            display: inline-block;
            background: linear-gradient(135deg, #22d3ee, #0891b2);
            color: #0f172a;
            padding: 14px 32px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            font-size: 1.1rem;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}
        .cta:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(34, 211, 238, 0.3);
        }}
    </style>
</head>
<body>
    {NAV_HTML.format(home_active=" active", docs_active="", redoc_active="")}
    <div class="container">
        <h1>Adaptive API Mesh</h1>
        <p class="subtitle">AAM v0.1.0</p>
        <p class="tagline">We do not change how data moves.<br>We make its behavior and meaning explicit.</p>
        <div class="flow">
            <div class="flow-item">AOD emits intent</div>
            <span class="flow-arrow">→</span>
            <div class="flow-item">AAM declares pipes</div>
            <span class="flow-arrow">→</span>
            <div class="flow-item">DCL unifies meaning</div>
        </div>
        <a href="/docs" class="cta">Explore API Documentation</a>
    </div>
</body>
</html>
""")


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
async def custom_swagger_ui():
    """Custom Swagger UI with navigation"""
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>API Docs - AAM</title>
    {NAV_STYLE}
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
    <style>
        .swagger-ui .topbar {{ display: none; }}
        .swagger-ui {{ background: #0f172a; }}
        .swagger-ui .info {{ margin: 20px 0; }}
    </style>
</head>
<body>
    {NAV_HTML.format(home_active="", docs_active=" active", redoc_active="")}
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
    <title>ReDoc - AAM</title>
    {NAV_STYLE}
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
    <style>
        body {{ margin: 0; padding: 0; }}
    </style>
</head>
<body>
    {NAV_HTML.format(home_active="", docs_active="", redoc_active=" active")}
    <redoc spec-url='/openapi.json'></redoc>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>
""")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "AAM",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }


class StatusUpdate(BaseModel):
    status: CandidateStatus


@app.post("/api/aam/candidates", tags=["Candidates"])
async def create_connection_candidate(candidate: ConnectionCandidateCreate):
    """Create a new connection candidate from AOD"""
    candidate_dict = candidate.model_dump()
    if candidate.preferred_modality:
        candidate_dict["preferred_modality"] = candidate.preferred_modality.value
    if candidate.findings:
        candidate_dict["findings"] = [f.model_dump() for f in candidate.findings]
    
    result = create_candidate(candidate_dict)
    return CandidateIntakeResponse(
        candidate_id=result["candidate_id"],
        status=CandidateStatus.NEW,
        message="Candidate created successfully"
    )


@app.get("/api/aam/candidates", tags=["Candidates"])
async def get_candidates(status: Optional[str] = Query(None, description="Filter by status")):
    """List all connection candidates"""
    candidates = list_candidates(status=status)
    return {"candidates": candidates, "count": len(candidates)}


@app.get("/api/aam/candidates/{candidate_id}", tags=["Candidates"])
async def get_single_candidate(candidate_id: str):
    """Get a single candidate by ID"""
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@app.patch("/api/aam/candidates/{candidate_id}/status", tags=["Candidates"])
async def update_status(candidate_id: str, update: StatusUpdate):
    """Update candidate status"""
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    success = update_candidate_status(candidate_id, update.status.value)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update status")
    
    return {"candidate_id": candidate_id, "status": update.status.value, "message": "Status updated"}


@app.get("/api/aam/collectors", tags=["Collectors"])
async def get_collectors():
    """List all collectors"""
    collectors = list_collectors()
    return {"collectors": collectors, "count": len(collectors)}


class MockCollectorRequest(BaseModel):
    candidate_id: Optional[str] = None


@app.post("/api/aam/collectors/mock/run", tags=["Collectors"])
async def run_mock(request: Optional[MockCollectorRequest] = None):
    """Run the mock collector to generate observations"""
    candidate_id = request.candidate_id if request else None
    observations = run_mock_collector(candidate_id=candidate_id)
    return {
        "message": "Mock collector executed",
        "observations_created": len(observations),
        "observations": observations
    }


@app.post("/api/aam/infer", tags=["Collectors"])
async def infer_pipes():
    """Process pending observations and create pipes"""
    observations = get_unprocessed_observations()
    if not observations:
        return {"message": "No pending observations", "pipes_created": 0, "pipes": []}
    
    inferred_pipes = infer_pipes_from_observations(observations)
    
    created_pipes = []
    for pipe in inferred_pipes:
        action = pipe.pop("_action", "create")
        if action == "create":
            result = create_pipe(pipe)
            pipe["pipe_id"] = result["pipe_id"]
            pipe["version"] = result["version"]
            created_pipes.append(pipe)
    
    for obs in observations:
        mark_observation_processed(obs["observation_id"])
    
    return {
        "message": "Inference complete",
        "observations_processed": len(observations),
        "pipes_created": len(created_pipes),
        "pipes": created_pipes
    }


@app.get("/api/pipes", tags=["Pipes"])
async def get_all_pipes(source_system: Optional[str] = Query(None, description="Filter by source system")):
    """List all declared pipes"""
    pipes = list_pipes(source_system=source_system)
    return {"pipes": pipes, "count": len(pipes)}


@app.get("/api/pipes/{pipe_id}", tags=["Pipes"])
async def get_single_pipe(pipe_id: str):
    """Get a single pipe by ID"""
    pipe = get_pipe(pipe_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipe not found")
    return pipe


@app.get("/api/pipes/{pipe_id}/versions", tags=["Pipes"])
async def get_pipe_version_history(pipe_id: str):
    """Get version history for a pipe"""
    pipe = get_pipe(pipe_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipe not found")
    
    versions = get_pipe_versions(pipe_id)
    return {"pipe_id": pipe_id, "versions": versions, "count": len(versions)}


@app.get("/api/pipes/{pipe_id}/drift", tags=["Pipes"])
async def get_pipe_drift_events(pipe_id: str):
    """Get drift events for a pipe"""
    pipe = get_pipe(pipe_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipe not found")
    
    events = get_drift_events(pipe_id)
    return {"pipe_id": pipe_id, "drift_events": events, "count": len(events)}


@app.get("/api/export/dcl/declared-pipes", tags=["Export"])
async def export_for_dcl():
    """Export all pipes in DCL format"""
    pipes = list_pipes()
    return {
        "export_version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "pipe_count": len(pipes),
        "pipes": pipes
    }


@app.get("/api/drift", tags=["Drift"])
async def get_all_drift_events(limit: int = Query(100, description="Maximum number of events")):
    """List all drift events"""
    events = list_all_drift_events(limit=limit)
    return {"drift_events": events, "count": len(events)}


# ============================================================================
# AAM V1 PRACTICAL INTERFACE ENDPOINTS
# ============================================================================

# --- Collector Run Tracking ---

@app.post("/api/collect/{collector}/run", tags=["Collectors"])
async def run_collector(collector: str, request: Optional[MockCollectorRequest] = None):
    """Run a collector and track the run"""
    collector_id = f"{collector}-collector-001" if collector == "mock" else collector
    
    run_id = create_collector_run(collector_id)
    
    try:
        if collector == "mock":
            candidate_id = request.candidate_id if request else None
            observations = run_mock_collector(candidate_id=candidate_id)
            complete_collector_run(run_id, "completed", len(observations))
            return {
                "run_id": run_id,
                "collector": collector,
                "status": "completed",
                "observations_created": len(observations),
                "observations": observations
            }
        else:
            complete_collector_run(run_id, "failed", 0, f"Unknown collector: {collector}")
            raise HTTPException(status_code=400, detail=f"Unknown collector: {collector}")
    except HTTPException:
        raise
    except Exception as e:
        complete_collector_run(run_id, "failed", 0, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/collect/runs", tags=["Collectors"])
async def get_collector_runs(
    collector_id: Optional[str] = Query(None, description="Filter by collector ID"),
    limit: int = Query(100, description="Maximum number of runs")
):
    """List collector runs"""
    runs = list_collector_runs(collector_id=collector_id, limit=limit)
    return {"runs": runs, "count": len(runs)}


@app.get("/api/collect/runs/{run_id}", tags=["Collectors"])
async def get_single_collector_run(run_id: str):
    """Get a specific collector run"""
    run = get_collector_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# --- Candidate Match/Defer ---

class MatchRequest(BaseModel):
    pipe_id: Optional[str] = None


class DeferRequest(BaseModel):
    reason: str


@app.post("/api/candidates/{candidate_id}/match", tags=["Candidates"])
async def match_candidate(candidate_id: str, request: MatchRequest):
    """Attempt to match candidate to a pipe"""
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    pipe_id = request.pipe_id
    score = 1.0
    reason = "Manual match"
    
    if not pipe_id:
        pipes = list_pipes(source_system=candidate.get("vendor_name"))
        if pipes:
            pipe_id = pipes[0]["pipe_id"]
            score = 0.8
            reason = "Auto-matched by vendor name"
        else:
            raise HTTPException(
                status_code=400, 
                detail="No pipe_id provided and no auto-match found. Provide a pipe_id or defer the candidate."
            )
    else:
        pipe = get_pipe(pipe_id)
        if not pipe:
            raise HTTPException(status_code=404, detail="Pipe not found")
    
    updated = update_candidate_match(candidate_id, pipe_id, score, reason)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update candidate")
    
    return {
        "candidate_id": candidate_id,
        "matched_pipe_id": pipe_id,
        "match_score": score,
        "match_reason": reason,
        "status": "connected"
    }


@app.post("/api/candidates/{candidate_id}/defer", tags=["Candidates"])
async def defer_candidate(candidate_id: str, request: DeferRequest):
    """Defer a candidate with a reason"""
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    
    updated = update_candidate_deferred(candidate_id, request.reason)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to defer candidate")
    
    return {
        "candidate_id": candidate_id,
        "status": "deferred",
        "deferred_reason": request.reason
    }


# --- Drift Ack/Suppress ---

class DriftActionRequest(BaseModel):
    by: Optional[str] = "operator"
    notes: Optional[str] = None


@app.post("/api/drift/{drift_id}/ack", tags=["Drift"])
async def acknowledge_drift(drift_id: str, request: DriftActionRequest):
    """Acknowledge a drift event"""
    drift = get_drift_event(drift_id)
    if not drift:
        raise HTTPException(status_code=404, detail="Drift event not found")
    
    updated = update_drift_status(drift_id, "acknowledged", by=request.by, notes=request.notes)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to acknowledge drift event")
    
    return updated


@app.post("/api/drift/{drift_id}/suppress", tags=["Drift"])
async def suppress_drift(drift_id: str, request: DriftActionRequest):
    """Suppress a drift event"""
    drift = get_drift_event(drift_id)
    if not drift:
        raise HTTPException(status_code=404, detail="Drift event not found")
    
    updated = update_drift_status(drift_id, "suppressed", by=request.by, notes=request.notes)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to suppress drift event")
    
    return updated


# --- Tee Requests ---

class TeeRequestCreate(BaseModel):
    pipe_id: Optional[str] = None
    candidate_id: Optional[str] = None
    target_system: str
    tee_type: str = "api_proxy"
    configuration: dict = {}
    notes: Optional[str] = None


class TeeStatusUpdate(BaseModel):
    status: str


@app.post("/api/tee/requests", tags=["Tee Requests"])
async def create_tee_request_endpoint(request: TeeRequestCreate):
    """Create a new tee request"""
    pipe_id = request.pipe_id
    
    if request.candidate_id and not pipe_id:
        candidate = get_candidate(request.candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if candidate.get("matched_pipe_id"):
            pipe_id = candidate["matched_pipe_id"]
        else:
            raise HTTPException(
                status_code=400, 
                detail="Candidate has no matched pipe. Provide pipe_id or match the candidate first."
            )
    
    if not pipe_id:
        raise HTTPException(status_code=400, detail="Either pipe_id or a matched candidate_id is required")
    
    pipe = get_pipe(pipe_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipe not found")
    
    tee_data = {
        "pipe_id": pipe_id,
        "target_system": request.target_system,
        "tee_type": request.tee_type,
        "configuration": request.configuration
    }
    
    result = create_tee_request(tee_data)
    return result


@app.get("/api/tee/requests", tags=["Tee Requests"])
async def get_tee_requests(status: Optional[str] = Query(None, description="Filter by status")):
    """List tee requests"""
    requests = list_tee_requests(status=status)
    return {"tee_requests": requests, "count": len(requests)}


@app.post("/api/tee/requests/{tee_id}/status", tags=["Tee Requests"])
async def update_tee_status(tee_id: str, request: TeeStatusUpdate):
    """Update tee request status"""
    if request.status not in ["approved", "verified"]:
        raise HTTPException(status_code=400, detail="Status must be 'approved' or 'verified'")
    
    updated = update_tee_request_status(tee_id, request.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Tee request not found")
    
    return updated
