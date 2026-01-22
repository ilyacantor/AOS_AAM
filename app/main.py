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
    mark_observation_processed
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
