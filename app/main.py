"""
AAM (Adaptive API Mesh) - FastAPI Backend

Inventory reusable data pipes and make their behavior explicit.
AOD emits intent → AAM declares pipes → DCL unifies meaning.
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
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
    get_connection,
    # AOD Handoff functions
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
from .collectors.mock import run_mock_collector
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
from .preset_config import PresetConfigLoader, EnterpriseMaturity
from .fabric_drift import FabricDriftDetector, FabricDriftType
from .adapters.factory import get_adapter_for_plane
from .adapters.base import AdapterStatus, PlaneHealth
from .pii_redaction import redact_pii_from_observation

app = FastAPI(
    title="AAM - Adaptive API Mesh",
    description="Inventory reusable data pipes and make their behavior explicit. AOD emits intent → AAM declares pipes → DCL unifies meaning.",
    version="0.1.0",
    docs_url=None,
    redoc_url=None
)

# Global component instances
preset_loader = PresetConfigLoader()
drift_detector = FabricDriftDetector()
adapter_registry: dict = {}  # plane_type -> adapter instance


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
    <div class="nav-links">
        <a href="/ui/pipes" class="nav-link{pipes_active}">Pipes</a>
        <a href="/ui/candidates" class="nav-link{candidates_active}">Candidates</a>
        <a href="/ui/drift" class="nav-link{drift_active}">Drift & Health</a>
        <a href="/ui/guide" class="nav-link{guide_active}">Guide</a>
    </div>
</nav>
"""


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
    <title>ReDoc - AAM</title>
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


# ============================================================================
# OPERATOR UI - AAM v1 Screens
# ============================================================================

UI_STYLE = """
<style>
    /* AutonomOS Color Palette */
    :root {
        --cyan-400: #22d3ee;
        --cyan-500: #0bcad9;
        --cyan-600: #0891b2;
        --green-400: #4ade80;
        --green-500: #22c55e;
        --blue-400: #60a5fa;
        --blue-500: #3b82f6;
        --purple-400: #c084fc;
        --purple-500: #a855f7;
        --red-400: #f87171;
        --red-500: #ef4444;
        --orange-400: #fb923c;
        --orange-500: #f97316;
        --yellow-400: #facc15;
        --yellow-500: #eab308;
        --slate-400: #94a3b8;
        --slate-500: #64748b;
        --slate-600: #475569;
        --slate-700: #334155;
        --slate-800: #1e293b;
        --slate-900: #0f172a;
    }
    .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 1.75rem; font-weight: 700; margin-bottom: 24px; color: #e2e8f0; }
    h2 { font-size: 1.25rem; font-weight: 600; margin-bottom: 16px; color: #e2e8f0; }
    h3 { font-size: 1rem; font-weight: 600; margin-bottom: 12px; color: #cbd5e1; }
    .page-subtitle { font-size: 0.9rem; color: #94a3b8; margin-top: -16px; margin-bottom: 24px; line-height: 1.5; }
    .controls { display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; align-items: center; }
    .btn {
        background: rgba(34, 211, 238, 0.1);
        color: var(--cyan-400);
        border: 1px solid rgba(34, 211, 238, 0.3);
        padding: 8px 16px;
        border-radius: 6px;
        font-weight: 500;
        cursor: pointer;
        font-family: inherit;
        font-size: 0.875rem;
        transition: all 0.2s ease;
        text-decoration: none;
        display: inline-block;
    }
    .btn:hover { background: rgba(34, 211, 238, 0.2); border-color: rgba(34, 211, 238, 0.5); box-shadow: 0 0 12px rgba(34, 211, 238, 0.2); }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-sm { padding: 4px 10px; font-size: 0.75rem; }
    .btn-success { color: var(--green-400); border-color: rgba(74, 222, 128, 0.3); background: rgba(74, 222, 128, 0.1); }
    .btn-success:hover { background: rgba(74, 222, 128, 0.2); border-color: rgba(74, 222, 128, 0.5); }
    .btn-warning { color: #fbbf24; border-color: rgba(251, 191, 36, 0.3); background: rgba(251, 191, 36, 0.1); }
    .btn-warning:hover { background: rgba(251, 191, 36, 0.2); border-color: rgba(251, 191, 36, 0.5); }
    .btn-danger { color: var(--red-400); border-color: rgba(248, 113, 113, 0.3); background: rgba(248, 113, 113, 0.1); }
    .btn-danger:hover { background: rgba(248, 113, 113, 0.2); border-color: rgba(248, 113, 113, 0.5); }
    .btn-warning { color: var(--orange-400); border-color: rgba(251, 146, 60, 0.3); background: rgba(251, 146, 60, 0.1); }
    .btn-warning:hover { background: rgba(251, 146, 60, 0.2); border-color: rgba(251, 146, 60, 0.5); }
    select {
        background: var(--slate-800);
        color: #ffffff;
        border: 1px solid var(--slate-700);
        padding: 8px 12px;
        border-radius: 6px;
        font-family: inherit;
        font-size: 0.875rem;
        cursor: pointer;
    }
    select:focus { outline: none; border-color: var(--cyan-400); box-shadow: 0 0 0 2px rgba(34, 211, 238, 0.1); }
    table { width: 100%; border-collapse: collapse; background: rgba(30, 41, 59, 0.6); border-radius: 8px; overflow: hidden; box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.1); }
    th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--slate-700); }
    th { background: rgba(30, 41, 59, 0.9); font-weight: 600; color: var(--slate-400); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
    tr:hover { background: rgba(34, 211, 238, 0.05); }
    tr:last-child td { border-bottom: none; }
    a { color: var(--cyan-400); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 500;
    }
    /* Status badges */
    .badge-new { background: rgba(59, 130, 246, 0.2); color: var(--blue-400); }
    .badge-triaged { background: rgba(192, 132, 252, 0.2); color: var(--purple-400); }
    .badge-connected { background: rgba(34, 197, 94, 0.2); color: var(--green-500); }
    .badge-deferred { background: rgba(148, 163, 184, 0.2); color: var(--slate-400); }
    .badge-open { background: rgba(248, 113, 113, 0.2); color: var(--red-400); }
    .badge-acknowledged { background: rgba(251, 146, 60, 0.2); color: var(--orange-400); }
    .badge-suppressed { background: rgba(148, 163, 184, 0.2); color: var(--slate-400); }
    .badge-resolved { background: rgba(34, 197, 94, 0.2); color: var(--green-500); }
    /* Severity badges */
    .badge-critical { background: rgba(239, 68, 68, 0.2); color: var(--red-500); }
    .badge-high { background: rgba(248, 113, 113, 0.2); color: var(--red-400); }
    .badge-medium { background: rgba(251, 146, 60, 0.2); color: var(--orange-400); }
    .badge-low { background: rgba(250, 204, 21, 0.2); color: var(--yellow-400); }
    /* Modality badges */
    .badge-api { background: rgba(34, 211, 238, 0.2); color: var(--cyan-400); }
    .badge-event { background: rgba(192, 132, 252, 0.2); color: var(--purple-400); }
    .badge-table { background: rgba(59, 130, 246, 0.2); color: var(--blue-400); }
    /* Special badges */
    .badge-live { background: rgba(34, 197, 94, 0.2); color: var(--green-400); animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
    .panel { background: rgba(30, 41, 59, 0.6); border: 1px solid var(--slate-700); border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.1); }
    .panel-title { font-size: 1rem; font-weight: 600; color: #e2e8f0; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--slate-700); }
    .field { margin-bottom: 12px; }
    .field-label { font-size: 0.75rem; color: var(--slate-400); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
    .field-value { color: #e2e8f0; font-size: 0.9rem; word-break: break-word; }
    .field-value.mono { font-family: 'Consolas', 'Monaco', monospace; font-size: 0.8rem; background: rgba(15, 23, 42, 0.5); padding: 8px; border-radius: 4px; }
    .grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
    .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
    .section { margin-bottom: 32px; }
    .empty-state { text-align: center; padding: 48px; color: var(--slate-500); }
    .toast { position: fixed; bottom: 24px; right: 24px; background: var(--slate-800); border: 1px solid var(--slate-700); padding: 12px 20px; border-radius: 8px; z-index: 1000; display: none; }
    .toast.success { border-color: rgba(34, 197, 94, 0.5); color: var(--green-500); }
    .toast.error { border-color: rgba(248, 113, 113, 0.5); color: var(--red-400); }
    .loading { opacity: 0.5; pointer-events: none; }
    .actions { display: flex; gap: 8px; }
    /* Stats cards */
    .stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
    .stat-card { background: rgba(30, 41, 59, 0.6); border: 1px solid var(--slate-700); border-radius: 8px; padding: 16px 20px; min-width: 140px; }
    .stat-value { font-size: 1.5rem; font-weight: 700; color: var(--cyan-400); }
    .stat-label { font-size: 0.75rem; color: var(--slate-400); text-transform: uppercase; letter-spacing: 0.05em; }
    @media (max-width: 768px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
</style>
"""

def ui_nav(active: str = "") -> str:
    """Generate navigation for operator UI screens"""
    def active_class(page: str) -> str:
        return " active" if page == active else ""
    return f"""
<nav class="nav">
    <div class="nav-links">
        <a href="/ui/topology" class="nav-link{active_class('topology')}" data-testid="nav-topology">Topology</a>
        <a href="/ui/pipes" class="nav-link{active_class('pipes')}" data-testid="nav-pipes">Pipes</a>
        <a href="/ui/candidates" class="nav-link{active_class('candidates')}" data-testid="nav-candidates">Candidates</a>
        <a href="/ui/drift" class="nav-link{active_class('drift')}" data-testid="nav-drift">Drift & Health</a>
        <a href="/ui/guide" class="nav-link{active_class('guide')}" data-testid="nav-guide">Guide</a>
    </div>
</nav>
"""


def aod_run_banner() -> str:
    """Generate AOD run information banner with Fetch AOD Data button"""
    latest_run = get_latest_aod_run()
    
    fetch_script = """
<script>
var _fetchRunning = false;
async function fetchAodData() {
    if (_fetchRunning) return;
    _fetchRunning = true;
    var btn = document.getElementById('fetch-aod-btn');
    btn.textContent = 'Fetching...';
    btn.disabled = true;
    btn.style.opacity = '0.5';
    try {
        var res = await fetch('/api/handoff/aod/fetch', { method: 'POST' });
        var data = await res.json();
        if (res.ok) {
            window.location.reload();
        } else {
            btn.textContent = data.detail || 'No AOD data stored';
            btn.style.opacity = '1';
            _fetchRunning = false;
        }
    } catch(e) {
        btn.textContent = 'Fetch Failed';
        btn.disabled = false;
        btn.style.opacity = '1';
        _fetchRunning = false;
    }
}
</script>"""
    
    fetch_btn = '<button class="btn btn-sm" style="font-size: 0.75rem; background: rgba(251, 146, 60, 0.2); border-color: rgba(251, 146, 60, 0.5); color: #fb923c;" onclick="fetchAodData()" data-testid="button-fetch-aod" id="fetch-aod-btn">Fetch AOD Data</button>'
    
    if not latest_run:
        return f"""
<div style="background: rgba(251, 146, 60, 0.1); border: 1px solid rgba(251, 146, 60, 0.3); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
    <div>
        <strong style="color: #fb923c;">No AOD Run Loaded</strong>
    </div>
    {fetch_btn}
</div>
{fetch_script}
"""
    
    aod_run_id = latest_run["aod_run_id"]
    snapshot_name = latest_run.get("snapshot_name")
    candidates = latest_run["candidates_accepted"]
    timestamp = latest_run["handoff_timestamp"]
    
    display_name = f'<strong style="color: #f0abfc;">{snapshot_name}</strong> <span style="color: #64748b; font-size: 0.8rem;">({aod_run_id})</span>' if snapshot_name else f'<span style="font-family: monospace;">{aod_run_id}</span>'
    
    return f"""
<div style="background: rgba(34, 211, 238, 0.1); border: 1px solid rgba(34, 211, 238, 0.3); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
    <div>
        <strong style="color: #22d3ee;">AOD Run:</strong> {display_name}
        <span style="margin-left: 20px; color: #94a3b8;">|</span>
        <span style="margin-left: 20px;"><strong>{candidates}</strong> pipes</span>
        <span style="margin-left: 20px; color: #94a3b8; font-size: 0.85rem;">{timestamp[:19] if timestamp else 'N/A'}</span>
    </div>
    <div style="display: flex; gap: 8px; align-items: center;">
        {fetch_btn}
        <a href="/ui/reconcile/{aod_run_id}" class="btn btn-sm" style="font-size: 0.75rem;" data-testid="link-reconcile">Reconcile</a>
    </div>
</div>
{fetch_script}
"""


@app.get("/ui/pipes", response_class=HTMLResponse, include_in_schema=False)
async def ui_pipes_list(
    filter: Optional[str] = Query("all")
):
    """Pipes Inventory Screen"""
    all_pipes = list_pipes()
    
    # Single filter for asset classes
    if filter == "all":
        pipes = all_pipes
    elif filter in ["IPAAS", "API_GATEWAY", "EVENT_BUS", "DATA_WAREHOUSE"]:
        pipes = [p for p in all_pipes if p.get("fabric_plane") == filter]
    else:
        # Filter by source system
        pipes = [p for p in all_pipes if p.get("source_system") == filter]
    
    source_systems = sorted(set(p.get("source_system", "") for p in all_pipes if p.get("source_system")))
    fabric_planes = ["IPAAS", "API_GATEWAY", "EVENT_BUS", "DATA_WAREHOUSE"]
    
    all_drift = list_all_drift_events()
    drift_by_pipe = {}
    for d in all_drift:
        pid = d.get("pipe_id")
        if pid:
            if pid not in drift_by_pipe:
                drift_by_pipe[pid] = {"open": 0, "total": 0}
            drift_by_pipe[pid]["total"] += 1
            if d.get("status") == "open":
                drift_by_pipe[pid]["open"] += 1
    
    fabric_plane_colors = {
        "IPAAS": "#22d3ee",
        "API_GATEWAY": "#a78bfa",
        "EVENT_BUS": "#f97316",
        "DATA_WAREHOUSE": "#10b981"
    }
    
    rows_html = ""
    for p in pipes:
        pipe_id = p.get("pipe_id", "")
        entity_scope = p.get("entity_scope", [])
        trust_labels = p.get("trust_labels", [])
        owner_signals = p.get("owner_signals", [])
        pipe_fabric = p.get("fabric_plane", "API_GATEWAY")
        fabric_color = fabric_plane_colors.get(pipe_fabric, "#64748b")
        drift_info = drift_by_pipe.get(pipe_id, {"open": 0, "total": 0})
        drift_status = f"{drift_info['open']} open" if drift_info['open'] > 0 else "OK"
        drift_class = "badge-open" if drift_info['open'] > 0 else "badge-connected"
        
        rows_html += f"""
        <tr data-testid="pipe-row-{pipe_id}">
            <td><span class="fabric-badge" style="background:{fabric_color}20;color:{fabric_color};border:1px solid {fabric_color}40;">{pipe_fabric}</span></td>
            <td><a href="/ui/pipes/{pipe_id}" data-testid="pipe-link-{pipe_id}">{p.get('display_name', 'Unnamed')}</a></td>
            <td>{p.get('source_system', '-')}</td>
            <td>{p.get('modality', '-')}</td>
            <td>{', '.join(entity_scope[:3])}{'...' if len(entity_scope) > 3 else ''}</td>
            <td>{len(trust_labels)}</td>
            <td><span class="badge {drift_class}">{drift_status}</span></td>
            <td>{', '.join(owner_signals[:2]) if owner_signals else '-'}</td>
        </tr>
        """
    
    if not pipes:
        rows_html = '<tr><td colspan="8" class="empty-state">No pipes found. Load a preset or run Mock Collector to generate sample data.</td></tr>'
    
    # Build single combined filter dropdown
    filter_options = '<option value="all"' + (' selected' if filter == "all" else '') + '>All</option>'
    # Add fabric types
    for f in fabric_planes:
        filter_options += f'<option value="{f}"' + (' selected' if filter == f else '') + f'>{f.replace("_", " ").title()}</option>'
    # Add source systems
    if source_systems:
        filter_options += '<optgroup label="Sources">'
        for s in source_systems:
            filter_options += f'<option value="{s}"' + (' selected' if filter == s else '') + f'>{s}</option>'
        filter_options += '</optgroup>'
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Pipes - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
    <style>
        .fabric-badge {{
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .preset-section {{
            background: rgba(34, 211, 238, 0.1);
            border: 1px solid rgba(34, 211, 238, 0.3);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
        }}
        .preset-section h3 {{
            margin: 0 0 12px 0;
            font-size: 0.9rem;
            color: #22d3ee;
        }}
        .preset-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
        }}
        .preset-card {{
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .preset-card:hover {{
            border-color: #22d3ee;
            background: rgba(34, 211, 238, 0.1);
        }}
        .preset-card h4 {{
            margin: 0 0 4px 0;
            font-size: 0.85rem;
        }}
        .preset-card p {{
            margin: 0;
            font-size: 0.7rem;
            color: #94a3b8;
        }}
        .stats-bar {{
            display: flex;
            gap: 24px;
            margin-bottom: 16px;
            padding: 12px 16px;
            background: rgba(30, 41, 59, 0.5);
            border-radius: 8px;
        }}
        .data-source-toggle {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
            padding: 12px 16px;
            background: rgba(30, 41, 59, 0.6);
            border: 1px solid #334155;
            border-radius: 8px;
        }}
        .toggle-label {{
            font-size: 0.85rem;
            color: #94a3b8;
            font-weight: 500;
        }}
        .toggle-group {{
            display: flex;
            background: rgba(15, 23, 42, 0.8);
            border-radius: 6px;
            overflow: hidden;
            border: 1px solid #334155;
        }}
        .toggle-btn {{
            padding: 8px 16px;
            font-size: 0.8rem;
            font-weight: 500;
            border: none;
            background: transparent;
            color: #94a3b8;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .toggle-btn.active {{
            background: #22d3ee;
            color: #0f172a;
        }}
        .toggle-btn:hover:not(.active) {{
            background: rgba(34, 211, 238, 0.1);
            color: #e2e8f0;
        }}
        .source-indicator {{
            font-size: 0.75rem;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 500;
        }}
        .source-indicator.mock {{
            background: rgba(167, 139, 250, 0.2);
            color: #a78bfa;
            border: 1px solid rgba(167, 139, 250, 0.3);
        }}
        .source-indicator.aod {{
            background: rgba(34, 211, 238, 0.2);
            color: #22d3ee;
            border: 1px solid rgba(34, 211, 238, 0.3);
        }}
        .stat-item {{
            text-align: center;
        }}
        .stat-value {{
            font-size: 1.5rem;
            font-weight: 700;
            color: #22d3ee;
        }}
        .stat-label {{
            font-size: 0.7rem;
            color: #94a3b8;
            text-transform: uppercase;
        }}
        .modal-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }}
        .modal-overlay.active {{
            display: flex;
        }}
        .modal-box {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 24px;
            max-width: 400px;
            width: 90%;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
        }}
        .modal-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 12px;
            color: #f1f5f9;
        }}
        .modal-message {{
            font-size: 0.9rem;
            color: #94a3b8;
            margin-bottom: 20px;
            line-height: 1.5;
        }}
        .modal-actions {{
            display: flex;
            gap: 12px;
            justify-content: flex-end;
        }}
        .modal-btn {{
            padding: 8px 20px;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
        }}
        .modal-btn-cancel {{
            background: #334155;
            color: #94a3b8;
        }}
        .modal-btn-cancel:hover {{
            background: #475569;
        }}
        .modal-btn-confirm {{
            background: #22d3ee;
            color: #0f172a;
        }}
        .modal-btn-confirm:hover {{
            background: #06b6d4;
        }}
    </style>
</head>
<body>
    {ui_nav('pipes')}
    <div class="container">
        <h1>Pipes</h1>
        <p class="page-subtitle">All declared data pipes with metadata, health status, and ownership. These are your canonical integration endpoints.</p>
        
        {aod_run_banner()}
        
        <div class="preset-section" data-testid="preset-section">
            <h3>Load Enterprise Preset</h3>
            <div class="preset-grid" id="preset-grid">Loading presets...</div>
        </div>
        
        <div class="data-source-toggle" data-testid="data-source-toggle">
            <span class="toggle-label">Generate Test Data:</span>
            <div class="toggle-group">
                <button class="toggle-btn active" id="toggle-mock" data-testid="toggle-mock" onclick="setDataSource('mock')">Mock Pipes</button>
                <button class="toggle-btn" id="toggle-aod" data-testid="toggle-aod" onclick="setDataSource('aod')">AOD Candidates</button>
            </div>
            <span class="source-indicator mock" id="source-indicator" data-testid="source-indicator">Creates sample pipes directly</span>
        </div>
        <div id="aod-note" style="display:none; padding: 12px; background: rgba(34, 211, 238, 0.1); border: 1px solid rgba(34, 211, 238, 0.3); border-radius: 8px; margin-bottom: 16px; font-size: 0.85rem; color: #94a3b8;">
            <strong style="color: #22d3ee;">Note:</strong> AOD handoffs create <strong>Candidates</strong>, not Pipes. 
            Candidates appear in the <a href="/ui/candidates" style="color: #22d3ee;">Candidates tab</a> and can be matched to create Pipes.
        </div>
        
        <div class="stats-bar" id="stats-bar" data-testid="stats-bar">
            <div class="stat-item"><div class="stat-value" id="stat-total">{len(pipes)}</div><div class="stat-label">Total Pipes</div></div>
        </div>
        
        <div class="controls">
            <button class="btn" id="btn-run-collector" data-testid="btn-run-collector">Run Mock Collector</button>
            <button class="btn" id="btn-export-dcl" data-testid="btn-export-dcl">Export to DCL</button>
            <select id="filter" data-testid="filter" onchange="applyFilter()">{filter_options}</select>
        </div>
        <table data-testid="pipes-table">
            <thead>
                <tr>
                    <th>Fabric</th>
                    <th>Pipe Name</th>
                    <th>Source System</th>
                    <th>Modality</th>
                    <th>Entity Scope</th>
                    <th>Trust Labels</th>
                    <th>Drift</th>
                    <th>Owner</th>
                </tr>
            </thead>
            <tbody id="pipes-body">{rows_html}</tbody>
        </table>
    </div>
    <div id="toast" class="toast"></div>
    
    <div id="confirm-modal" class="modal-overlay" data-testid="confirm-modal">
        <div class="modal-box">
            <div class="modal-title" id="modal-title">Confirm Action</div>
            <div class="modal-message" id="modal-message">Are you sure?</div>
            <div class="modal-actions">
                <button class="modal-btn modal-btn-cancel" id="modal-cancel" data-testid="modal-cancel">Cancel</button>
                <button class="modal-btn modal-btn-confirm" id="modal-confirm" data-testid="modal-confirm">Continue</button>
            </div>
        </div>
    </div>
    
    <script>
        let modalResolve = null;
        
        function showConfirmModal(title, message) {{
            return new Promise((resolve) => {{
                modalResolve = resolve;
                document.getElementById('modal-title').textContent = title;
                document.getElementById('modal-message').textContent = message;
                document.getElementById('confirm-modal').classList.add('active');
            }});
        }}
        
        document.getElementById('modal-cancel').addEventListener('click', () => {{
            document.getElementById('confirm-modal').classList.remove('active');
            if (modalResolve) modalResolve(false);
        }});
        
        document.getElementById('modal-confirm').addEventListener('click', () => {{
            document.getElementById('confirm-modal').classList.remove('active');
            if (modalResolve) modalResolve(true);
        }});
        
        document.getElementById('confirm-modal').addEventListener('click', (e) => {{
            if (e.target.id === 'confirm-modal') {{
                document.getElementById('confirm-modal').classList.remove('active');
                if (modalResolve) modalResolve(false);
            }}
        }});
        
        function showToast(message, type) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast ' + type;
            toast.style.display = 'block';
            setTimeout(() => toast.style.display = 'none', 3000);
        }}
        
        function applyFilter() {{
            const filter = document.getElementById('filter').value;
            const params = new URLSearchParams();
            if (filter && filter !== 'all') params.set('filter', filter);
            window.location.href = '/ui/pipes' + (params.toString() ? '?' + params.toString() : '');
        }}
        
        async function loadPresets() {{
            try {{
                const res = await fetch('/api/presets');
                const data = await res.json();
                const grid = document.getElementById('preset-grid');
                if (data.presets && data.presets.length > 0) {{
                    grid.innerHTML = data.presets.map(p => `
                        <div class="preset-card" onclick="loadPreset('${{p.preset_id}}')" data-testid="preset-${{p.preset_id}}">
                            <h4>${{p.name}}</h4>
                            <p>${{p.pipe_count}} pipes, ${{p.candidate_count}} candidates</p>
                        </div>
                    `).join('');
                }} else {{
                    grid.innerHTML = '<p>No presets available</p>';
                }}
            }} catch (e) {{
                document.getElementById('preset-grid').innerHTML = '<p>Failed to load presets</p>';
            }}
        }}
        
        async function loadPreset(presetId) {{
            const confirmed = await showConfirmModal(
                'Load Preset',
                'This will replace all existing data with the preset. Any current pipes, candidates, and drift events will be cleared.'
            );
            if (!confirmed) return;
            try {{
                const res = await fetch('/api/presets/' + presetId + '/load', {{ method: 'POST' }});
                const data = await res.json();
                if (res.ok) {{
                    showToast(data.message, 'success');
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
        }}
        
        loadPresets();
        
        let currentDataSource = localStorage.getItem('aam_data_source') || 'mock';
        
        function setDataSource(source, persist = true) {{
            currentDataSource = source;
            if (persist) {{
                localStorage.setItem('aam_data_source', source);
            }}
            const mockBtn = document.getElementById('toggle-mock');
            const aodBtn = document.getElementById('toggle-aod');
            const indicator = document.getElementById('source-indicator');
            const mockCollectorBtn = document.getElementById('btn-run-collector');
            
            const aodNote = document.getElementById('aod-note');
            
            if (source === 'mock') {{
                mockBtn.classList.add('active');
                aodBtn.classList.remove('active');
                indicator.className = 'source-indicator mock';
                indicator.textContent = 'Creates sample pipes directly';
                mockCollectorBtn.style.display = 'inline-block';
                aodNote.style.display = 'none';
            }} else {{
                aodBtn.classList.add('active');
                mockBtn.classList.remove('active');
                indicator.className = 'source-indicator aod';
                indicator.textContent = 'Creates candidates for triage';
                mockCollectorBtn.style.display = 'none';
                aodNote.style.display = 'block';
            }}
        }}
        
        // Initialize toggle state from localStorage on page load
        setDataSource(currentDataSource, false);
        
        document.getElementById('btn-run-collector').addEventListener('click', async function() {{
            this.disabled = true;
            this.textContent = 'Running...';
            try {{
                const res = await fetch('/api/collect/mock/run', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: '{{}}' }});
                const data = await res.json();
                if (res.ok) {{
                    showToast('Collector ran: ' + data.observations_created + ' observations created', 'success');
                    const inferRes = await fetch('/api/aam/infer', {{ method: 'POST' }});
                    const inferData = await inferRes.json();
                    showToast('Inferred ' + inferData.pipes_created + ' pipes', 'success');
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
            this.disabled = false;
            this.textContent = 'Run Mock Collector';
        }});
        
        document.getElementById('btn-export-dcl').addEventListener('click', async function() {{
            try {{
                const res = await fetch('/api/export/dcl/declared-pipes');
                const data = await res.json();
                const blob = new Blob([JSON.stringify(data, null, 2)], {{ type: 'application/json' }});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'dcl-export-' + new Date().toISOString().slice(0,10) + '.json';
                a.click();
                showToast('Exported ' + data.pipe_count + ' pipes', 'success');
            }} catch (e) {{
                showToast('Export failed: ' + e.message, 'error');
            }}
        }});
    </script>
</body>
</html>
""")


@app.get("/ui/pipes/{pipe_id}", response_class=HTMLResponse, include_in_schema=False)
async def ui_pipe_detail(pipe_id: str):
    """Pipe Detail Screen"""
    pipe = get_pipe(pipe_id)
    if not pipe:
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Pipe Not Found - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
</head>
<body>
    {ui_nav('pipes')}
    <div class="container">
        <h1>Pipe Not Found</h1>
        <p>The pipe with ID "{pipe_id}" was not found.</p>
        <a href="/ui/pipes" class="btn">Back to Pipes</a>
    </div>
</body>
</html>
""", status_code=404)
    
    versions = get_pipe_versions(pipe_id)
    drift_events = get_drift_events(pipe_id)
    
    endpoint_ref = pipe.get("endpoint_ref", {})
    provenance = pipe.get("provenance", {})
    schema_info = pipe.get("schema_info")
    entity_scope = pipe.get("entity_scope", [])
    identity_keys = pipe.get("identity_keys", [])
    trust_labels = pipe.get("trust_labels", [])
    owner_signals = pipe.get("owner_signals", [])
    
    trust_labels_html = ''.join(f'<span class="badge badge-connected" style="margin-right:4px;">{t}</span>' for t in trust_labels) or '-'
    
    drift_rows = ""
    for d in drift_events:
        drift_rows += f"""
        <tr>
            <td>{d.get('drift_type', '-')}</td>
            <td><span class="badge badge-{d.get('severity', 'medium')}">{d.get('severity', 'medium')}</span></td>
            <td><span class="badge badge-{d.get('status', 'open')}">{d.get('status', 'open')}</span></td>
            <td>{d.get('detected_at', '-')[:16] if d.get('detected_at') else '-'}</td>
            <td style="font-size:0.75rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;">{d.get('old_value', '-')[:30]}... → {d.get('new_value', '-')[:30]}...</td>
        </tr>
        """
    if not drift_events:
        drift_rows = '<tr><td colspan="5" class="empty-state">No drift events</td></tr>'
    
    versions_html = ""
    for v in versions[:5]:
        versions_html += f"<div style='margin-bottom:8px;'><strong>v{v.get('version', '?')}</strong> - {v.get('created_at', '')[:16]}</div>"
    if not versions:
        versions_html = "<div class='empty-state'>No versions</div>"
    
    import json as json_module
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>{pipe.get('display_name', 'Pipe')} - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
</head>
<body>
    {ui_nav('pipes')}
    <div class="container">
        <div class="controls">
            <a href="/ui/pipes" class="btn" data-testid="btn-back">← Back to Pipes</a>
            <button class="btn" id="btn-recompute" data-testid="btn-recompute">Recompute Declaration</button>
            <button class="btn" id="btn-create-tee" data-testid="btn-create-tee">Create Tee Request</button>
        </div>
        <h1 data-testid="pipe-title">{pipe.get('display_name', 'Unnamed Pipe')}</h1>
        
        <div class="grid-2">
            <div class="panel">
                <div class="panel-title">Pipe Info</div>
                <div class="field">
                    <div class="field-label">Pipe ID</div>
                    <div class="field-value mono" data-testid="field-pipe-id">{pipe_id}</div>
                </div>
                <div class="field">
                    <div class="field-label">Fabric Plane</div>
                    <div class="field-value" style="color: #22d3ee; font-weight: 600;">{pipe.get('fabric_plane', 'API_GATEWAY')}</div>
                </div>
                <div class="field">
                    <div class="field-label">Source System</div>
                    <div class="field-value">{pipe.get('source_system', '-')}</div>
                </div>
                <div class="field">
                    <div class="field-label">Transport Kind</div>
                    <div class="field-value">{pipe.get('transport_kind', '-')}</div>
                </div>
                <div class="field">
                    <div class="field-label">Modality</div>
                    <div class="field-value">{pipe.get('modality', '-')}</div>
                </div>
                <div class="field">
                    <div class="field-label">Change Semantics</div>
                    <div class="field-value">{pipe.get('change_semantics', '-')}</div>
                </div>
                <div class="field">
                    <div class="field-label">Freshness</div>
                    <div class="field-value">{pipe.get('freshness', '-')}</div>
                </div>
                <div class="field">
                    <div class="field-label">Version</div>
                    <div class="field-value">v{pipe.get('version', 1)}</div>
                </div>
            </div>
            
            <div class="panel">
                <div class="panel-title">Endpoint Reference</div>
                <div class="field-value mono" data-testid="field-endpoint">{json_module.dumps(endpoint_ref, indent=2) if endpoint_ref else 'No endpoint reference'}</div>
            </div>
        </div>
        
        <div class="grid-2">
            <div class="panel">
                <div class="panel-title">Provenance</div>
                <div class="field">
                    <div class="field-label">Discovered By</div>
                    <div class="field-value">{provenance.get('discovered_by', '-')}</div>
                </div>
                <div class="field">
                    <div class="field-label">Discovered At</div>
                    <div class="field-value">{provenance.get('discovered_at', '-')}</div>
                </div>
                <div class="field">
                    <div class="field-label">Lineage Hints</div>
                    <div class="field-value">{', '.join(provenance.get('lineage_hints', [])) or '-'}</div>
                </div>
            </div>
            
            <div class="panel">
                <div class="panel-title">Entity & Identity</div>
                <div class="field">
                    <div class="field-label">Entity Scope</div>
                    <div class="field-value">{', '.join(entity_scope) or '-'}</div>
                </div>
                <div class="field">
                    <div class="field-label">Identity Keys</div>
                    <div class="field-value">{', '.join(identity_keys) or '-'}</div>
                </div>
                <div class="field">
                    <div class="field-label">Owner Signals</div>
                    <div class="field-value">{', '.join(owner_signals) or '-'}</div>
                </div>
            </div>
        </div>
        
        <div class="grid-2">
            <div class="panel">
                <div class="panel-title">Trust Labels</div>
                <div>{trust_labels_html}</div>
            </div>
            
            <div class="panel">
                <div class="panel-title">Schema Info</div>
                {f'<div class="field-value mono">{json_module.dumps(schema_info, indent=2)}</div>' if schema_info else '<div class="empty-state">No schema info</div>'}
            </div>
        </div>
        
        <div class="grid-2">
            <div class="panel">
                <div class="panel-title">Version History</div>
                {versions_html}
            </div>
            
            <div class="panel">
                <div class="panel-title">Drift Timeline</div>
                <table>
                    <thead>
                        <tr><th>Type</th><th>Severity</th><th>Status</th><th>Detected</th><th>Evidence</th></tr>
                    </thead>
                    <tbody>{drift_rows}</tbody>
                </table>
            </div>
        </div>
    </div>
    <div id="toast" class="toast"></div>
    <script>
        function showToast(message, type) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast ' + type;
            toast.style.display = 'block';
            setTimeout(() => toast.style.display = 'none', 3000);
        }}
        
        document.getElementById('btn-recompute').addEventListener('click', async function() {{
            this.disabled = true;
            this.textContent = 'Recomputing...';
            try {{
                const res = await fetch('/api/aam/infer', {{ method: 'POST' }});
                const data = await res.json();
                showToast('Recomputed: ' + data.pipes_created + ' pipes processed', 'success');
                setTimeout(() => location.reload(), 1500);
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
            this.disabled = false;
            this.textContent = 'Recompute Declaration';
        }});
        
        document.getElementById('btn-create-tee').addEventListener('click', async function() {{
            this.disabled = true;
            try {{
                const res = await fetch('/api/tee/requests', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ pipe_id: '{pipe_id}', target_system: 'default', tee_type: 'api_proxy' }})
                }});
                const data = await res.json();
                if (res.ok) {{
                    showToast('Tee request created: ' + data.tee_id, 'success');
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
            this.disabled = false;
        }});
    </script>
</body>
</html>
""")


@app.get("/ui/candidates", response_class=HTMLResponse, include_in_schema=False)
async def ui_candidates_list(
    view: Optional[str] = Query("sors_fabrics", description="View filter: all, sors, fabrics, sors_fabrics, ipaas, warehouse, gateway, eventbus")
):
    """Candidates Screen"""
    all_candidates = list_candidates()
    
    # Define category groups
    sor_categories = {"crm", "erp", "hcm", "idp", "itsm"}
    fabric_type_map = {
        "ipaas": {"ipaas"},
        "warehouse": {"data warehouse", "warehouse", "data"},
        "gateway": {"api gateway", "gateway"},
        "eventbus": {"event bus", "eventbus", "stream"}
    }
    all_fabric_categories = set().union(*fabric_type_map.values())
    
    # Filter based on view mode
    if view == "all":
        candidates = all_candidates
    elif view == "sors":
        candidates = [c for c in all_candidates if c.get("category", "").lower() in sor_categories]
    elif view == "fabrics":
        candidates = [c for c in all_candidates if c.get("category", "").lower() in all_fabric_categories]
    elif view == "sors_fabrics":
        combined = sor_categories | all_fabric_categories
        candidates = [c for c in all_candidates if c.get("category", "").lower() in combined]
    elif view in fabric_type_map:
        candidates = [c for c in all_candidates if c.get("category", "").lower() in fabric_type_map[view]]
    else:
        candidates = all_candidates
    
    rows_html = ""
    for c in candidates:
        candidate_id = c.get("candidate_id", "")
        findings = c.get("findings", [])
        status_val = c.get("status", "new")
        matched_pipe = c.get("matched_pipe_id")
        priority = c.get("priority_score")
        
        match_btn = f'<button class="btn btn-sm" onclick="matchCandidate(\'{candidate_id}\')">Match</button>' if status_val not in ['connected', 'deferred'] else ''
        defer_btn = f'<button class="btn btn-sm btn-danger" onclick="deferCandidate(\'{candidate_id}\')">Defer</button>' if status_val not in ['connected', 'deferred'] else ''
        tee_btn = f'<button class="btn btn-sm" onclick="createTee(\'{candidate_id}\')">Tee</button>' if status_val == 'connected' else ''
        
        rows_html += f"""
        <tr data-testid="candidate-row-{candidate_id}">
            <td>{c.get('asset_key', '-')}</td>
            <td>{c.get('vendor_name', '-')}</td>
            <td>{c.get('category', '-')}</td>
            <td>{priority if priority else '-'}</td>
            <td><span class="badge badge-{status_val}">{status_val}</span></td>
            <td>{f'<a href="/ui/pipes/{matched_pipe}">{matched_pipe[:8]}...</a>' if matched_pipe else '-'}</td>
            <td>{len(findings)}</td>
            <td class="actions">{match_btn}{defer_btn}{tee_btn}</td>
        </tr>
        """
    
    if not candidates:
        rows_html = '<tr><td colspan="8" class="empty-state">No candidates found. Create candidates via the API.</td></tr>'
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Candidates - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
</head>
<body>
    {ui_nav('candidates')}
    <div class="container">
        <h1>Candidates</h1>
        <p class="page-subtitle">Connection requests from AOD discovery. Triage, match to pipes, or defer candidates that don't fit your integration mesh.</p>
        
        {aod_run_banner()}
        
        <div class="stats" style="margin-bottom: 16px;">
            <div class="stat-card">
                <div class="stat-value">{len(candidates)}</div>
                <div class="stat-label">Showing</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(all_candidates)}</div>
                <div class="stat-label">Total</div>
            </div>
        </div>
        <div class="controls">
            <select id="filter-view" data-testid="filter-view" onchange="applyFilter()">
                <option value="all"{" selected" if view == "all" else ""}>All</option>
                <option value="sors"{" selected" if view == "sors" else ""}>SORs</option>
                <option value="fabrics"{" selected" if view == "fabrics" else ""}>Fabrics</option>
                <option value="sors_fabrics"{" selected" if view == "sors_fabrics" else ""}>SORs + Fabrics</option>
                <option value="ipaas"{" selected" if view == "ipaas" else ""}>iPaaS</option>
                <option value="warehouse"{" selected" if view == "warehouse" else ""}>Warehouse</option>
                <option value="gateway"{" selected" if view == "gateway" else ""}>API Gateway</option>
                <option value="eventbus"{" selected" if view == "eventbus" else ""}>Event Bus</option>
            </select>
        </div>
        <table data-testid="candidates-table">
            <thead>
                <tr>
                    <th>Asset Key</th>
                    <th>Vendor</th>
                    <th>Category</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Matched Pipe</th>
                    <th>Findings</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="candidates-body">{rows_html}</tbody>
        </table>
    </div>
    <div id="toast" class="toast"></div>

    <!-- Match Modal -->
    <div id="match-modal" class="modal" style="display:none;">
        <div class="modal-content">
            <div class="modal-header">
                <h3>Match to Pipe</h3>
                <button class="close-btn" onclick="closeMatchModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="field">
                    <label class="field-label">Select a Pipe</label>
                    <select id="pipe-select" class="modal-select">
                        <option value="">Loading pipes...</option>
                    </select>
                </div>
                <p style="color: var(--slate-400); font-size: 0.85rem; margin-top: 12px;">
                    Select a pipe to link this candidate to, or choose "Auto-match" to let the system find the best match.
                </p>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeMatchModal()">Cancel</button>
                <button class="btn btn-success" onclick="confirmMatch()">Match</button>
            </div>
        </div>
    </div>

    <!-- Defer Modal -->
    <div id="defer-modal" class="modal" style="display:none;">
        <div class="modal-content">
            <div class="modal-header">
                <h3>Defer Candidate</h3>
                <button class="close-btn" onclick="closeDeferModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="field">
                    <label class="field-label">Reason for Deferring</label>
                    <textarea id="defer-reason" class="modal-textarea" rows="3" placeholder="e.g., Waiting for vendor approval, Low priority, etc."></textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeDeferModal()">Cancel</button>
                <button class="btn btn-warning" onclick="confirmDefer()">Defer</button>
            </div>
        </div>
    </div>

    <style>
        .modal {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }}
        .modal-content {{
            background: var(--slate-800);
            border: 1px solid var(--slate-700);
            border-radius: 12px;
            width: 90%;
            max-width: 500px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }}
        .modal-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid var(--slate-700);
        }}
        .modal-header h3 {{
            margin: 0;
            color: var(--cyan-400);
        }}
        .modal-header .close-btn {{
            background: none;
            border: none;
            color: var(--slate-400);
            font-size: 1.5rem;
            cursor: pointer;
            padding: 0;
            line-height: 1;
        }}
        .modal-header .close-btn:hover {{
            color: #fff;
        }}
        .modal-body {{
            padding: 20px;
        }}
        .modal-footer {{
            display: flex;
            justify-content: flex-end;
            gap: 12px;
            padding: 16px 20px;
            border-top: 1px solid var(--slate-700);
        }}
        .modal-select, .modal-textarea {{
            width: 100%;
            padding: 10px 12px;
            background: var(--slate-900);
            border: 1px solid var(--slate-600);
            border-radius: 6px;
            color: #fff;
            font-size: 0.95rem;
        }}
        .modal-select:focus, .modal-textarea:focus {{
            outline: none;
            border-color: var(--cyan-400);
        }}
        .modal-textarea {{
            resize: vertical;
            font-family: inherit;
        }}
    </style>

    <script>
        let currentCandidateId = null;

        function showToast(message, type) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast ' + type;
            toast.style.display = 'block';
            setTimeout(() => toast.style.display = 'none', 3000);
        }}

        function applyFilter() {{
            const view = document.getElementById('filter-view').value;
            const params = new URLSearchParams();
            if (view) params.set('view', view);
            window.location.href = '/ui/candidates' + (params.toString() ? '?' + params.toString() : '');
        }}

        async function matchCandidate(candidateId) {{
            currentCandidateId = candidateId;
            const select = document.getElementById('pipe-select');
            select.innerHTML = '<option value="">Loading...</option>';
            document.getElementById('match-modal').style.display = 'flex';

            // Fetch pipes
            try {{
                const res = await fetch('/api/pipes');
                const data = await res.json();
                const pipes = data.pipes || [];

                let options = '<option value="">(Auto-match - let system choose)</option>';
                pipes.forEach(p => {{
                    const name = p.display_name || p.pipe_id;
                    const source = p.source_system || 'Unknown';
                    options += `<option value="${{p.pipe_id}}">${{name}} (${{source}})</option>`;
                }});
                select.innerHTML = options;
            }} catch (e) {{
                select.innerHTML = '<option value="">(Auto-match - let system choose)</option>';
                showToast('Could not load pipes', 'error');
            }}
        }}

        function closeMatchModal() {{
            document.getElementById('match-modal').style.display = 'none';
            currentCandidateId = null;
        }}

        async function confirmMatch() {{
            if (!currentCandidateId) return;
            const pipeId = document.getElementById('pipe-select').value;

            try {{
                const body = pipeId ? {{ pipe_id: pipeId }} : {{}};
                const res = await fetch('/api/candidates/' + currentCandidateId + '/match', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(body)
                }});
                const data = await res.json();
                if (res.ok) {{
                    closeMatchModal();
                    showToast('Matched to pipe: ' + data.matched_pipe_id, 'success');
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Match failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
        }}

        function deferCandidate(candidateId) {{
            currentCandidateId = candidateId;
            document.getElementById('defer-reason').value = '';
            document.getElementById('defer-modal').style.display = 'flex';
        }}

        function closeDeferModal() {{
            document.getElementById('defer-modal').style.display = 'none';
            currentCandidateId = null;
        }}

        async function confirmDefer() {{
            if (!currentCandidateId) return;
            const reason = document.getElementById('defer-reason').value.trim();
            if (!reason) {{
                showToast('Please enter a reason', 'error');
                return;
            }}

            try {{
                const res = await fetch('/api/candidates/' + currentCandidateId + '/defer', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ reason: reason }})
                }});
                const data = await res.json();
                if (res.ok) {{
                    closeDeferModal();
                    showToast('Candidate deferred', 'success');
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
        }}

        async function createTee(candidateId) {{
            try {{
                const res = await fetch('/api/tee/requests', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ candidate_id: candidateId, target_system: 'default', tee_type: 'api_proxy' }})
                }});
                const data = await res.json();
                if (res.ok) {{
                    showToast('Tee request created: ' + data.tee_id, 'success');
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
        }}

        // Close modals on escape key
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') {{
                closeMatchModal();
                closeDeferModal();
            }}
        }});

        // Close modals on backdrop click
        document.getElementById('match-modal').addEventListener('click', function(e) {{
            if (e.target === this) closeMatchModal();
        }});
        document.getElementById('defer-modal').addEventListener('click', function(e) {{
            if (e.target === this) closeDeferModal();
        }});
    </script>
</body>
</html>
""")


@app.get("/ui/guide", response_class=HTMLResponse, include_in_schema=False)
async def ui_guide():
    """User Guide Screen"""
    guide_style = """
    <style>
        .guide-container { max-width: 900px; margin: 0 auto; padding: 32px 24px; }
        .guide-section { margin-bottom: 40px; }
        .guide-section h2 { 
            color: var(--cyan-400); 
            border-bottom: 1px solid var(--slate-700); 
            padding-bottom: 8px; 
            margin-bottom: 16px;
        }
        .guide-section h3 { color: #e2e8f0; margin-top: 24px; margin-bottom: 12px; }
        .guide-section p { color: var(--slate-400); line-height: 1.7; margin-bottom: 12px; }
        .guide-section ul, .guide-section ol { color: var(--slate-400); padding-left: 24px; margin-bottom: 16px; }
        .guide-section li { margin-bottom: 8px; line-height: 1.6; }
        .guide-table { width: 100%; border-collapse: collapse; margin: 16px 0; }
        .guide-table th, .guide-table td { 
            padding: 10px 14px; 
            text-align: left; 
            border: 1px solid var(--slate-700);
        }
        .guide-table th { 
            background: rgba(30, 41, 59, 0.8); 
            color: var(--cyan-400); 
            font-weight: 600;
            font-size: 0.85rem;
        }
        .guide-table td { color: #e2e8f0; }
        .guide-code { 
            font-family: 'Consolas', 'Monaco', monospace; 
            background: rgba(15, 23, 42, 0.7); 
            padding: 2px 6px; 
            border-radius: 4px;
            font-size: 0.85rem;
            color: var(--cyan-400);
        }
        .guide-diagram {
            background: rgba(15, 23, 42, 0.5);
            border: 1px solid var(--slate-700);
            border-radius: 8px;
            padding: 16px;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.9rem;
            color: var(--cyan-400);
            text-align: center;
            margin: 16px 0;
        }
        .highlight { color: var(--cyan-400); font-weight: 500; }
        .guide-card {
            background: rgba(30, 41, 59, 0.6);
            border: 1px solid var(--slate-700);
            border-radius: 8px;
            padding: 16px;
            margin: 16px 0;
        }
        .guide-card-title { color: var(--cyan-400); font-weight: 600; margin-bottom: 8px; }
        .toc { margin-bottom: 32px; }
        .toc a { color: var(--cyan-400); display: block; padding: 6px 0; }
        .toc a:hover { color: #ffffff; }
    </style>
    """
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>User Guide - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
    {guide_style}
</head>
<body>
    {ui_nav('guide')}
    <div class="guide-container">
        <h1>AAM Operator User Guide</h1>
        
        <div class="toc panel">
            <div class="panel-title">Quick Navigation</div>
            <a href="#what-is-aam">What is AAM?</a>
            <a href="#three-jobs">The Three Operator Jobs</a>
            <a href="#topology-screen">Topology Screen</a>
            <a href="#pipes-screen">Pipes Inventory Screen</a>
            <a href="#pipe-detail">Pipe Detail Screen</a>
            <a href="#candidates-screen">Candidates Screen</a>
            <a href="#drift-screen">Drift & Health Screen</a>
            <a href="#workflows">Common Workflows</a>
            <a href="#glossary">Glossary</a>
        </div>
        
        <div class="guide-section" id="what-is-aam">
            <h2>What is AAM?</h2>
            <p><strong>AAM (Adaptive API Mesh)</strong> is the self-healing integration mesh that observes, documents, and maintains your enterprise's data pipes. It makes pipe behavior and meaning explicit <strong>without changing how data moves</strong>.</p>
            
            <h3>The Big Picture</h3>
            <p>AAM sits between two other systems:</p>
            <div class="guide-diagram">
                AOD (discovers what exists) → <span class="highlight">AAM (catalogs pipes, self-heals)</span> → DCL (unifies meaning)
            </div>
            <ul>
                <li><strong>AOD</strong> discovers what systems exist and sends "connection candidates" to AAM</li>
                <li><strong>AAM</strong> (this system) catalogs connections as "declared pipes" and self-heals when things drift</li>
                <li><strong>DCL</strong> consumes declared pipes to build unified business understanding</li>
            </ul>
            
            <h3>Connectivity Modalities</h3>
            <p>AAM supports four connection patterns:</p>
            <table class="guide-table">
                <tr><th>Mode</th><th>Description</th><th>Use Case</th></tr>
                <tr><td>Control-Plane Attachment</td><td>Read-only visibility into APIs, integrations, ownership</td><td>Primary enterprise pattern</td></tr>
                <tr><td>Declared Interface</td><td>MuleSoft System APIs or enterprise-approved APIs</td><td>Standardized access</td></tr>
                <tr><td>Passive Subscription</td><td>Kafka topics, Event Hub, Snowflake streams</td><td>Event-driven data</td></tr>
                <tr><td>Minimal Tee</td><td>One additional sink added to existing flow</td><td>Explicit enablement only</td></tr>
            </table>

            <h3>Fabric Plane Integrations</h3>
            <p>AAM connects to <strong>Fabric Planes</strong>, not individual SaaS apps:</p>
            <table class="guide-table">
                <tr><th>Plane</th><th>Systems</th><th>Capabilities</th></tr>
                <tr><td>iPaaS</td><td>Workato, MuleSoft, Tray.io</td><td>Webhook signals, recipe changes</td></tr>
                <tr><td>API Gateway</td><td>Kong, Apigee, AWS API GW</td><td>API catalogs, traffic patterns</td></tr>
                <tr><td>Event Bus</td><td>Kafka, EventBridge, Pulsar</td><td>Schema registries, topic metadata</td></tr>
                <tr><td>Data Warehouse</td><td>Snowflake, BigQuery, Redshift</td><td>Table schemas, freshness metadata</td></tr>
            </table>

            <h3>Self-Healing Capabilities</h3>
            <p>AAM actively monitors and repairs connectivity issues:</p>
            <table class="guide-table">
                <tr><th>Drift Type</th><th>Detection</th><th>Self-Heal Action</th></tr>
                <tr><td>Connection Drift</td><td>Lost connectivity to Fabric Plane</td><td>Reconnect adapter</td></tr>
                <tr><td>Consumer Lag</td><td>Event Bus consumers falling behind</td><td>Restart consumers</td></tr>
                <tr><td>Warehouse Suspend</td><td>Warehouse compute suspended</td><td>Wake warehouse</td></tr>
                <tr><td>Schema Drift</td><td>Field changes in pipe schemas</td><td>Log version, alert operators</td></tr>
            </table>
            
            <div class="guide-card">
                <div class="guide-card-title">What AAM Does NOT Do</div>
                <p>AAM does not move data, transform data, act as an iPaaS, build per-app SaaS connectors, provision new connectors, or rotate secrets. It only <strong>observes</strong>, <strong>documents</strong>, and <strong>self-heals connectivity</strong>.</p>
            </div>
        </div>
        
        <div class="guide-section" id="three-jobs">
            <h2>The Three Operator Jobs</h2>
            <p>As an operator, AAM supports exactly three jobs:</p>
            <ol>
                <li><strong>See what pipes exist</strong> - View the inventory of data pipes with their metadata and trust state</li>
                <li><strong>See what's wrong</strong> - Identify drift, health issues, and coverage gaps with evidence</li>
                <li><strong>Take bounded actions</strong> - Run collectors, acknowledge drift, tag ownership, export to DCL</li>
            </ol>
            <p>Nothing more, nothing less. AAM deliberately avoids "magic" actions like "fix automatically" or "connect now."</p>
        </div>

        <div class="guide-section" id="topology-screen">
            <h2>Topology Screen</h2>
            <p>The <strong>Topology</strong> screen is the landing page and provides an interactive graph visualization of your entire integration mesh. It shows how fabric planes, pipes, source systems, and candidates relate to each other.</p>

            <h3>Node Types</h3>
            <table class="guide-table">
                <tr><th>Shape</th><th>Color</th><th>Meaning</th></tr>
                <tr><td>Diamond</td><td>Purple/Cyan/Orange/Green</td><td>Fabric Plane (API Gateway, iPaaS, Event Bus, Data Warehouse)</td></tr>
                <tr><td>Circle</td><td>Blue</td><td>Pipe - a declared data connection</td></tr>
                <tr><td>Square</td><td>Gray</td><td>Source System - where data originates</td></tr>
                <tr><td>Triangle</td><td>Purple</td><td>Candidate - a potential connection from AOD</td></tr>
            </table>

            <h3>Controls</h3>
            <table class="guide-table">
                <tr><th>Control</th><th>What It Does</th></tr>
                <tr><td>View Filter</td><td>Filter to show only nodes in a specific fabric plane</td></tr>
                <tr><td>Layout</td><td>Switch between Hierarchical (default), Force-Directed, or Circular layouts</td></tr>
                <tr><td>Lock Positions</td><td>Toggle physics on/off - when locked, nodes stay where you drag them</td></tr>
                <tr><td>Reset View</td><td>Return to default view with all nodes</td></tr>
                <tr><td>Fit to Screen</td><td>Zoom to fit all visible nodes</td></tr>
            </table>

            <h3>Interactions</h3>
            <ul>
                <li><strong>Click</strong> a node to see its details in the side panel</li>
                <li><strong>Double-click</strong> a pipe node to navigate to its detail page</li>
                <li><strong>Drag</strong> nodes to rearrange them (use Lock Positions to keep them in place)</li>
                <li><strong>Scroll</strong> to zoom in/out</li>
            </ul>
        </div>

        <div class="guide-section" id="pipes-screen">
            <h2>Pipes Inventory Screen</h2>
            <p>This is your main dashboard showing all discovered data pipes. Access it via the <span class="guide-code">Pipes</span> navigation link.</p>
            
            <h3>What You See</h3>
            <table class="guide-table">
                <tr><th>Element</th><th>What It Means</th></tr>
                <tr><td>Pipe Name</td><td>Human-readable name for this data pipe (clickable to view details)</td></tr>
                <tr><td>Source System</td><td>Where the data comes from (e.g., "Salesforce", "Workday")</td></tr>
                <tr><td>Modality</td><td>How this pipe connects: CONTROL_PLANE, DECLARED_INTERFACE, PASSIVE_SUBSCRIPTION, or MINIMAL_TEE</td></tr>
                <tr><td>Transport</td><td>How data moves: API, EVENT_STREAM, TABLE, FILE, or WEBHOOK</td></tr>
                <tr><td>Trust Labels</td><td>Quality signals like data freshness, schema stability, ownership clarity</td></tr>
            </table>
            
            <h3>Actions You Can Take</h3>
            <table class="guide-table">
                <tr><th>Button</th><th>What It Does</th></tr>
                <tr><td>Run Mock Collector</td><td>Triggers a mock collector to simulate pipe discovery and create sample data</td></tr>
                <tr><td>Export to DCL</td><td>Generates a snapshot of all pipes in DCL format for downstream consumption</td></tr>
            </table>

            <h3>Enterprise Presets</h3>
            <p>At the top of the Pipes screen, you can load predefined enterprise presets that populate sample data for different integration patterns. This is useful for demos and testing.</p>
        </div>
        
        <div class="guide-section" id="pipe-detail">
            <h2>Pipe Detail Screen</h2>
            <p>Clicking on a pipe name takes you to its detail view with complete information.</p>
            
            <h3>Key Sections</h3>
            <table class="guide-table">
                <tr><th>Section</th><th>What It Shows</th></tr>
                <tr><td>Identity & Classification</td><td>Pipe ID, display name, source system, modality, transport kind</td></tr>
                <tr><td>Data Characteristics</td><td>Entity scope, identity keys, change semantics, freshness</td></tr>
                <tr><td>Provenance</td><td>Discovery source, when discovered, lineage hints</td></tr>
                <tr><td>Trust & Ownership</td><td>Trust labels, owner signals</td></tr>
                <tr><td>Version History</td><td>How this pipe's definition has changed over time</td></tr>
                <tr><td>Drift Events</td><td>Any drift events specific to this pipe</td></tr>
            </table>
        </div>
        
        <div class="guide-section" id="candidates-screen">
            <h2>Candidates Screen</h2>
            <p>Shows connection candidates from AOD that haven't been fully processed yet.</p>
            
            <h3>Candidate Statuses</h3>
            <table class="guide-table">
                <tr><th>Status</th><th>What It Means</th></tr>
                <tr><td><span class="badge badge-new">New</span></td><td>Just arrived from AOD, not yet reviewed</td></tr>
                <tr><td><span class="badge badge-triaged">Triaged</span></td><td>Reviewed but not yet connected to a pipe</td></tr>
                <tr><td><span class="badge badge-connected">Connected</span></td><td>Successfully matched to a declared pipe</td></tr>
                <tr><td><span class="badge badge-deferred">Deferred</span></td><td>Intentionally set aside (with a reason)</td></tr>
            </table>
            
            <h3>Actions</h3>
            <ul>
                <li><strong>Match to Pipe</strong> - Links this candidate to an existing pipe (requires pipe ID)</li>
                <li><strong>Defer</strong> - Sets the candidate aside with a reason</li>
                <li><strong>Create Tee</strong> - Creates a minimal tee request artifact (for connected candidates)</li>
            </ul>
        </div>
        
        <div class="guide-section" id="drift-screen">
            <h2>Drift & Health Screen</h2>
            <p>Shows issues that need attention - places where reality has diverged from expectations.</p>
            
            <h3>Drift Types</h3>
            <table class="guide-table">
                <tr><th>Type</th><th>What It Means</th></tr>
                <tr><td>SCHEMA</td><td>The structure of the data changed (fields added/removed/modified)</td></tr>
                <tr><td>FRESHNESS</td><td>Data stopped updating at the expected rate</td></tr>
                <tr><td>CONTRACT</td><td>The agreed behavior of the pipe changed</td></tr>
            </table>
            
            <h3>Severity Levels</h3>
            <table class="guide-table">
                <tr><th>Level</th><th>What It Means</th><th>Response</th></tr>
                <tr><td><span class="badge badge-critical">Critical</span></td><td>Major breaking change</td><td>Immediate action required</td></tr>
                <tr><td><span class="badge badge-high">High</span></td><td>Significant change</td><td>Review within 24 hours</td></tr>
                <tr><td><span class="badge badge-medium">Medium</span></td><td>Notable change</td><td>Review within a week</td></tr>
                <tr><td><span class="badge badge-low">Low</span></td><td>Minor change</td><td>Review when convenient</td></tr>
            </table>
            
            <h3>Drift Statuses</h3>
            <ul>
                <li><span class="badge badge-open">Open</span> - Needs attention, not yet reviewed</li>
                <li><span class="badge badge-acknowledged">Acknowledged</span> - Reviewed and noted</li>
                <li><span class="badge badge-suppressed">Suppressed</span> - Intentionally hidden</li>
            </ul>
        </div>
        
        <div class="guide-section" id="workflows">
            <h2>Common Workflows</h2>
            
            <div class="guide-card">
                <div class="guide-card-title">Processing New Candidates</div>
                <ol>
                    <li>Go to <strong>Candidates</strong> screen</li>
                    <li>Review candidates with "New" status</li>
                    <li>For each candidate: Match to a pipe, or Defer with a reason</li>
                </ol>
            </div>
            
            <div class="guide-card">
                <div class="guide-card-title">Exploring the Integration Mesh</div>
                <ol>
                    <li>Start at the <strong>Topology</strong> screen (the landing page)</li>
                    <li>Use the View filter to focus on a specific fabric plane</li>
                    <li>Click nodes to see their metadata in the side panel</li>
                    <li>Double-click a pipe to drill into its detail page</li>
                </ol>
            </div>

            <div class="guide-card">
                <div class="guide-card-title">Populating Sample Data</div>
                <ol>
                    <li>Go to <strong>Pipes</strong> screen</li>
                    <li>Load an Enterprise Preset to populate sample data, or</li>
                    <li>Click <strong>Run Mock Collector</strong> to simulate pipe discovery</li>
                    <li>Review newly created pipes in the table</li>
                </ol>
            </div>
            
            <div class="guide-card">
                <div class="guide-card-title">Investigating Drift</div>
                <ol>
                    <li>Go to <strong>Drift & Health</strong> screen</li>
                    <li>Review items with "Open" status</li>
                    <li>Click on the pipe name to see full details</li>
                    <li>Acknowledge or Suppress as appropriate</li>
                </ol>
            </div>
        </div>
        
        <div class="guide-section" id="glossary">
            <h2>Glossary</h2>
            <table class="guide-table">
                <tr><th>Term</th><th>Definition</th></tr>
                <tr><td>Candidate</td><td>A potential connection discovered by AOD that AAM might catalog</td></tr>
                <tr><td>Collector</td><td>A component that observes enterprise systems and creates observations</td></tr>
                <tr><td>Declared Pipe</td><td>A cataloged data connection with full metadata</td></tr>
                <tr><td>DCL</td><td>Data Catalog Layer - consumes pipes from AAM to unify meaning</td></tr>
                <tr><td>Drift</td><td>When reality diverges from what was previously observed</td></tr>
                <tr><td>Fabric Plane</td><td>A category of integration infrastructure (API Gateway, iPaaS, Event Bus, Data Warehouse)</td></tr>
                <tr><td>Modality</td><td>The approach for connecting (control plane, declared interface, etc.)</td></tr>
                <tr><td>Observation</td><td>Raw data from a collector before being processed into a pipe</td></tr>
                <tr><td>Pipe</td><td>A reusable data connection between systems</td></tr>
                <tr><td>Provenance</td><td>Origin and lineage information about a pipe</td></tr>
                <tr><td>Schema Hash</td><td>A fingerprint of the data structure for detecting changes</td></tr>
                <tr><td>Topology</td><td>The graph visualization showing how pipes, systems, and candidates interconnect</td></tr>
                <tr><td>Transport</td><td>How data physically moves (API, events, files, etc.)</td></tr>
            </table>
        </div>
        
        <div style="text-align: center; padding: 24px; color: var(--slate-500);">
            <p>Need more help? Check the <a href="/docs">API Documentation</a> for complete endpoint details.</p>
        </div>
    </div>
</body>
</html>
""")


@app.get("/ui/drift", response_class=HTMLResponse, include_in_schema=False)
async def ui_drift_list(status: Optional[str] = Query(None)):
    """Drift & Health Screen"""
    all_events = list_all_drift_events(limit=500)
    
    if status:
        all_events = [e for e in all_events if e.get("status") == status]
    
    schema_drift = [e for e in all_events if e.get("drift_type") == "schema"]
    contract_drift = [e for e in all_events if e.get("drift_type") == "contract"]
    freshness_drift = [e for e in all_events if e.get("drift_type") == "freshness"]
    
    status_options = f'''
        <option value="">All Statuses</option>
        <option value="open"{"selected" if status == "open" else ""}>Open</option>
        <option value="acknowledged"{"selected" if status == "acknowledged" else ""}>Acknowledged</option>
        <option value="suppressed"{"selected" if status == "suppressed" else ""}>Suppressed</option>
    '''
    
    def make_drift_table(events, section_id):
        if not events:
            return '<div class="empty-state">No drift events in this category</div>'
        
        rows = ""
        for e in events:
            drift_id = e.get("drift_id", "")
            pipe_id = e.get("pipe_id", "")
            severity = e.get("severity", "medium")
            status_val = e.get("status", "open")
            detected = e.get("detected_at", "")[:16] if e.get("detected_at") else "-"
            evidence = f"{e.get('old_value', '')[:20]}→{e.get('new_value', '')[:20]}" if e.get('old_value') else "-"
            
            ack_btn = f'<button class="btn btn-sm" onclick="ackDrift(\'{drift_id}\')">Ack</button>' if status_val == "open" else ""
            supp_btn = f'<button class="btn btn-sm btn-danger" onclick="suppressDrift(\'{drift_id}\')">Suppress</button>' if status_val in ["open", "acknowledged"] else ""
            
            rows += f"""
            <tr data-testid="drift-row-{drift_id}">
                <td><a href="/ui/pipes/{pipe_id}">{pipe_id[:12]}...</a></td>
                <td>{e.get('drift_type', '-')}</td>
                <td><span class="badge badge-{severity}">{severity}</span></td>
                <td><span class="badge badge-{status_val}">{status_val}</span></td>
                <td>{detected}</td>
                <td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;font-size:0.75rem;">{evidence}</td>
                <td class="actions">{ack_btn}{supp_btn}</td>
            </tr>
            """
        
        return f"""
        <table>
            <thead>
                <tr><th>Pipe ID</th><th>Type</th><th>Severity</th><th>Status</th><th>First Seen</th><th>Evidence</th><th>Actions</th></tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        """
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Drift & Health - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
</head>
<body>
    {ui_nav('drift')}
    <div class="container">
        <h1>Drift & Health</h1>
        <p class="page-subtitle">Monitor schema changes and connectivity issues. Acknowledge, suppress, or take action on drift events.</p>
        <div class="controls">
            <button class="btn" id="btn-rerun-collector" data-testid="btn-rerun-collector">Re-run Collector</button>
            <select id="filter-status" data-testid="filter-drift-status" onchange="applyFilter()">{status_options}</select>
        </div>
        
        <div class="section">
            <h2>Schema Drift ({len(schema_drift)})</h2>
            {make_drift_table(schema_drift, 'schema')}
        </div>
        
        <div class="section">
            <h2>Contract Drift ({len(contract_drift)})</h2>
            {make_drift_table(contract_drift, 'contract')}
        </div>
        
        <div class="section">
            <h2>Freshness Drift ({len(freshness_drift)})</h2>
            {make_drift_table(freshness_drift, 'freshness')}
        </div>
    </div>
    <div id="toast" class="toast"></div>
    <script>
        function showToast(message, type) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast ' + type;
            toast.style.display = 'block';
            setTimeout(() => toast.style.display = 'none', 3000);
        }}
        
        function applyFilter() {{
            const status = document.getElementById('filter-status').value;
            const params = new URLSearchParams();
            if (status) params.set('status', status);
            window.location.href = '/ui/drift' + (params.toString() ? '?' + params.toString() : '');
        }}
        
        async function ackDrift(driftId) {{
            try {{
                const res = await fetch('/api/drift/' + driftId + '/ack', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ by: 'operator' }})
                }});
                const data = await res.json();
                if (res.ok) {{
                    showToast('Drift acknowledged', 'success');
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
        }}
        
        async function suppressDrift(driftId) {{
            const notes = prompt('Suppression reason (optional):');
            try {{
                const res = await fetch('/api/drift/' + driftId + '/suppress', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ by: 'operator', notes: notes || '' }})
                }});
                const data = await res.json();
                if (res.ok) {{
                    showToast('Drift suppressed', 'success');
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
        }}
        
        document.getElementById('btn-rerun-collector').addEventListener('click', async function() {{
            this.disabled = true;
            this.textContent = 'Running...';
            try {{
                const res = await fetch('/api/collect/mock/run', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: '{{}}' }});
                const data = await res.json();
                if (res.ok) {{
                    showToast('Collector ran: ' + data.observations_created + ' observations', 'success');
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
            this.disabled = false;
            this.textContent = 'Re-run Collector';
        }});
    </script>
</body>
</html>
""")


@app.get("/ui/topology", response_class=HTMLResponse, include_in_schema=False)
async def ui_topology():
    """Topology Visualization Screen - Interactive graph of pipes, planes, and sources"""
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Topology - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        #topology-container {{
            width: 100%;
            height: 600px;
            border: 1px solid var(--slate-700);
            border-radius: 8px;
            background: rgba(15, 23, 42, 0.8);
        }}
        .topology-controls {{
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
            flex-wrap: wrap;
            align-items: center;
        }}
        .stats.compact {{
            display: flex;
            gap: 8px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }}
        .stats.compact .stat-card {{
            padding: 6px 12px;
            min-width: auto;
        }}
        .stats.compact .stat-value {{
            font-size: 1rem;
            margin-bottom: 0;
        }}
        .stats.compact .stat-label {{
            font-size: 0.65rem;
        }}
        .legend-below {{
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-top: 12px;
            padding: 8px 12px;
            background: rgba(30, 41, 59, 0.6);
            border-radius: 6px;
            justify-content: center;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 0.7rem;
            color: var(--slate-300);
        }}
        .legend-shape {{
            width: 14px;
            height: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .legend-shape svg {{
            width: 12px;
            height: 12px;
        }}
        .node-details {{
            position: absolute;
            top: 100px;
            right: 24px;
            width: 300px;
            background: rgba(30, 41, 59, 0.95);
            border: 1px solid var(--slate-700);
            border-radius: 8px;
            padding: 16px;
            display: none;
            z-index: 100;
        }}
        .node-details.visible {{
            display: block;
        }}
        .node-details h3 {{
            margin-bottom: 12px;
            color: var(--cyan-400);
        }}
        .node-details .close-btn {{
            position: absolute;
            top: 8px;
            right: 8px;
            background: none;
            border: none;
            color: var(--slate-400);
            cursor: pointer;
            font-size: 1.2rem;
        }}
        .filter-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .filter-group label {{
            font-size: 0.85rem;
            color: var(--slate-400);
        }}
    </style>
</head>
<body>
    {ui_nav("topology")}
    <div class="container">
        <h1>Topology</h1>
        <p class="page-subtitle">Interactive graph visualization of your integration mesh. Shows how fabric planes, pipes, source systems, and candidates connect.</p>

        {aod_run_banner()}

        <div class="stats compact" id="stats-container">
            <div class="stat-card">
                <div class="stat-value" id="stat-pipes">-</div>
                <div class="stat-label">Pipes</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-fabrics">-</div>
                <div class="stat-label">Fabrics</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-sors">-</div>
                <div class="stat-label">SORs</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-drift">-</div>
                <div class="stat-label">Drift</div>
            </div>
        </div>

        <div class="topology-controls">
            <div class="filter-group">
                <label>Filter:</label>
                <select id="asset-filter" onchange="applyTopologyFilters()">
                    <option value="all" selected>All</option>
                    <option value="sors">SORs</option>
                    <option value="fabrics">Fabrics</option>
                    <option value="API_GATEWAY">API Gateway</option>
                    <option value="IPAAS">iPaaS</option>
                    <option value="EVENT_BUS">Event Bus</option>
                    <option value="DATA_WAREHOUSE">Data Warehouse</option>
                </select>
            </div>
            <div class="filter-group">
                <label>Detail Level:</label>
                <select id="detail-filter" onchange="applyTopologyFilters()">
                    <option value="summary" selected>Summary View</option>
                    <option value="all">All Assets (slow)</option>
                </select>
            </div>
            <div class="filter-group">
                <label>Layout:</label>
                <select id="layout-select" onchange="changeLayout()">
                    <option value="physics">Force-Directed</option>
                    <option value="hierarchical">Hierarchical</option>
                    <option value="circular">Circular</option>
                </select>
            </div>
            <button class="btn" onclick="resetView()">Reset View</button>
            <button class="btn" onclick="fitToScreen()">Fit to Screen</button>
            <button class="btn btn-success" onclick="refreshData()">Refresh Data</button>
            <button class="btn" id="physics-toggle" onclick="togglePhysics()">🔓 Unlock Positions</button>
        </div>

        <div id="topology-container"></div>

        <div class="legend-below">
            <div class="legend-item">
                <div class="legend-shape"><svg viewBox="0 0 12 12"><polygon points="6,0 12,6 6,12 0,6" fill="#a78bfa"/></svg></div>
                <span>Gateway</span>
            </div>
            <div class="legend-item">
                <div class="legend-shape"><svg viewBox="0 0 12 12"><polygon points="6,0 12,6 6,12 0,6" fill="#22d3ee"/></svg></div>
                <span>iPaaS</span>
            </div>
            <div class="legend-item">
                <div class="legend-shape"><svg viewBox="0 0 12 12"><polygon points="6,0 12,6 6,12 0,6" fill="#f97316"/></svg></div>
                <span>Event Bus</span>
            </div>
            <div class="legend-item">
                <div class="legend-shape"><svg viewBox="0 0 12 12"><polygon points="6,0 12,6 6,12 0,6" fill="#10b981"/></svg></div>
                <span>Warehouse</span>
            </div>
            <div class="legend-item">
                <div class="legend-shape"><svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="#60a5fa"/></svg></div>
                <span>Pipe</span>
            </div>
            <div class="legend-item">
                <div class="legend-shape"><svg viewBox="0 0 12 12"><rect x="1" y="1" width="10" height="10" fill="#94a3b8"/></svg></div>
                <span>Source</span>
            </div>
            <div class="legend-item">
                <div class="legend-shape"><svg viewBox="0 0 12 12"><polygon points="6,1 11,11 1,11" fill="#c084fc"/></svg></div>
                <span>Candidate</span>
            </div>
        </div>

        <div id="node-details" class="node-details">
            <button class="close-btn" onclick="closeDetails()">&times;</button>
            <h3 id="detail-title">Node Details</h3>
            <div id="detail-content"></div>
        </div>
    </div>

    <script>
        let network = null;
        let allNodes = [];
        let allEdges = [];
        let physicsEnabled = true;

        const nodeColors = {{
            fabric_plane: {{
                'IPAAS': '#22d3ee',
                'API_GATEWAY': '#a78bfa',
                'EVENT_BUS': '#f97316',
                'DATA_WAREHOUSE': '#10b981'
            }},
            pipe: '#60a5fa',
            source_system: '#94a3b8',
            candidate: '#c084fc'
        }};

        const nodeShapes = {{
            fabric_plane: 'diamond',
            pipe: 'dot',
            source_system: 'square',
            candidate: 'triangle'
        }};

        async function loadTopology(fabricFilter = 'all', sorFilter = 'all', detailLevel = 'summary') {{
            let url = '/api/topology/summary';
            
            if (detailLevel === 'all') {{
                url = '/api/topology';
            }} else if (fabricFilter !== 'all') {{
                url = `/api/topology/plane/${{fabricFilter}}`;
            }}

            const response = await fetch(url);
            let data = await response.json();
            
            // Apply SOR filter client-side
            if (sorFilter !== 'all') {{
                if (sorFilter === 'show') {{
                    // Show only SOR nodes
                    data.nodes = data.nodes.filter(n => 
                        n.metadata && n.metadata.is_sor === true || n.type === 'fabric_plane'
                    );
                }} else if (sorFilter === 'hide') {{
                    // Hide SOR nodes
                    data.nodes = data.nodes.filter(n => 
                        !n.metadata || n.metadata.is_sor !== true
                    );
                }}
                // Filter edges to only those with both nodes present
                const nodeIds = new Set(data.nodes.map(n => n.id));
                data.edges = data.edges.filter(e => 
                    nodeIds.has(e.source) && nodeIds.has(e.target)
                );
            }}

            allNodes = data.nodes.map(n => ({{
                id: n.id,
                label: n.label,
                shape: nodeShapes[n.type] || 'dot',
                color: n.type === 'fabric_plane'
                    ? nodeColors.fabric_plane[n.metadata.plane_type] || '#64748b'
                    : nodeColors[n.type] || '#64748b',
                size: n.type === 'fabric_plane' ? 30 : (n.type === 'pipe' ? 20 : 15),
                font: {{ color: '#ffffff', size: 12 }},
                title: buildTooltip(n),
                nodeData: n
            }}));

            allEdges = data.edges.map(e => ({{
                id: e.id,
                from: e.source,
                to: e.target,
                color: {{ color: '#475569', opacity: 0.6 }},
                width: e.type === 'candidate_to_pipe' ? 2 : 1,
                dashes: e.type === 'candidate_for_source',
                arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }}
            }}));

            // Update stats
            if (data.stats) {{
                // Canonical KPIs: Pipes (= candidates), Fabrics, SORs
                document.getElementById('stat-pipes').textContent = data.stats.total_candidates || 0;
                document.getElementById('stat-fabrics').textContent = data.stats.fabrics || 0;
                document.getElementById('stat-sors').textContent = data.stats.sors || 0;
                document.getElementById('stat-drift').textContent = data.stats.pipes_with_drift || 0;
            }}

            renderNetwork();
        }}

        function buildTooltip(node) {{
            let html = `<div style="background:#1e293b;padding:8px;border-radius:4px;color:#fff;">`;
            html += `<strong>${{node.label}}</strong><br/>`;
            html += `Type: ${{node.type}}<br/>`;
            if (node.metadata.fabric_plane) html += `Plane: ${{node.metadata.fabric_plane}}<br/>`;
            if (node.metadata.source_system) html += `Source: ${{node.metadata.source_system}}<br/>`;
            if (node.metadata.modality) html += `Modality: ${{node.metadata.modality}}<br/>`;
            if (node.metadata.status) html += `Status: ${{node.metadata.status}}<br/>`;
            html += `</div>`;
            return html;
        }}

        function renderNetwork() {{
            const container = document.getElementById('topology-container');
            const data = {{
                nodes: new vis.DataSet(allNodes),
                edges: new vis.DataSet(allEdges)
            }};

            const options = getLayoutOptions();

            network = new vis.Network(container, data, options);

            network.on('click', function(params) {{
                if (params.nodes.length > 0) {{
                    const nodeId = params.nodes[0];
                    const node = allNodes.find(n => n.id === nodeId);
                    if (node) showNodeDetails(node);
                }} else {{
                    closeDetails();
                }}
            }});

            network.on('doubleClick', function(params) {{
                if (params.nodes.length > 0) {{
                    const nodeId = params.nodes[0];
                    const node = allNodes.find(n => n.id === nodeId);
                    if (node && node.nodeData.type === 'pipe') {{
                        window.location.href = `/ui/pipes/${{node.nodeData.metadata.pipe_id}}`;
                    }}
                }}
            }});
        }}

        function getLayoutOptions() {{
            const layoutType = document.getElementById('layout-select').value;

            const baseOptions = {{
                nodes: {{
                    borderWidth: 2,
                    shadow: true
                }},
                edges: {{
                    smooth: {{ type: 'continuous' }}
                }},
                interaction: {{
                    hover: true,
                    tooltipDelay: 200,
                    zoomView: true,
                    dragView: true
                }}
            }};

            if (layoutType === 'hierarchical') {{
                return {{
                    ...baseOptions,
                    layout: {{
                        hierarchical: {{
                            direction: 'UD',
                            sortMethod: 'hubsize',
                            levelSeparation: 100,
                            nodeSpacing: 150
                        }}
                    }},
                    physics: false
                }};
            }} else if (layoutType === 'circular') {{
                return {{
                    ...baseOptions,
                    layout: {{
                        improvedLayout: true
                    }},
                    physics: {{
                        enabled: true,
                        solver: 'repulsion',
                        repulsion: {{
                            nodeDistance: 200
                        }}
                    }}
                }};
            }} else {{
                return {{
                    ...baseOptions,
                    physics: {{
                        enabled: true,
                        solver: 'forceAtlas2Based',
                        forceAtlas2Based: {{
                            gravitationalConstant: -50,
                            springLength: 100,
                            springConstant: 0.08
                        }},
                        stabilization: {{ iterations: 100 }}
                    }}
                }};
            }}
        }}

        function showNodeDetails(node) {{
            const details = document.getElementById('node-details');
            const title = document.getElementById('detail-title');
            const content = document.getElementById('detail-content');

            title.textContent = node.label;

            let html = `<div class="field"><div class="field-label">Type</div><div class="field-value">${{node.nodeData.type}}</div></div>`;

            const meta = node.nodeData.metadata;
            for (const [key, value] of Object.entries(meta)) {{
                if (value && key !== 'central' && key !== 'color') {{
                    let displayValue = value;
                    if (Array.isArray(value)) {{
                        displayValue = value.length > 0 ? value.join(', ') : '(none)';
                    }}
                    const label = key.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                    html += `<div class="field"><div class="field-label">${{label}}</div><div class="field-value">${{displayValue}}</div></div>`;
                }}
            }}

            if (node.nodeData.type === 'pipe') {{
                html += `<div style="margin-top:12px;"><a href="/ui/pipes/${{meta.pipe_id}}" class="btn btn-sm">View Pipe Details</a></div>`;
            }}

            content.innerHTML = html;
            details.classList.add('visible');
        }}

        function closeDetails() {{
            document.getElementById('node-details').classList.remove('visible');
        }}

        function applyTopologyFilters() {{
            const assetFilter = document.getElementById('asset-filter').value;
            const detailLevel = document.getElementById('detail-filter').value;
            
            // Map single filter to fabric/sor parameters
            let fabricFilter = 'all';
            let sorFilter = 'all';
            
            if (assetFilter === 'sors') {{
                sorFilter = 'show';
            }} else if (assetFilter === 'fabrics') {{
                fabricFilter = 'all';
                sorFilter = 'hide';
            }} else if (assetFilter !== 'all') {{
                // Specific fabric type
                fabricFilter = assetFilter;
            }}
            
            loadTopology(fabricFilter, sorFilter, detailLevel);
        }}

        function changeLayout() {{
            renderNetwork();
        }}

        function resetView() {{
            document.getElementById('view-filter').value = 'all';
            document.getElementById('layout-select').value = 'physics';
            loadTopology('all');
        }}

        function fitToScreen() {{
            if (network) network.fit();
        }}

        function refreshData() {{
            const filter = document.getElementById('view-filter').value;
            loadTopology(filter);
        }}

        function togglePhysics() {{
            physicsEnabled = !physicsEnabled;
            const btn = document.getElementById('physics-toggle');

            if (physicsEnabled) {{
                btn.textContent = '🔓 Unlock Positions';
                btn.classList.remove('btn-warning');
                if (network) {{
                    network.setOptions({{ physics: getLayoutOptions().physics }});
                }}
            }} else {{
                btn.textContent = '🔒 Lock Positions';
                btn.classList.add('btn-warning');
                if (network) {{
                    // Disable physics - nodes stay where you put them
                    network.setOptions({{ physics: false }});
                }}
            }}
        }}

        // Initialize
        loadTopology();
    </script>
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


# ============================================================================
# AOD HANDOFF ENDPOINTS
# ============================================================================

@app.post("/api/handoff/aod/reset", tags=["AOD Handoff"])
async def reset_aod_data():
    """
    Reset ALL prior AAM state.
    
    Clears ALL existing data (fabric planes, candidates, pipes, drift,
    handoff logs, observations, collectors, tee requests, policy manifests).
    Call this before sending a new AOD handoff to ensure no stale data
    from prior runs pollutes the current state.
    """
    reset_result = reset_aod_state()
    print(f"[AAM RESET] Reset complete: {reset_result['total_rows_deleted']} rows cleared across {len(reset_result['tables_cleared'])} tables")
    return reset_result


@app.post("/api/handoff/aod/fetch", tags=["AOD Handoff"])
async def fetch_aod_data():
    """
    Reset all AAM state, then replay the last AOD handoff data.
    """
    payload = _load_aod_payload()
    if not payload:
        raise HTTPException(status_code=404, detail="No AOD payload stored. Receive a handoff first.")
    
    reset_result = reset_aod_state()
    print(f"[AAM FETCH] Reset complete: {reset_result['total_rows_deleted']} rows cleared")
    
    request = AODHandoffRequest(**payload)
    handoff_response = await receive_aod_handoff(request)
    
    result = handoff_response.model_dump() if hasattr(handoff_response, 'model_dump') else dict(handoff_response)
    result["reset"] = reset_result
    return result


AOD_PAYLOAD_FILE = "aod_last_payload.json"

def _save_aod_payload(request: AODHandoffRequest):
    """Save raw AOD payload to file so it can be replayed after reset."""
    try:
        import json as _json
        with open(AOD_PAYLOAD_FILE, "w") as f:
            _json.dump(request.model_dump(mode="json"), f)
    except Exception as e:
        print(f"[AAM] Failed to save AOD payload: {e}")

def _load_aod_payload() -> Optional[dict]:
    """Load last saved AOD payload from file."""
    try:
        import json as _json
        with open(AOD_PAYLOAD_FILE, "r") as f:
            return _json.load(f)
    except Exception:
        return None


@app.post("/api/handoff/aod/receive", tags=["AOD Handoff"])
async def receive_aod_handoff(request: AODHandoffRequest):
    """
    Receive batch handoff of candidates from AOD.

    This is the primary integration point between AOD and AAM.
    AOD sends ConnectionCandidates after discovery with:
    - execution_allowed: Whether AOD governance permits execution
    - action_type: "inventory_only" (human review) or "provision" (auto-connect)
    - blocking_findings: Findings that prevent auto-provisioning
    - connected_via_plane: Fabric plane routing hint from AOD
    - fabric_planes: Detected fabric control planes
    """
    _save_aod_payload(request)
    
    # LOG INCOMING REQUEST
    print(f"[AAM HANDOFF] run_id={request.run_id}, snapshot_name={request.snapshot_name}, candidates={len(request.candidates)}")
    
    # Store fabric planes from AOD and build lookup map
    fabric_planes_stored = 0
    fabric_plane_map = {}  # vendor -> plane_id mapping
    if request.fabric_planes:
        for plane in request.fabric_planes:
            try:
                plane_dict = plane.model_dump()
                result = store_fabric_plane(plane_dict, request.run_id)
                plane_id = result["plane_id"]
                fabric_plane_map[plane.vendor.lower()] = plane_id
                fabric_planes_stored += 1
            except Exception as e:
                print(f"[AAM] Failed to store fabric plane {plane.vendor}: {e}")
    
    # Auto-create fabric planes from SOR candidates if none provided
    sor_categories = {'crm', 'erp', 'hcm', 'idp', 'itsm', 'saas', 'hr', 'finance', 'cmdb', 'identity'}
    if not request.fabric_planes:
        seen_vendors = set()
        for candidate in request.candidates:
            cat_lower = candidate.category.lower() if candidate.category else ""
            if cat_lower in sor_categories and candidate.vendor_name:
                vendor_key = candidate.vendor_name.lower()
                if vendor_key not in seen_vendors:
                    seen_vendors.add(vendor_key)
                    # Create fabric plane from SOR candidate
                    plane_type = "API_GATEWAY"  # SORs typically expose APIs
                    if cat_lower in {'erp', 'finance'}:
                        plane_type = "DATA_WAREHOUSE"
                    elif cat_lower in {'crm', 'saas', 'hr', 'hcm'}:
                        plane_type = "API_GATEWAY"
                    elif cat_lower in {'idp', 'identity'}:
                        plane_type = "API_GATEWAY"
                    elif cat_lower in {'itsm', 'cmdb'}:
                        plane_type = "IPAAS"
                    
                    plane_dict = {
                        "plane_type": plane_type,
                        "vendor": candidate.vendor_name,
                        "display_name": f"{candidate.asset_key} ({candidate.category})",
                        "domain": cat_lower,
                        "managed_asset_count": 1
                    }
                    try:
                        result = store_fabric_plane(plane_dict, request.run_id)
                        plane_id = result["plane_id"]
                        fabric_plane_map[vendor_key] = plane_id
                        fabric_planes_stored += 1
                        print(f"[AAM] Auto-created fabric plane for SOR: {candidate.vendor_name} ({plane_type})")
                    except Exception as e:
                        print(f"[AAM] Failed to auto-create fabric plane for {candidate.vendor_name}: {e}")
    
    accepted = []
    rejected = []

    for candidate in request.candidates:
        try:
            # Convert to dict for database
            candidate_dict = candidate.model_dump()

            # Handle enums
            if candidate.preferred_modality:
                candidate_dict["preferred_modality"] = candidate.preferred_modality.value
            if candidate.action_type:
                candidate_dict["action_type"] = candidate.action_type.value
            if candidate.connected_via_plane:
                candidate_dict["connected_via_plane"] = candidate.connected_via_plane.value
            if candidate.findings:
                candidate_dict["findings"] = [f.model_dump() for f in candidate.findings]
            
            # Link candidate to fabric plane
            fabric_plane_id = None
            vendor_lower = candidate.vendor_name.lower()
            
            # Try direct vendor match first
            for plane_vendor, plane_id in fabric_plane_map.items():
                if plane_vendor in vendor_lower or vendor_lower in plane_vendor:
                    fabric_plane_id = plane_id
                    break
            
            # Fallback: infer from category
            if not fabric_plane_id and fabric_plane_map:
                category_lower = candidate.category.lower()
                if "data" in category_lower or "warehouse" in category_lower:
                    target_type = "warehouse"
                elif "event" in category_lower or "stream" in category_lower:
                    target_type = "event_bus"
                elif "gateway" in category_lower or "api" in category_lower:
                    target_type = "api_gateway"
                else:
                    target_type = "ipaas"
                
                # Find first plane of that type
                for plane in request.fabric_planes:
                    if plane.plane_type == target_type:
                        fabric_plane_id = fabric_plane_map.get(plane.vendor.lower())
                        if fabric_plane_id:
                            break
            
            if fabric_plane_id:
                candidate_dict["fabric_plane_id"] = fabric_plane_id

            # Create the candidate
            result = create_candidate(candidate_dict)
            accepted.append({
                "aod_asset_id": candidate.aod_asset_id,
                "candidate_id": result["candidate_id"],
                "execution_allowed": candidate.execution_allowed,
                "action_type": candidate.action_type.value
            })

        except Exception as e:
            rejected.append({
                "aod_asset_id": candidate.aod_asset_id,
                "asset_key": candidate.asset_key,
                "reason": str(e)
            })

    # Extract AOD-provided fabric planes for reconciliation
    aod_fabric_planes_data = []
    if request.fabric_planes:
        for plane in request.fabric_planes:
            aod_fabric_planes_data.append({
                "plane_type": plane.plane_type,
                "vendor": plane.vendor,
                "is_healthy": plane.is_healthy
            })
    
    # Extract SOR vendors from candidates for reconciliation
    aod_sor_data = {}
    sor_cat_set = {'crm', 'erp', 'hcm', 'idp', 'itsm', 'saas', 'hr', 'finance', 'cmdb', 'identity'}
    for candidate in request.candidates:
        cat_lower = candidate.category.lower() if candidate.category else ""
        if cat_lower in sor_cat_set and candidate.vendor_name:
            vendor_key = candidate.vendor_name.lower()
            if vendor_key not in aod_sor_data:
                aod_sor_data[vendor_key] = {"vendor": candidate.vendor_name, "category": cat_lower, "count": 0}
            aod_sor_data[vendor_key]["count"] += 1
    
    # Log the handoff
    handoff_log = create_handoff_log({
        "aod_run_id": request.run_id,
        "snapshot_name": request.snapshot_name,
        "candidates_received": len(request.candidates),
        "candidates_accepted": len(accepted),
        "candidates_rejected": len(rejected),
        "rejected_reasons": rejected,
        "policy_version": request.policy_version,
        "handoff_timestamp": request.handoff_timestamp.isoformat() if request.handoff_timestamp else None,
        "aod_fabric_planes": aod_fabric_planes_data,
        "aod_sor_vendors": list(aod_sor_data.values())
    })

    return AODHandoffResponse(
        run_id=request.run_id,
        candidates_received=len(request.candidates),
        candidates_accepted=len(accepted),
        candidates_rejected=len(rejected),
        rejected_reasons=rejected,
        handoff_id=handoff_log["handoff_id"],
        processed_at=datetime.utcnow()
    )


@app.post("/api/handoff/aod/policy", tags=["AOD Handoff"])
async def receive_aod_policy(policy: AODPolicyManifest):
    """
    Receive governance policy manifest from AOD.

    AOD publishes its governance rules so AAM can:
    - Respect blocking finding types
    - Apply fabric plane routing rules
    - Enforce auto-provision vs human-review categories
    """
    policy_dict = policy.model_dump()
    result = save_policy_manifest(policy_dict)

    return {
        "message": "Policy manifest received and activated",
        "policy_id": result["policy_id"],
        "policy_version": result["policy_version"],
        "is_active": True
    }


@app.get("/api/handoff/aod/policy", tags=["AOD Handoff"])
async def get_current_aod_policy():
    """Get the currently active AOD policy manifest"""
    policy = get_active_policy_manifest()
    if not policy:
        return {"message": "No active policy manifest", "policy": None}
    return {"policy": policy}


@app.post("/api/fabric-planes/backfill", tags=["Fabric Planes"])
async def backfill_fabric_planes_from_candidates():
    """
    Backfill fabric planes from existing SOR candidates.
    Creates fabric plane entries for each unique vendor in SOR categories.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    sor_categories = ('crm', 'erp', 'hcm', 'idp', 'itsm', 'saas', 'hr', 'finance', 'cmdb', 'identity')
    placeholders = ','.join('?' * len(sor_categories))
    
    cursor.execute(f"""
        SELECT DISTINCT vendor_name, category, asset_key, aod_run_id
        FROM connection_candidates 
        WHERE LOWER(category) IN ({placeholders})
        AND vendor_name IS NOT NULL AND vendor_name != ''
    """, sor_categories)
    
    candidates = cursor.fetchall()
    conn.close()
    
    created = 0
    for row in candidates:
        vendor_name, category, asset_key, aod_run_id = row
        cat_lower = category.lower() if category else ""
        
        plane_type = "API_GATEWAY"
        if cat_lower in {'erp', 'finance'}:
            plane_type = "DATA_WAREHOUSE"
        elif cat_lower in {'itsm', 'cmdb'}:
            plane_type = "IPAAS"
        
        plane_dict = {
            "plane_type": plane_type,
            "vendor": vendor_name,
            "display_name": f"{asset_key} ({category})",
            "domain": cat_lower,
            "managed_asset_count": 1
        }
        try:
            store_fabric_plane(plane_dict, aod_run_id)
            created += 1
            print(f"[AAM] Backfilled fabric plane: {vendor_name} ({plane_type})")
        except Exception as e:
            print(f"[AAM] Skip duplicate fabric plane {vendor_name}: {e}")
    
    return {
        "message": f"Backfilled {created} fabric planes from SOR candidates",
        "created": created
    }


@app.get("/api/handoff/aod/policy/history", tags=["AOD Handoff"])
async def get_aod_policy_history(limit: int = Query(20, description="Maximum policies to return")):
    """Get history of AOD policy manifests"""
    policies = list_policy_manifests(limit=limit)
    return {"policies": policies, "count": len(policies)}


@app.get("/api/handoff/aod/logs", tags=["AOD Handoff"])
async def get_handoff_logs(
    aod_run_id: Optional[str] = Query(None, description="Filter by AOD run ID"),
    limit: int = Query(50, description="Maximum logs to return")
):
    """Get AOD handoff logs"""
    logs = list_handoff_logs(aod_run_id=aod_run_id, limit=limit)
    return {"logs": logs, "count": len(logs)}


@app.get("/api/handoff/aod/logs/{handoff_id}", tags=["AOD Handoff"])
async def get_handoff_log_detail(handoff_id: str):
    """Get details of a specific handoff"""
    log = get_handoff_log(handoff_id)
    if not log:
        raise HTTPException(status_code=404, detail="Handoff log not found")
    return log


@app.get("/api/handoff/aod/run/{aod_run_id}/candidates", tags=["AOD Handoff"])
async def get_candidates_from_aod_run(aod_run_id: str):
    """Get all candidates from a specific AOD discovery run"""
    candidates = get_candidates_by_aod_run(aod_run_id)
    return {
        "aod_run_id": aod_run_id,
        "candidates": candidates,
        "count": len(candidates)
    }


@app.get("/api/handoff/aod/run/{aod_run_id}/reconciliation", tags=["AOD Handoff"])
async def get_aod_run_reconciliation(aod_run_id: str):
    """
    Reconcile AOD handoff data with AAM storage.
    
    Compares what AOD sent vs what AAM stored:
    - Candidates (which ARE pipes by canonical definition)
    - Fabric planes
    - SORs
    
    Use this to diagnose data integrity issues.
    """
    from .db import get_aod_reconciliation
    reconciliation = get_aod_reconciliation(aod_run_id)
    return reconciliation


@app.get("/ui/reconcile/{aod_run_id}", response_class=HTMLResponse, include_in_schema=False)
async def ui_reconcile(aod_run_id: str):
    """Reconciliation UI - human-readable view of AOD handoff reconciliation"""
    from .db import get_aod_reconciliation
    data = get_aod_reconciliation(aod_run_id)
    
    if data.get("error"):
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Reconciliation - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
</head>
<body>
    {ui_nav()}
    <div class="container">
        <h1>Reconciliation</h1>
        <div class="panel" style="text-align: center; padding: 48px;">
            <div style="font-size: 1.1rem; color: var(--red-400); margin-bottom: 8px;">Run Not Found</div>
            <div style="color: var(--slate-400); font-family: monospace;">{aod_run_id}</div>
            <a href="/ui/pipes" class="btn" style="margin-top: 16px;">Back to Pipes</a>
        </div>
    </div>
</body>
</html>
""")
    
    aod_sent = data["aod_sent"]
    aam = data["aam_stored"]
    recon = data["reconciliation"]
    snapshot = data.get("snapshot_name") or ""
    timestamp = data.get("handoff_timestamp", "")[:19] if data.get("handoff_timestamp") else "N/A"
    
    # Overall status
    all_match = recon["candidates_match"] and recon["pipes_match"]
    status_color = "var(--green-400)" if all_match else "var(--red-400)"
    status_icon = "&#10003;" if all_match else "&#10007;"
    status_text = "All Reconciled" if all_match else "Discrepancy Detected"
    
    # Fabric plane bars
    fabric_types = ["API_GATEWAY", "DATA_WAREHOUSE", "IPAAS", "EVENT_BUS"]
    fabric_colors = {
        "API_GATEWAY": "var(--cyan-400)",
        "DATA_WAREHOUSE": "var(--blue-400)",
        "IPAAS": "var(--purple-400)",
        "EVENT_BUS": "var(--orange-400)"
    }
    fabric_labels = {
        "API_GATEWAY": "API Gateway",
        "DATA_WAREHOUSE": "Data Warehouse",
        "IPAAS": "iPaaS",
        "EVENT_BUS": "Event Bus"
    }
    fabrics_by_type = aam.get("fabrics_by_type", {})
    max_fabric = max(fabrics_by_type.values()) if fabrics_by_type else 1
    
    fabric_bars_html = ""
    for ft in fabric_types:
        count = fabrics_by_type.get(ft, 0)
        pct = int((count / max_fabric) * 100) if max_fabric > 0 and count > 0 else 0
        color = fabric_colors.get(ft, "var(--slate-400)")
        label = fabric_labels.get(ft, ft)
        fabric_bars_html += f"""
        <div style="margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="font-size: 0.8rem; color: #cbd5e1;">{label}</span>
                <span style="font-size: 0.8rem; font-weight: 600; color: {color};">{count}</span>
            </div>
            <div style="height: 6px; background: var(--slate-800); border-radius: 3px; overflow: hidden;">
                <div style="height: 100%; width: {pct}%; background: {color}; border-radius: 3px; transition: width 0.3s;"></div>
            </div>
        </div>
        """
    
    # Category breakdown
    candidates_by_cat = aam.get("candidates_by_category", {})
    sor_categories = {"crm", "erp", "hcm", "idp", "itsm"}
    cat_colors = {
        "crm": "var(--cyan-400)", "erp": "var(--blue-400)", "hcm": "var(--green-400)",
        "idp": "var(--purple-400)", "itsm": "var(--orange-400)", "other": "var(--slate-400)",
        "unknown": "var(--slate-500)"
    }
    
    category_rows_html = ""
    for cat, count in sorted(candidates_by_cat.items(), key=lambda x: -x[1]):
        is_sor = cat in sor_categories
        color = cat_colors.get(cat, "var(--slate-400)")
        sor_badge = f'<span class="badge badge-connected" style="margin-left: 8px; font-size: 0.65rem;">SOR</span>' if is_sor else ''
        category_rows_html += f"""
        <tr>
            <td>
                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: {color}; margin-right: 8px;"></span>
                <span style="text-transform: uppercase; font-weight: 500;">{cat}</span>
                {sor_badge}
            </td>
            <td style="text-align: right; font-weight: 600; color: {color};">{count}</td>
        </tr>
        """
    
    # Reconciliation check rows
    def check_row(label, expected, actual, match):
        icon = "&#10003;" if match else "&#10007;"
        color = "var(--green-400)" if match else "var(--red-400)"
        bg = "rgba(34, 197, 94, 0.08)" if match else "rgba(248, 113, 113, 0.08)"
        return f"""
        <tr style="background: {bg};">
            <td style="font-weight: 500;">{label}</td>
            <td style="text-align: center;">{expected}</td>
            <td style="text-align: center;">{actual}</td>
            <td style="text-align: center; color: {color}; font-size: 1.1rem;">{icon}</td>
        </tr>
        """
    
    checks_html = check_row("Candidates / Pipes", aod_sent["candidates_accepted"], aam["candidates"], recon["candidates_match"])
    
    discrepancy_html = ""
    if recon["discrepancy"] != 0:
        disc = recon["discrepancy"]
        direction = "more" if disc > 0 else "fewer"
        discrepancy_html = f"""
        <div style="background: rgba(248, 113, 113, 0.1); border: 1px solid rgba(248, 113, 113, 0.3); border-radius: 8px; padding: 12px 16px; margin-top: 16px; color: var(--red-400);">
            <strong>Discrepancy:</strong> AOD accepted {abs(disc)} {direction} candidate(s) than AAM stored.
        </div>
        """
    
    # ===== DEEP CHECKS HTML =====
    deep = data.get("deep_checks", {})
    total_issues = deep.get("total_issues", 0)
    
    def check_header(title, has_issues, issue_count=0, description=""):
        icon = "&#10007;" if has_issues else "&#10003;"
        color = "var(--red-400)" if has_issues else "var(--green-400)"
        bg = "rgba(248, 113, 113, 0.1)" if has_issues else "rgba(34, 197, 94, 0.1)"
        border = "rgba(248, 113, 113, 0.3)" if has_issues else "rgba(34, 197, 94, 0.3)"
        count_badge = f'<span style="background: {bg}; color: {color}; padding: 2px 10px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; margin-left: 8px;">{issue_count} issue{"s" if issue_count != 1 else ""}</span>' if has_issues else '<span style="background: rgba(34, 197, 94, 0.1); color: var(--green-400); padding: 2px 10px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; margin-left: 8px;">Pass</span>'
        desc_html = f'<div style="color: var(--slate-400); font-size: 0.8rem; margin-top: 2px;">{description}</div>' if description else ''
        return f"""
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--slate-700);">
            <div>
                <span style="color: {color}; font-size: 1.1rem; margin-right: 8px;">{icon}</span>
                <span style="font-size: 1rem; font-weight: 600; color: #e2e8f0;">{title}</span>
                {count_badge}
                {desc_html}
            </div>
        </div>
        """
    
    # --- Deep Check 1: Vendor Matching ---
    vm = deep.get("vendor_matching", {})
    vm_issues = vm.get("case_duplicates", [])
    
    vm_content = ""
    if vm_issues:
        vm_rows = ""
        for dup in vm_issues:
            variants_str = ", ".join([f'"{v["name"]}" ({v["count"]})' for v in dup["variants"]])
            vm_rows += f"""
            <tr>
                <td style="font-weight: 500;">{dup["canonical"]}</td>
                <td style="font-size: 0.85rem;">{variants_str}</td>
                <td style="text-align: right; font-weight: 600;">{dup["total"]}</td>
            </tr>
            """
        vm_content = f"""
        <div style="color: var(--orange-400); font-size: 0.85rem; margin-bottom: 12px;">
            The following vendor names appear with different capitalization, which may cause duplicate entries.
        </div>
        <table>
            <thead><tr><th>Canonical Name</th><th>Variants Found</th><th style="text-align: right;">Total</th></tr></thead>
            <tbody>{vm_rows}</tbody>
        </table>
        """
    else:
        vm_content = f'<div style="color: var(--slate-400); font-size: 0.85rem;">{vm.get("total_vendors", 0)} unique vendors stored. No case-sensitivity duplicates found.</div>'
    
    # --- Deep Check 2: Candidate Row Check ---
    cr = deep.get("candidate_rows", {})
    cr_unconnected = cr.get("unconnected", [])
    cr_blocked = cr.get("blocked", [])
    cr_issue_count = cr.get("unconnected_count", 0) + cr.get("blocked_count", 0)
    
    cr_content = ""
    if cr_unconnected:
        cr_rows = ""
        for c in cr_unconnected[:15]:
            cr_rows += f"""
            <tr>
                <td style="font-family: monospace; font-size: 0.75rem;">{c["candidate_id"][:12]}...</td>
                <td>{c["vendor"]}</td>
                <td>{c["display_name"]}</td>
                <td><span class="badge badge-{'new' if c['status'].lower() not in ('new','triaged','connected','deferred','open','acknowledged','suppressed','resolved') else c['status'].lower()}">{c["status"]}</span></td>
            </tr>
            """
        more_text = f'<div style="color: var(--slate-400); font-size: 0.8rem; margin-top: 8px;">...and {cr.get("unconnected_count", 0) - 15} more</div>' if cr.get("unconnected_count", 0) > 15 else ""
        cr_content += f"""
        <div style="margin-bottom: 16px;">
            <div style="font-size: 0.85rem; font-weight: 500; color: var(--orange-400); margin-bottom: 8px;">Unconnected Candidates ({cr.get("unconnected_count", 0)})</div>
            <table>
                <thead><tr><th>ID</th><th>Vendor</th><th>Name</th><th>Status</th></tr></thead>
                <tbody>{cr_rows}</tbody>
            </table>
            {more_text}
        </div>
        """
    
    if cr_blocked:
        bl_rows = ""
        for c in cr_blocked[:10]:
            bl_rows += f"""
            <tr>
                <td style="font-family: monospace; font-size: 0.75rem;">{c["candidate_id"][:12]}...</td>
                <td>{c["vendor"]}</td>
                <td>{c["display_name"]}</td>
                <td><span class="badge badge-critical">Blocked</span></td>
            </tr>
            """
        cr_content += f"""
        <div>
            <div style="font-size: 0.85rem; font-weight: 500; color: var(--red-400); margin-bottom: 8px;">Execution-Blocked Candidates ({cr.get("blocked_count", 0)})</div>
            <table>
                <thead><tr><th>ID</th><th>Vendor</th><th>Name</th><th>Status</th></tr></thead>
                <tbody>{bl_rows}</tbody>
            </table>
        </div>
        """
    
    if not cr_content:
        cr_content = f'<div style="color: var(--slate-400); font-size: 0.85rem;">All {cr.get("total", 0)} candidates are connected and execution-allowed.</div>'
    
    # --- Deep Check 3: Fabric Plane Comparison ---
    fc = deep.get("fabric_comparison", {})
    fc_vendors = fc.get("vendors", [])
    fc_mismatches = fc.get("mismatches", 0)
    has_aod_fabric = fc.get("has_aod_data", False)
    fc_only_aod = fc.get("only_in_aod", [])
    fc_only_aam = fc.get("only_in_aam", [])
    fc_in_both = fc.get("in_both", [])
    
    plane_labels = {
        "IPAAS": "iPaaS", "API_GATEWAY": "API GW", "EVENT_BUS": "Event Bus", "DATA_WAREHOUSE": "DW"
    }
    
    def vendor_badge(name, style_type="default"):
        if style_type == "aod":
            return f'<span style="display: inline-block; background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.3); padding: 3px 10px; border-radius: 4px; font-size: 0.8rem; margin: 2px; color: #a5b4fc;">{name}</span>'
        elif style_type == "aam":
            return f'<span style="display: inline-block; background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.3); padding: 3px 10px; border-radius: 4px; font-size: 0.8rem; margin: 2px; color: #86efac;">{name}</span>'
        elif style_type == "match":
            return f'<span style="display: inline-block; background: rgba(34,197,94,0.05); border: 1px solid rgba(34,197,94,0.2); padding: 3px 10px; border-radius: 4px; font-size: 0.8rem; margin: 2px; color: #86efac;">{name}</span>'
        elif style_type == "mismatch":
            return f'<span style="display: inline-block; background: rgba(248,113,113,0.1); border: 1px solid rgba(248,113,113,0.3); padding: 3px 10px; border-radius: 4px; font-size: 0.8rem; margin: 2px; color: #fca5a5;">{name}</span>'
        elif style_type == "warning":
            return f'<span style="display: inline-block; background: rgba(251,191,36,0.1); border: 1px solid rgba(251,191,36,0.3); padding: 3px 10px; border-radius: 4px; font-size: 0.8rem; margin: 2px; color: #fcd34d;">{name}</span>'
        else:
            return f'<span style="display: inline-block; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); padding: 3px 10px; border-radius: 4px; font-size: 0.8rem; margin: 2px; color: #e2e8f0;">{name}</span>'
    
    fc_content = ""
    if not has_aod_fabric:
        fc_content += '<div style="color: var(--slate-400); font-size: 0.85rem; margin-bottom: 12px; padding: 8px; background: rgba(255,255,255,0.02); border-radius: 6px;">AOD did not provide explicit fabric planes for this run. Re-send from AOD with fabric_planes to enable side-by-side comparison.</div>'
    
    if has_aod_fabric and fc_vendors:
        # Global vendor comparison table
        fc_content += """
        <div style="margin-bottom: 12px;">
            <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
                <thead>
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                        <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Vendor</th>
                        <th style="text-align: center; padding: 8px; color: #a5b4fc; font-weight: 500;">AOD Type</th>
                        <th style="text-align: center; padding: 8px; color: #86efac; font-weight: 500;">AAM Type</th>
                        <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Status</th>
                    </tr>
                </thead>
                <tbody>
        """
        for v in fc_vendors:
            vendor_name = v["vendor"]
            aod_type = plane_labels.get(v.get("aod_plane_type", ""), v.get("aod_plane_type") or "-")
            aam_type = plane_labels.get(v.get("aam_plane_type", ""), v.get("aam_plane_type") or "-")
            status = v["status"]
            
            if status == "match":
                status_html = '<span style="color: var(--green-400);">&#10003; Match</span>'
                row_bg = "rgba(34,197,94,0.03)"
            elif status == "type_mismatch":
                status_html = '<span style="color: #fcd34d;">&#9888; Type differs</span>'
                row_bg = "rgba(251,191,36,0.03)"
            elif status == "only_aod":
                status_html = '<span style="color: #fca5a5;">Missing in AAM</span>'
                row_bg = "rgba(248,113,113,0.03)"
            else:
                status_html = '<span style="color: #93c5fd;">Extra in AAM</span>'
                row_bg = "rgba(147,197,253,0.03)"
            
            aod_cell = f'<span style="color: #a5b4fc;">{aod_type}</span>' if v.get("aod_plane_type") else '<span style="color: var(--slate-600);">-</span>'
            aam_cell = f'<span style="color: #86efac;">{aam_type}</span>' if v.get("aam_plane_type") else '<span style="color: var(--slate-600);">-</span>'
            
            fc_content += f"""
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: {row_bg};">
                        <td style="padding: 8px; font-weight: 500; color: #e2e8f0;">{vendor_name}</td>
                        <td style="padding: 8px; text-align: center;">{aod_cell}</td>
                        <td style="padding: 8px; text-align: center;">{aam_cell}</td>
                        <td style="padding: 8px; text-align: center; font-size: 0.8rem;">{status_html}</td>
                    </tr>
            """
        
        fc_content += """
                </tbody>
            </table>
        </div>
        """
        
        # Summary deltas
        if fc_only_aod:
            fc_content += '<div style="margin-top: 8px; padding: 8px; background: rgba(248,113,113,0.05); border-radius: 6px; border-left: 3px solid rgba(248,113,113,0.5);">'
            fc_content += '<div style="font-size: 0.75rem; color: #fca5a5; margin-bottom: 4px; font-weight: 600;">Missing in AAM (AOD expects these)</div>'
            fc_content += " ".join([vendor_badge(v, "mismatch") for v in fc_only_aod])
            fc_content += '</div>'
        if fc_only_aam:
            fc_content += '<div style="margin-top: 8px; padding: 8px; background: rgba(147,197,253,0.05); border-radius: 6px; border-left: 3px solid rgba(147,197,253,0.5);">'
            fc_content += '<div style="font-size: 0.75rem; color: #93c5fd; margin-bottom: 4px; font-weight: 600;">Extra in AAM (not in AOD)</div>'
            fc_content += " ".join([vendor_badge(v, "aod") for v in fc_only_aam])
            fc_content += '</div>'
    elif not has_aod_fabric:
        # No AOD data, just show AAM's state
        for v in fc_vendors:
            fc_content += vendor_badge(v["vendor"]) + " "
        if not fc_vendors:
            fc_content += '<div style="color: var(--slate-500); font-size: 0.85rem;">No fabric planes registered.</div>'
    
    # --- Deep Check 3b: SOR Vendor Comparison ---
    sc_sor = deep.get("sor_comparison", {})
    sor_vendors_list = sc_sor.get("vendors", [])
    sor_by_cat = sc_sor.get("by_category", [])
    sor_mismatches = sc_sor.get("mismatches", 0)
    has_aod_sor = sc_sor.get("has_aod_data", False)
    sor_only_aod = sc_sor.get("only_in_aod", [])
    sor_only_aam = sc_sor.get("only_in_aam", [])
    sor_in_both = sc_sor.get("in_both", [])
    
    sor_content = ""
    
    if not has_aod_sor:
        sor_content += '<div style="color: var(--slate-400); font-size: 0.85rem; margin-bottom: 12px; padding: 8px; background: rgba(255,255,255,0.02); border-radius: 6px;">AOD SOR data not stored for this run. Future handoffs will capture AOD SOR vendors for side-by-side comparison.</div>'
    
    if has_aod_sor and sor_vendors_list:
        cat_labels_sor = {
            "crm": "CRM", "erp": "ERP", "hcm": "HCM", "idp": "Identity", "itsm": "ITSM"
        }
        
        # Global SOR vendor comparison table
        sor_content += """
        <div style="margin-bottom: 12px;">
            <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
                <thead>
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                        <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Vendor</th>
                        <th style="text-align: center; padding: 8px; color: #a5b4fc; font-weight: 500;">AOD Category</th>
                        <th style="text-align: center; padding: 8px; color: #86efac; font-weight: 500;">AAM Pipes</th>
                        <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Status</th>
                    </tr>
                </thead>
                <tbody>
        """
        for v in sor_vendors_list:
            vendor_name = v["vendor"]
            aod_cat = cat_labels_sor.get(v.get("aod_category", ""), v.get("aod_category") or "-")
            aam_pipes = v.get("aam_pipe_count", 0)
            status = v["status"]
            
            if status == "match":
                status_html = f'<span style="color: var(--green-400);">&#10003; {aam_pipes} pipe{"s" if aam_pipes != 1 else ""}</span>'
                row_bg = "rgba(34,197,94,0.03)"
            elif status == "only_aod":
                status_html = '<span style="color: #fca5a5;">No pipes in AAM</span>'
                row_bg = "rgba(248,113,113,0.03)"
            else:
                status_html = f'<span style="color: #93c5fd;">{aam_pipes} pipe{"s" if aam_pipes != 1 else ""} (not in AOD)</span>'
                row_bg = "rgba(147,197,253,0.03)"
            
            aod_cell = f'<span style="color: #a5b4fc;">{aod_cat}</span>' if v.get("aod_category") else '<span style="color: var(--slate-600);">-</span>'
            
            sor_content += f"""
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: {row_bg};">
                        <td style="padding: 8px; font-weight: 500; color: #e2e8f0;">{vendor_name}</td>
                        <td style="padding: 8px; text-align: center;">{aod_cell}</td>
                        <td style="padding: 8px; text-align: center; color: #86efac;">{aam_pipes if aam_pipes > 0 else '<span style="color: var(--slate-600);">0</span>'}</td>
                        <td style="padding: 8px; text-align: center; font-size: 0.8rem;">{status_html}</td>
                    </tr>
            """
        
        sor_content += """
                </tbody>
            </table>
        </div>
        """
        
        # Summary deltas
        if sor_only_aod:
            sor_content += '<div style="margin-top: 8px; padding: 8px; background: rgba(248,113,113,0.05); border-radius: 6px; border-left: 3px solid rgba(248,113,113,0.5);">'
            sor_content += '<div style="font-size: 0.75rem; color: #fca5a5; margin-bottom: 4px; font-weight: 600;">AOD found these SOR vendors but AAM has no pipes for them</div>'
            sor_content += " ".join([vendor_badge(v, "mismatch") for v in sor_only_aod])
            sor_content += '</div>'
        if sor_only_aam:
            sor_content += '<div style="margin-top: 8px; padding: 8px; background: rgba(147,197,253,0.05); border-radius: 6px; border-left: 3px solid rgba(147,197,253,0.5);">'
            sor_content += '<div style="font-size: 0.75rem; color: #93c5fd; margin-bottom: 4px; font-weight: 600;">AAM has pipes for vendors AOD did not report</div>'
            sor_content += " ".join([vendor_badge(v, "aod") for v in sor_only_aam])
            sor_content += '</div>'
    elif not has_aod_sor and sor_vendors_list:
        # No AOD data, show AAM's declared pipe vendors
        for v in sor_vendors_list:
            sor_content += vendor_badge(f'{v["vendor"]} ({v["aam_pipe_count"]} pipes)') + " "
    elif not sor_vendors_list:
        sor_content += '<div style="color: var(--slate-500); font-size: 0.85rem;">No SOR vendors to compare.</div>'
    
    # --- Deep Check 4: Schema Completeness ---
    sc = deep.get("schema_completeness", {})
    sc_score = sc.get("completeness_score", 100)
    sc_field_counts = sc.get("field_missing_counts", {})
    sc_incomplete = sc.get("incomplete_candidates", [])
    sc_total = sc.get("total_candidates", 0)
    
    sc_bar_color = "var(--green-400)" if sc_score >= 80 else ("var(--orange-400)" if sc_score >= 50 else "var(--red-400)")
    
    sc_content = f"""
    <div style="margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
            <span style="font-size: 0.85rem; color: #cbd5e1;">Data Completeness</span>
            <span style="font-size: 0.85rem; font-weight: 600; color: {sc_bar_color};">{sc_score}%</span>
        </div>
        <div style="height: 8px; background: var(--slate-800); border-radius: 4px; overflow: hidden;">
            <div style="height: 100%; width: {sc_score}%; background: {sc_bar_color}; border-radius: 4px;"></div>
        </div>
        <div style="font-size: 0.8rem; color: var(--slate-400); margin-top: 4px;">{sc.get("incomplete_count", 0)} of {sc_total} candidates have missing fields</div>
    </div>
    """
    
    if sc_field_counts:
        field_labels = {
            "vendor_name": "Vendor Name",
            "display_name": "Display Name",
            "category": "Category",
            "known_endpoints": "Endpoints",
            "preferred_modality": "Modality",
            "connected_via_plane": "Fabric Plane"
        }
        max_field = max(sc_field_counts.values()) if sc_field_counts else 1
        for field, count in sorted(sc_field_counts.items(), key=lambda x: -x[1]):
            if count == 0:
                continue
            pct = int((count / max(max_field, 1)) * 100)
            label = field_labels.get(field, field)
            sc_content += f"""
            <div style="margin-bottom: 6px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                    <span style="font-size: 0.8rem; color: #cbd5e1;">{label}</span>
                    <span style="font-size: 0.8rem; color: var(--orange-400);">{count} missing</span>
                </div>
                <div style="height: 4px; background: var(--slate-800); border-radius: 2px; overflow: hidden;">
                    <div style="height: 100%; width: {pct}%; background: var(--orange-400); border-radius: 2px;"></div>
                </div>
            </div>
            """
    
    # --- Deep Check 5: Duplicate Detection ---
    dd = deep.get("duplicates", {})
    dd_groups = dd.get("duplicate_groups", [])
    dd_total = dd.get("total_duplicate_rows", 0)
    
    dd_content = ""
    if dd_groups:
        dd_rows = ""
        for g in dd_groups[:15]:
            dd_rows += f"""
            <tr>
                <td style="font-weight: 500;">{g["vendor"]}</td>
                <td>{g["display_name"]}</td>
                <td><span style="text-transform: uppercase; font-size: 0.8rem;">{g["category"]}</span></td>
                <td style="text-align: right; font-weight: 600; color: var(--orange-400);">{g["count"]}</td>
            </tr>
            """
        more_text = f'<div style="color: var(--slate-400); font-size: 0.8rem; margin-top: 8px;">...and {dd.get("total_groups", 0) - 15} more groups</div>' if dd.get("total_groups", 0) > 15 else ""
        dd_content = f"""
        <div style="color: var(--orange-400); font-size: 0.85rem; margin-bottom: 12px;">
            {dd_total} candidate rows across {dd.get("total_groups", 0)} groups share the same vendor + display name combination.
        </div>
        <table>
            <thead><tr><th>Vendor</th><th>Display Name</th><th>Category</th><th style="text-align: right;">Copies</th></tr></thead>
            <tbody>{dd_rows}</tbody>
        </table>
        {more_text}
        """
    else:
        dd_content = '<div style="color: var(--slate-400); font-size: 0.85rem;">No duplicate candidates detected.</div>'
    
    # Overall status: factor in deep checks
    has_deep_issues = total_issues > 0
    overall_match = all_match and not has_deep_issues
    overall_color = "var(--green-400)" if overall_match else ("var(--orange-400)" if all_match else "var(--red-400)")
    overall_icon = "&#10003;" if overall_match else "&#9888;" if all_match else "&#10007;"
    overall_text = "All Clear" if overall_match else (f"{total_issues} Issue{'s' if total_issues != 1 else ''} Found" if all_match else "Discrepancy + Issues")
    if overall_match:
        overall_bg_color = "rgba(34, 197, 94, 0.1)"
        overall_border = "1px solid rgba(34, 197, 94, 0.3)"
    elif all_match:
        overall_bg_color = "rgba(251, 146, 60, 0.1)"
        overall_border = "1px solid rgba(251, 146, 60, 0.3)"
    else:
        overall_bg_color = "rgba(248, 113, 113, 0.1)"
        overall_border = "1px solid rgba(248, 113, 113, 0.3)"
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Reconcile: {snapshot or aod_run_id} - AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
    <style>
        .recon-status {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 1rem;
        }}
        .recon-meta {{
            display: flex;
            gap: 24px;
            flex-wrap: wrap;
            color: var(--slate-400);
            font-size: 0.85rem;
            margin-bottom: 24px;
        }}
        .recon-meta strong {{
            color: #cbd5e1;
        }}
        .deep-check {{
            margin-bottom: 24px;
        }}
    </style>
</head>
<body>
    {ui_nav()}
    <div class="container">
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 8px;">
            <h1 style="margin-bottom: 0;">Reconciliation Report</h1>
            <div class="recon-status" style="background: {overall_bg_color}; border: {overall_border}; color: {overall_color};">
                <span style="font-size: 1.2rem;">{overall_icon}</span>
                {overall_text}
            </div>
        </div>
        
        <div class="recon-meta">
            {'<div><strong>Snapshot:</strong> <span style="color: #f0abfc;">' + snapshot + '</span></div>' if snapshot else ''}
            <div><strong>Run ID:</strong> <span style="font-family: monospace;">{aod_run_id}</span></div>
            <div><strong>Timestamp:</strong> {timestamp}</div>
        </div>

        <!-- KPI Stats -->
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{aod_sent["candidates_accepted"]}</div>
                <div class="stat-label">AOD Sent</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: var(--green-400);">{aam["candidates"]}</div>
                <div class="stat-label">AAM Stored</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: var(--purple-400);">{aam["fabric_planes"]}</div>
                <div class="stat-label">Fabric Planes</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: var(--blue-400);">{aam["sors"]}</div>
                <div class="stat-label">SOR Candidates</div>
            </div>
        </div>

        <!-- Data Integrity Check -->
        <div class="section">
            <div class="panel">
                <div class="panel-title">Data Integrity Check</div>
                <table>
                    <thead>
                        <tr>
                            <th>Check</th>
                            <th style="text-align: center;">AOD Accepted</th>
                            <th style="text-align: center;">AAM Stored</th>
                            <th style="text-align: center;">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {checks_html}
                    </tbody>
                </table>
                {discrepancy_html}
            </div>
        </div>

        <div class="grid-2">
            <div class="panel">
                <div class="panel-title">Fabric Planes by Type</div>
                {fabric_bars_html if fabric_bars_html else '<div style="color: var(--slate-500); font-size: 0.85rem;">No fabric planes found for this run.</div>'}
            </div>
            <div class="panel">
                <div class="panel-title">Candidates by Category</div>
                <table>
                    <thead><tr><th>Category</th><th style="text-align: right;">Count</th></tr></thead>
                    <tbody>
                        {category_rows_html if category_rows_html else '<tr><td colspan="2" style="color: var(--slate-500);">No categories found.</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Deep Checks Section -->
        <h2 style="margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--slate-700);">Deep Reconciliation Checks</h2>
        <p class="page-subtitle" style="margin-top: -8px;">Detailed data quality analysis across 6 dimensions</p>

        <!-- Check 1: Vendor Matching -->
        <div class="deep-check">
            <div class="panel" data-testid="check-vendor-matching">
                {check_header("Vendor Name Consistency", vm.get("has_issues", False), len(vm_issues), "Detects case-sensitivity duplicates across vendor names")}
                {vm_content}
            </div>
        </div>

        <!-- Check 2: Candidate Row Check -->
        <div class="deep-check">
            <div class="panel" data-testid="check-candidate-rows">
                {check_header("Candidate Row Integrity", cr.get("has_issues", False), cr_issue_count, "Flags candidates not connected or blocked from execution")}
                {cr_content}
            </div>
        </div>

        <!-- Check 3: Fabric Plane Comparison -->
        <div class="deep-check">
            <div class="panel" data-testid="check-fabric-comparison">
                {check_header("Fabric Plane Comparison", fc.get("has_issues", False), fc_mismatches, "Compares AOD-declared fabric vendors vs AAM current state")}
                {fc_content}
            </div>
        </div>

        <!-- Check 3b: SOR Vendor Comparison -->
        <div class="deep-check">
            <div class="panel" data-testid="check-sor-comparison">
                {check_header("SOR Vendor Comparison", sc_sor.get("has_issues", False), sor_mismatches, "Compares SOR vendors by category between AOD and AAM")}
                {sor_content}
            </div>
        </div>

        <!-- Check 4: Schema Completeness -->
        <div class="deep-check">
            <div class="panel" data-testid="check-schema-completeness">
                {check_header("Schema Completeness", sc.get("has_issues", False), sc.get("incomplete_count", 0), "Identifies candidates with missing key data fields")}
                {sc_content}
            </div>
        </div>

        <!-- Check 5: Duplicate Detection -->
        <div class="deep-check">
            <div class="panel" data-testid="check-duplicates">
                {check_header("Duplicate Detection", dd.get("has_issues", False), dd.get("total_groups", 0), "Finds candidates with identical vendor + display name combinations")}
                {dd_content}
            </div>
        </div>

        <div style="text-align: center; margin-top: 24px; padding-bottom: 32px;">
            <a href="/ui/pipes" class="btn" data-testid="link-back-pipes" style="margin-right: 8px;">Back to Pipes</a>
            <a href="/api/handoff/aod/run/{aod_run_id}/reconciliation" target="_blank" class="btn btn-sm" data-testid="link-raw-json" style="color: var(--slate-400); border-color: var(--slate-600);">View Raw JSON</a>
        </div>
    </div>
</body>
</html>
""")


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


# Alias endpoint to match documentation
@app.post("/api/collect/mock/run", tags=["Collectors"])
async def run_mock_alias(request: Optional[MockCollectorRequest] = None):
    """Run the mock collector (alias for /api/aam/collectors/mock/run)"""
    return await run_mock(request)


@app.post("/api/aam/infer", tags=["Collectors"])
async def infer_pipes():
    """Process pending observations and create pipes"""
    observations = get_unprocessed_observations()
    if not observations:
        return {"message": "No pending observations", "pipes_created": 0, "pipes": []}

    # Apply PII redaction based on current preset's governance policy
    policies = preset_loader.get_governance_policies()
    pii_policy = policies.get("pii_redaction", "optional")

    redacted_observations = []
    redaction_applied = 0
    for obs in observations:
        redacted_obs = redact_pii_from_observation(obs, policy=pii_policy)
        redacted_observations.append(redacted_obs)
        if redacted_obs.get("metadata", {}).get("pii_redacted"):
            redaction_applied += 1

    inferred_pipes = infer_pipes_from_observations(redacted_observations)

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
        "pipes": created_pipes,
        "pii_redaction_policy": pii_policy,
        "observations_redacted": redaction_applied
    }


@app.get("/api/pipes", tags=["Pipes"])
async def get_all_pipes(
    source_system: Optional[str] = Query(None, description="Filter by source system"),
    fabric_plane: Optional[str] = Query(None, description="Filter by fabric plane (IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE)")
):
    """List all declared pipes"""
    pipes = list_pipes(source_system=source_system, fabric_plane=fabric_plane)
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


@app.get("/api/dcl/export-pipes", tags=["DCL Export"], response_model=None)
async def export_pipes_for_dcl(aod_run_id: Optional[str] = Query(None, description="Filter by AOD run ID")):
    """
    Export pipe definitions grouped by fabric plane for DCL consumption.
    
    Returns candidates grouped into 4 fabric planes:
    - iPaaS (MuleSoft, Workato)
    - Warehouse (Snowflake, BigQuery)
    - API Gateway (Kong, Apigee)
    - Event Bus (Kafka, EventBridge)
    
    Each plane includes connections with inferred schemas.
    """
    from .dcl_export import build_dcl_export
    
    export_data = build_dcl_export(aod_run_id=aod_run_id)
    return export_data.model_dump()


@app.get("/api/drift", tags=["Drift"])
async def get_all_drift_events(limit: Optional[int] = Query(None, description="Maximum number of events (optional)")):
    """List all drift events"""
    events = list_all_drift_events(limit=limit)
    return {"drift_events": events, "count": len(events)}


# ============================================================================
# AAM V1 PRACTICAL INTERFACE ENDPOINTS
# ============================================================================

# --- Collector Run Tracking ---

@app.post("/api/collect/{collector}/run", tags=["Collectors"])
async def run_collector(collector: str, request: Optional[MockCollectorRequest] = None):
    """Run a collector and track the run. Supports 'mock' and 'adapter' collectors."""
    collector_id = f"{collector}-collector-001" if collector in ["mock", "adapter"] else collector
    
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
        elif collector == "adapter":
            if not adapter_registry:
                complete_collector_run(run_id, "failed", 0, "No adapters connected")
                raise HTTPException(status_code=400, detail="No adapters connected. Connect adapters first via /api/adapters/{plane_type}/connect")
            
            all_observations = []
            adapters_collected = []
            
            for plane_type, adapter in adapter_registry.items():
                health = await adapter.check_health()
                if health.status != AdapterStatus.CONNECTED:
                    continue
                
                policies = preset_loader.get_governance_policies()
                adapter.apply_governance_policy(policies)
                
                observations = await adapter.discover_pipes()
                
                # Get PII redaction policy
                pii_policy = policies.get("pii_redaction", "optional")

                for obs in observations:
                    obs_data = {
                        "observation_id": obs.get("observation_id"),
                        "collector_id": collector_id,
                        "candidate_id": None,
                        "source_system": obs.get("source_system", adapter.plane_vendor),
                        "endpoint_info": obs.get("endpoint_info", {}),
                        "entity_hints": obs.get("entity_hints", []),
                        "schema_sample": obs.get("schema_sample"),
                        "metadata": {
                            "plane_type": plane_type,
                            "vendor": adapter.plane_vendor,
                            "governance_applied": list(policies.keys()),
                            "preset": preset_loader.current_config.preset_id
                        }
                    }
                    # Apply PII redaction before storing
                    obs_data = redact_pii_from_observation(obs_data, policy=pii_policy)
                    create_observation(obs_data)
                    all_observations.append(obs_data)
                
                adapters_collected.append(plane_type)
            
            complete_collector_run(run_id, "completed", len(all_observations))
            return {
                "run_id": run_id,
                "collector": collector,
                "status": "completed",
                "observations_created": len(all_observations),
                "adapters_collected": adapters_collected,
                "current_preset": preset_loader.current_config.name,
                "observations": all_observations
            }
        else:
            complete_collector_run(run_id, "failed", 0, f"Unknown collector: {collector}")
            raise HTTPException(status_code=400, detail=f"Unknown collector: {collector}. Valid: mock, adapter")
    except HTTPException:
        raise
    except Exception as e:
        complete_collector_run(run_id, "failed", 0, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/collect/runs", tags=["Collectors"])
async def get_collector_runs(
    collector_id: Optional[str] = Query(None, description="Filter by collector ID"),
    limit: Optional[int] = Query(None, description="Maximum number of runs (optional)")
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
    """
    Attempt to match candidate to a pipe.

    Enforces AOD governance:
    - If execution_allowed=False, blocks auto-matching (requires human override)
    - If action_type="inventory_only", blocks auto-matching
    - Respects blocking_findings from AOD
    """
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # === AOD GOVERNANCE ENFORCEMENT ===
    execution_allowed = candidate.get("execution_allowed", True)
    action_type = candidate.get("action_type", "provision")
    blocking_findings = candidate.get("blocking_findings", [])

    # Check if this is an auto-match attempt (no pipe_id specified)
    is_auto_match = request.pipe_id is None

    if is_auto_match:
        # Enforce execution_allowed for auto-matching
        if not execution_allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Auto-matching blocked by AOD governance. "
                f"Candidate has execution_allowed=False. "
                f"Blocking findings: {blocking_findings}. "
                f"Manual review and explicit pipe_id required."
            )

        # Enforce action_type for auto-matching
        if action_type == "inventory_only":
            raise HTTPException(
                status_code=403,
                detail=f"Auto-matching blocked by AOD governance. "
                f"Candidate action_type is 'inventory_only' (requires human review). "
                f"Provide explicit pipe_id to override."
            )

    # For manual matches with pipe_id, warn but allow (human override)
    elif not execution_allowed or action_type == "inventory_only":
        # Log warning but allow manual override
        pass  # Future: could add audit log here

    # Check block direct access policy
    vendor = candidate.get("vendor_name", "")
    if preset_loader.should_block_direct_api(vendor):
        # In non-scrappy modes, we need to route through the appropriate fabric plane
        # Check if a direct API_GATEWAY connection is being attempted
        if request.pipe_id:
            pipe = get_pipe(request.pipe_id)
            if pipe and pipe.get("fabric_plane") == "API_GATEWAY":
                # Validate routing - this will fail for direct access in non-scrappy modes
                is_valid, block_reason = preset_loader.validate_candidate_routing(
                    vendor, FabricPlane.API_GATEWAY
                )
                if not is_valid:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Direct API access blocked: {block_reason}. "
                        f"Current preset ({preset_loader.current_config.name}) requires routing through "
                        f"{preset_loader.current_config.primary_plane.value}."
                    )

    pipe_id = request.pipe_id
    score = 1.0
    reason = "Manual match"

    if not pipe_id:
        # Try multiple auto-match strategies
        vendor = candidate.get("vendor_name", "").lower()
        category = candidate.get("category", "").lower()

        # Strategy 1: Exact vendor name match
        pipes = list_pipes(source_system=candidate.get("vendor_name"))
        if pipes:
            pipe_id = pipes[0]["pipe_id"]
            score = 0.9
            reason = "Auto-matched by vendor name"
        else:
            # Strategy 2: Partial vendor name match
            all_pipes = list_pipes(limit=200)
            for p in all_pipes:
                source = (p.get("source_system") or "").lower()
                if vendor and (vendor in source or source in vendor):
                    pipe_id = p["pipe_id"]
                    score = 0.7
                    reason = f"Auto-matched by partial vendor match ({p.get('source_system')})"
                    break

            # Strategy 3: Category-based match (if category contains hints)
            if not pipe_id:
                category_hints = {
                    "crm": ["salesforce", "hubspot", "dynamics"],
                    "collaboration": ["slack", "teams", "notion"],
                    "payment": ["stripe", "paypal", "square"],
                    "communication": ["twilio", "sendgrid"],
                    "analytics": ["segment", "mixpanel", "amplitude"],
                }
                for cat, sources in category_hints.items():
                    if cat in category:
                        for p in all_pipes:
                            source = (p.get("source_system") or "").lower()
                            if any(s in source for s in sources):
                                pipe_id = p["pipe_id"]
                                score = 0.5
                                reason = f"Auto-matched by category ({cat} -> {p.get('source_system')})"
                                break
                        if pipe_id:
                            break

            # Strategy 4: If still no match but pipes exist, create a new pipe from candidate
            if not pipe_id and all_pipes:
                # Determine fabric plane - prefer AOD's connected_via_plane hint if provided
                aod_plane_hint = candidate.get("connected_via_plane")
                candidate_category = candidate.get("category", "")

                if aod_plane_hint:
                    # AOD detected a fabric plane connection - use it
                    try:
                        routed_plane = FabricPlane(aod_plane_hint)
                        routing_source = "aod_hint"
                    except ValueError:
                        # Invalid plane from AOD, fall back to preset routing
                        routed_plane = preset_loader.get_routing_decision(candidate_category)
                        routing_source = "preset_fallback"
                else:
                    # No AOD hint, use preset routing policy
                    routed_plane = preset_loader.get_routing_decision(candidate_category)
                    routing_source = "preset"

                # Validate the routing is allowed
                is_valid, route_reason = preset_loader.validate_candidate_routing(
                    vendor, routed_plane
                )
                if not is_valid:
                    raise HTTPException(
                        status_code=403,
                        detail=f"Cannot create pipe: {route_reason}. "
                        f"Consider using preset 6 (Scrappy) for direct access, or connect "
                        f"to the appropriate fabric plane first."
                    )

                # Build provenance with AOD traceability
                lineage_hints = [f"candidate:{candidate_id}", f"routed_via:{routed_plane.value}"]
                if candidate.get("aod_run_id"):
                    lineage_hints.append(f"aod_run:{candidate.get('aod_run_id')}")
                if candidate.get("aod_asset_id"):
                    lineage_hints.append(f"aod_asset:{candidate.get('aod_asset_id')}")
                lineage_hints.append(f"routing_source:{routing_source}")

                # Create a new pipe from this candidate using the routed plane
                new_pipe_data = {
                    "display_name": candidate.get("display_name") or candidate.get("vendor_name"),
                    "source_system": candidate.get("vendor_name"),
                    "fabric_plane": routed_plane.value,
                    "modality": candidate.get("preferred_modality") or "DECLARED_INTERFACE",
                    "transport_kind": "API",
                    "provenance": {
                        "discovered_by": "auto-match",
                        "discovered_at": datetime.utcnow().isoformat(),
                        "lineage_hints": lineage_hints
                    }
                }
                result = create_pipe(new_pipe_data)
                pipe_id = result["pipe_id"]
                score = 0.6
                reason = f"Created new pipe from candidate ({candidate.get('vendor_name')}) via {routed_plane.value} ({routing_source})"

        if not pipe_id:
            raise HTTPException(
                status_code=400,
                detail="Auto-match failed and no pipes exist. Load a preset first or manually select a pipe."
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
    """Deprecated: Use TeeVerificationRequest instead"""
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


class TeeVerificationRequest(BaseModel):
    """Request model for TEE verification with validation details"""
    status: str
    verification_method: Optional[str] = None  # e.g., "manual_test", "automated_check", "log_review"
    verification_evidence: Optional[str] = None  # Evidence or notes about verification
    verified_by: Optional[str] = None  # Who performed the verification


@app.post("/api/tee/requests/{tee_id}/status", tags=["Tee Requests"])
async def update_tee_status(tee_id: str, request: TeeVerificationRequest):
    """
    Update TEE request status with workflow enforcement.

    Workflow: requested → approved → verified

    - To move to 'approved': Request must be in 'requested' status
    - To move to 'verified': Request must be in 'approved' status, and verification details should be provided
    """
    if request.status not in ["approved", "verified"]:
        raise HTTPException(status_code=400, detail="Status must be 'approved' or 'verified'")

    # Get current TEE request to validate workflow
    tee_req = get_tee_request(tee_id)
    if not tee_req:
        raise HTTPException(status_code=404, detail="TEE request not found")

    current_status = tee_req.get("status")

    # Enforce workflow transitions
    if request.status == "approved":
        if current_status != "requested":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve: TEE request is in '{current_status}' status. "
                "Only 'requested' status can be approved."
            )

    elif request.status == "verified":
        if current_status != "approved":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot verify: TEE request is in '{current_status}' status. "
                "Only 'approved' status can be verified. Approve the request first."
            )

        # Verification requires additional validation
        if not request.verification_method:
            raise HTTPException(
                status_code=400,
                detail="Verification requires a verification_method (e.g., 'manual_test', 'automated_check', 'log_review')"
            )

        # Validate that the TEE is actually working (simulation for now)
        pipe = get_pipe(tee_req["pipe_id"])
        if not pipe:
            raise HTTPException(
                status_code=400,
                detail="Cannot verify: Associated pipe no longer exists"
            )

    updated = update_tee_request_status(tee_id, request.status)
    if not updated:
        raise HTTPException(status_code=404, detail="TEE request not found")

    # Add verification metadata to response
    response = dict(updated)
    if request.status == "verified":
        response["verification"] = {
            "method": request.verification_method,
            "evidence": request.verification_evidence,
            "verified_by": request.verified_by,
            "pipe_status": "active" if pipe else "unknown"
        }

    return response


# ============================================================================
# FABRIC ADAPTER ENDPOINTS
# ============================================================================

@app.get("/api/adapters", tags=["Fabric Adapters"])
async def list_adapters():
    """List all registered fabric plane adapters and their status"""
    result = []
    for plane_type, adapter in adapter_registry.items():
        health = await adapter.check_health()
        result.append({
            "plane_type": plane_type,
            "vendor": adapter.plane_vendor,
            "status": health.status.value,
            "last_check": health.last_check.isoformat(),
            "latency_ms": health.latency_ms
        })
    return {"adapters": result, "count": len(result), "current_preset": preset_loader.current_config.name}


@app.post("/api/adapters/{plane_type}/connect", tags=["Fabric Adapters"])
async def connect_adapter(plane_type: str):
    """Connect to a fabric plane"""
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
        "vendor": adapter.plane_vendor
    }


@app.post("/api/adapters/{plane_type}/disconnect", tags=["Fabric Adapters"])
async def disconnect_adapter(plane_type: str):
    """Disconnect from a fabric plane"""
    if plane_type not in adapter_registry:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {plane_type}")
    
    adapter = adapter_registry[plane_type]
    success = await adapter.disconnect()
    return {"plane_type": plane_type, "disconnected": success}


@app.get("/api/adapters/{plane_type}/health", tags=["Fabric Adapters"])
async def check_adapter_health(plane_type: str):
    """Check health of a fabric plane adapter"""
    if plane_type not in adapter_registry:
        raise HTTPException(status_code=404, detail=f"Adapter not found: {plane_type}")
    
    adapter = adapter_registry[plane_type]
    health = await adapter.check_health()
    
    drift_event = drift_detector.detect_connection_drift(
        plane_type=plane_type,
        plane_vendor=adapter.plane_vendor,
        is_connected=(health.status == AdapterStatus.CONNECTED)
    )
    
    return {
        "plane_type": plane_type,
        "vendor": adapter.plane_vendor,
        "status": health.status.value,
        "latency_ms": health.latency_ms,
        "last_check": health.last_check.isoformat(),
        "metrics": health.metrics,
        "drift_detected": drift_event is not None,
        "drift_id": drift_event.drift_id if drift_event else None
    }


@app.post("/api/adapters/{plane_type}/discover", tags=["Fabric Adapters"])
async def discover_from_adapter(plane_type: str):
    """Discover pipes from a fabric plane adapter"""
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
        "governance_applied": list(policies.keys())
    }


@app.post("/api/adapters/{plane_type}/self-heal", tags=["Fabric Adapters"])
async def trigger_self_heal(plane_type: str):
    """Trigger self-healing for a fabric plane adapter"""
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
        results.append({
            "drift_id": drift.drift_id,
            "drift_type": drift.drift_type.value,
            "healed": success
        })
    
    return {"healed": healed, "total_drifts": len(drifts), "results": results}


# ============================================================================
# FABRIC DRIFT ENDPOINTS
# ============================================================================

@app.get("/api/fabric-drift", tags=["Fabric Drift"])
async def list_fabric_drift():
    """List all fabric plane drift events (connectivity drift, not schema drift)"""
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
                "auto_heal_success": d.auto_heal_success
            }
            for d in drifts
        ],
        "count": len(drifts)
    }


@app.get("/api/fabric-drift/stats", tags=["Fabric Drift"])
async def get_fabric_drift_stats():
    """Get fabric drift statistics"""
    return drift_detector.get_drift_stats()


@app.get("/api/fabric-drift/heal-history", tags=["Fabric Drift"])
async def get_heal_history():
    """Get self-healing history"""
    return {"history": drift_detector.get_heal_history()}


@app.post("/api/fabric-drift/{drift_id}/ack", tags=["Fabric Drift"])
async def acknowledge_fabric_drift(drift_id: str):
    """Acknowledge a fabric drift event"""
    success = drift_detector.acknowledge_drift(drift_id)
    if not success:
        raise HTTPException(status_code=404, detail="Drift event not found")
    return {"drift_id": drift_id, "acknowledged": True}


@app.post("/api/fabric-drift/{drift_id}/suppress", tags=["Fabric Drift"])
async def suppress_fabric_drift(drift_id: str):
    """Suppress a fabric drift event"""
    success = drift_detector.suppress_drift(drift_id)
    if not success:
        raise HTTPException(status_code=404, detail="Drift event not found")
    return {"drift_id": drift_id, "suppressed": True}


# ============================================================================
# PRESET CONFIG ENDPOINTS (Enhanced)
# ============================================================================

@app.get("/api/preset-config", tags=["Preset Config"])
async def get_current_preset_config():
    """Get the current enterprise preset configuration"""
    config = preset_loader.current_config
    return {
        "preset_id": config.preset_id,
        "name": config.name,
        "description": config.description,
        "primary_plane": config.primary_plane.value,
        "allowed_planes": [p.value for p in config.allowed_planes],
        "direct_access_allowed": config.direct_app_access,
        "policies": config.policies
    }


@app.post("/api/preset-config/{preset_name}/activate", tags=["Preset Config"])
async def activate_preset(preset_name: str):
    """Activate an enterprise preset (scrappy, ipaas_centric, platform_oriented, warehouse_centric)"""
    preset_map = {
        "scrappy": EnterpriseMaturity.SCRAPPY,
        "early_scrappy": EnterpriseMaturity.SCRAPPY,
        "ipaas_centric": EnterpriseMaturity.IPAAS_CENTRIC,
        "ipaas-centric": EnterpriseMaturity.IPAAS_CENTRIC,
        "platform_oriented": EnterpriseMaturity.PLATFORM_ORIENTED,
        "platform-oriented": EnterpriseMaturity.PLATFORM_ORIENTED,
        "warehouse_centric": EnterpriseMaturity.WAREHOUSE_CENTRIC,
        "warehouse-centric": EnterpriseMaturity.WAREHOUSE_CENTRIC
    }
    
    preset = preset_map.get(preset_name.lower())
    if not preset:
        raise HTTPException(status_code=400, detail=f"Unknown preset: {preset_name}. Valid: scrappy, ipaas_centric, platform_oriented, warehouse_centric")
    
    preset_loader.set_preset(preset)
    
    for adapter in adapter_registry.values():
        await adapter.disconnect()
    adapter_registry.clear()
    
    config = preset_loader.current_config
    return {
        "activated": preset_name,
        "preset_id": config.preset_id,
        "name": config.name,
        "primary_plane": config.primary_plane.value,
        "allowed_planes": [p.value for p in config.allowed_planes],
        "direct_access_allowed": config.direct_app_access,
        "adapters_cleared": True
    }


@app.get("/api/preset-config/all", tags=["Preset Config"])
async def list_all_preset_configs():
    """List all available enterprise preset configurations"""
    return {"presets": preset_loader.list_all_presets()}


@app.post("/api/preset-config/validate-routing", tags=["Preset Config"])
async def validate_routing(vendor: str, target_plane: str):
    """Validate if a routing decision is allowed under current preset"""
    try:
        plane_enum = FabricPlane(target_plane.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid plane: {target_plane}")
    
    allowed, reason = preset_loader.validate_candidate_routing(vendor, plane_enum)
    return {
        "vendor": vendor,
        "target_plane": target_plane,
        "allowed": allowed,
        "reason": reason,
        "current_preset": preset_loader.current_config.name
    }


# ============================================================================
# PRESETS / SEED DATA ENDPOINTS
# ============================================================================

import json
import os

PRESETS_DIR = os.path.join(os.path.dirname(__file__), "..", "samples", "presets")


@app.get("/api/presets", tags=["Presets"])
async def list_presets():
    """List available enterprise maturity presets"""
    presets = []
    if os.path.exists(PRESETS_DIR):
        for filename in os.listdir(PRESETS_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(PRESETS_DIR, filename)
                with open(filepath, "r") as f:
                    data = json.load(f)
                    presets.append({
                        "preset_id": data.get("preset_id", filename.replace(".json", "")),
                        "name": data.get("name", filename),
                        "description": data.get("description", ""),
                        "pipe_count": len(data.get("pipes", [])),
                        "candidate_count": len(data.get("candidates", []))
                    })
    return {"presets": presets, "count": len(presets)}


@app.get("/api/presets/{preset_id}", tags=["Presets"])
async def get_preset(preset_id: str):
    """Get details of a specific preset"""
    filepath = os.path.join(PRESETS_DIR, f"{preset_id}.json")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Preset not found")
    
    with open(filepath, "r") as f:
        data = json.load(f)
    return data


@app.post("/api/presets/{preset_id}/load", tags=["Presets"])
async def load_preset(preset_id: str, clear_existing: bool = Query(True, description="Clear existing data before loading")):
    """Load a preset - populates database with sample data"""
    filepath = os.path.join(PRESETS_DIR, f"{preset_id}.json")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Preset not found")

    with open(filepath, "r") as f:
        data = json.load(f)

    if clear_existing:
        clear_all_data()

    pipes_created = 0
    candidates_created = 0
    drift_events_created = 0
    created_pipe_ids = []

    for pipe_data in data.get("pipes", []):
        provenance = {
            "discovered_by": f"preset:{preset_id}",
            "discovered_at": datetime.utcnow().isoformat(),
            "lineage_hints": [f"preset:{preset_id}"]
        }
        pipe_data["provenance"] = provenance
        result = create_pipe(pipe_data)
        created_pipe_ids.append(result["pipe_id"])
        pipes_created += 1

    for candidate_data in data.get("candidates", []):
        create_candidate(candidate_data)
        candidates_created += 1

    # Generate sample drift events for some pipes
    import random
    drift_samples = [
        ("schema", "field: user_id (integer)", "field: user_id (string)", "high", "Field type changed from integer to string"),
        ("schema", "fields: [id, name, email]", "fields: [id, name, email, phone]", "low", "New field 'phone' added"),
        ("freshness", "last_update: 2024-01-15", "last_update: 2023-12-01", "critical", "Data not updated for 45 days"),
        ("contract", "rate_limit: 1000/min", "rate_limit: 100/min", "high", "API rate limit reduced by 90%"),
        ("schema", "nullable: false", "nullable: true", "medium", "Field nullability changed"),
        ("freshness", "sync_interval: 1h", "sync_interval: 24h", "medium", "Sync frequency reduced"),
        ("contract", "auth: api_key", "auth: oauth2", "high", "Authentication method changed"),
    ]

    # Add drift events to ~30% of pipes
    pipes_with_drift = random.sample(created_pipe_ids, min(len(created_pipe_ids) // 3 + 1, len(created_pipe_ids)))
    for pipe_id in pipes_with_drift:
        drift_type, old_val, new_val, severity, description = random.choice(drift_samples)
        drift_id = create_drift_event(pipe_id, drift_type, old_val, new_val, {"description": description})
        # Update severity (since create_drift_event uses defaults)
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE drift_events SET severity = ? WHERE drift_id = ?", (severity, drift_id))
        conn.commit()
        conn.close()
        drift_events_created += 1

    return {
        "preset_id": preset_id,
        "name": data.get("name"),
        "pipes_created": pipes_created,
        "candidates_created": candidates_created,
        "drift_events_created": drift_events_created,
        "message": f"Preset '{data.get('name')}' loaded successfully"
    }


@app.get("/api/stats", tags=["Stats"])
async def get_stats():
    """Get statistics about pipes by fabric_plane and modality"""
    stats = get_pipe_stats()
    candidates = list_candidates()
    stats["total_candidates"] = len(candidates)
    stats["candidates_by_status"] = {}
    for c in candidates:
        status = c.get("status", "new")
        stats["candidates_by_status"][status] = stats["candidates_by_status"].get(status, 0) + 1
    return stats


# ============================================================================
# TOPOLOGY API (Graph/Visualization)
# ============================================================================

@app.get("/api/topology", tags=["Topology"])
async def get_full_topology():
    """
    Get the complete topology graph for visualization.

    Returns nodes (fabric planes, source systems, pipes, candidates) and
    edges (relationships between them) suitable for graph visualization.

    Node types:
    - fabric_plane: Integration fabric (IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE)
    - source_system: Data source (Salesforce, Workato, etc.)
    - pipe: Declared data pipe
    - candidate: Connection candidate

    Edge types:
    - pipe_in_plane: Pipe belongs to a fabric plane
    - pipe_from_source: Pipe originates from a source system
    - candidate_to_pipe: Candidate matched to a pipe
    - candidate_for_source: Candidate targets a source system
    """
    from datetime import datetime
    topology = get_topology_data()
    return {
        "nodes": topology["nodes"],
        "edges": topology["edges"],
        "stats": topology["stats"],
        "generated_at": datetime.utcnow().isoformat()
    }


@app.get("/api/topology/nodes", tags=["Topology"])
async def get_topology_nodes(
    node_type: Optional[str] = Query(None, description="Filter by node type (fabric_plane, source_system, pipe, candidate)")
):
    """Get just the nodes from the topology graph, optionally filtered by type."""
    topology = get_topology_data()
    nodes = topology["nodes"]

    if node_type:
        nodes = [n for n in nodes if n["type"] == node_type]

    return {
        "nodes": nodes,
        "total": len(nodes),
        "filter": node_type
    }


@app.get("/api/topology/edges", tags=["Topology"])
async def get_topology_edges(
    edge_type: Optional[str] = Query(None, description="Filter by edge type (pipe_in_plane, pipe_from_source, candidate_to_pipe, candidate_for_source)")
):
    """Get just the edges from the topology graph, optionally filtered by type."""
    topology = get_topology_data()
    edges = topology["edges"]

    if edge_type:
        edges = [e for e in edges if e["type"] == edge_type]

    return {
        "edges": edges,
        "total": len(edges),
        "filter": edge_type
    }


@app.get("/api/topology/stats", tags=["Topology"])
async def get_topology_stats():
    """
    Get statistics about the topology.

    Returns counts of nodes/edges by type, list of fabric planes and source systems,
    and connectivity statistics.
    """
    topology = get_topology_data()
    return topology["stats"]


@app.get("/api/topology/pipe/{pipe_id}", tags=["Topology"])
async def get_pipe_topology(pipe_id: str):
    """
    Get topology centered on a specific pipe.

    Returns the pipe, its fabric plane, source system, and any connected candidates.
    Useful for focused visualization of a single pipe's context.
    """
    result = get_topology_for_pipe(pipe_id)
    if not result["nodes"]:
        raise HTTPException(status_code=404, detail=f"Pipe {pipe_id} not found")

    from datetime import datetime
    return {
        **result,
        "generated_at": datetime.utcnow().isoformat()
    }


@app.get("/api/topology/summary", tags=["Topology"])
async def get_topology_summary():
    """
    Get a lightweight topology showing only Fabric Planes and Systems of Record (SORs).
    
    This view is optimized for large datasets - it shows aggregate counts instead of
    individual assets, making it suitable for 600+ asset inventories.
    """
    from datetime import datetime
    
    pipes = list_pipes()
    candidates = list_candidates()
    
    # Build fabric plane nodes with counts
    fabric_counts = {"IPAAS": 0, "API_GATEWAY": 0, "EVENT_BUS": 0, "DATA_WAREHOUSE": 0}
    for p in pipes:
        plane = p.get("fabric_plane", "API_GATEWAY")
        if plane in fabric_counts:
            fabric_counts[plane] += 1
    
    # Count candidates by category mapped to planes
    # Note: AOD categories are business categories (CRM, ERP, etc.)
    # We need to use fabric_plane_id or connected_via_plane from the candidate
    candidate_counts = {"IPAAS": 0, "API_GATEWAY": 0, "EVENT_BUS": 0, "DATA_WAREHOUSE": 0, "OTHER": 0}
    for c in candidates:
        # Use fabric_plane_id to determine plane (set during AOD handoff)
        fabric_plane_id = c.get("fabric_plane_id", "")
        connected_via = c.get("connected_via_plane", "")

        # Extract plane type from fabric_plane_id (format: "PLANE_TYPE:vendor")
        if fabric_plane_id and ":" in fabric_plane_id:
            plane = fabric_plane_id.split(":")[0].upper()
        elif connected_via:
            plane = connected_via.upper()
        else:
            plane = "OTHER"

        if plane in candidate_counts:
            candidate_counts[plane] += 1
        else:
            candidate_counts["OTHER"] += 1

    # Build SOR nodes from source systems
    # SOR categories per canonical definition
    sor_categories = {"crm", "erp", "hcm", "idp", "itsm"}
    
    sor_systems = {}
    for p in pipes:
        source = p.get("source_system")
        if source:
            if source not in sor_systems:
                sor_systems[source] = {"pipe_count": 0, "candidate_count": 0, "planes": set(), "is_sor": False, "category": None}
            sor_systems[source]["pipe_count"] += 1
            sor_systems[source]["planes"].add(p.get("fabric_plane", "API_GATEWAY"))

    for c in candidates:
        vendor = c.get("vendor_name")
        if vendor:
            if vendor not in sor_systems:
                sor_systems[vendor] = {"pipe_count": 0, "candidate_count": 0, "planes": set(), "is_candidate": True, "is_sor": False, "category": None}
            sor_systems[vendor]["candidate_count"] = sor_systems[vendor].get("candidate_count", 0) + 1
            if "is_candidate" not in sor_systems[vendor]:
                sor_systems[vendor]["is_candidate"] = True
            
            # Mark as SOR if category matches
            category = c.get("category", "").lower()
            if category in sor_categories:
                sor_systems[vendor]["is_sor"] = True
                sor_systems[vendor]["category"] = category

            # Add plane connection for candidates using fabric_plane_id or connected_via_plane
            fabric_plane_id = c.get("fabric_plane_id", "")
            connected_via = c.get("connected_via_plane", "")

            if fabric_plane_id and ":" in fabric_plane_id:
                plane = fabric_plane_id.split(":")[0].upper()
                sor_systems[vendor]["planes"].add(plane)
            elif connected_via:
                sor_systems[vendor]["planes"].add(connected_via.upper())
    
    # Create nodes
    nodes = []
    edges = []
    
    # Fabric plane nodes
    plane_labels = {
        "IPAAS": "iPaaS",
        "API_GATEWAY": "API Gateway", 
        "EVENT_BUS": "Event Bus",
        "DATA_WAREHOUSE": "Data Warehouse"
    }
    for plane, label in plane_labels.items():
        pipe_count = fabric_counts.get(plane, 0)
        cand_count = candidate_counts.get(plane, 0)
        nodes.append({
            "id": f"plane:{plane}",
            "label": f"{label}\n({pipe_count} pipes, {cand_count} candidates)",
            "type": "fabric_plane",
            "metadata": {
                "plane_type": plane,
                "pipe_count": pipe_count,
                "candidate_count": cand_count
            }
        })
    
    # SOR nodes: Prioritize actual SORs (CRM, ERP, etc.), then fill with top others
    # First, get all true SORs (those with SOR categories)
    true_sors = [(name, data) for name, data in sor_systems.items() if data.get("is_sor")]
    true_sors = sorted(true_sors, key=lambda x: x[1]["pipe_count"] + x[1].get("candidate_count", 0), reverse=True)
    
    # Then get remaining non-SOR systems
    other_systems = [(name, data) for name, data in sor_systems.items() if not data.get("is_sor")]
    other_systems = sorted(other_systems, key=lambda x: x[1]["pipe_count"] + x[1].get("candidate_count", 0), reverse=True)
    
    # Combine: all true SORs + top remaining to reach 20 total
    remaining_slots = max(0, 20 - len(true_sors))
    sorted_sors = true_sors + other_systems[:remaining_slots]
    for sor_name, sor_data in sorted_sors:
        pipe_count = sor_data["pipe_count"]
        cand_count = sor_data.get("candidate_count", 0)
        # Show both counts in label
        if pipe_count > 0 and cand_count > 0:
            label = f"{sor_name}\n({pipe_count} pipes, {cand_count} candidates)"
        elif cand_count > 0:
            label = f"{sor_name}\n({cand_count} candidates)"
        else:
            label = f"{sor_name}\n({pipe_count} pipes)"

        nodes.append({
            "id": f"sor:{sor_name}",
            "label": label,
            "type": "source_system",
            "metadata": {
                "name": sor_name,
                "pipe_count": pipe_count,
                "candidate_count": cand_count,
                "is_candidate_source": sor_data.get("is_candidate", False),
                "is_sor": sor_data.get("is_sor", False),
                "category": sor_data.get("category")
            }
        })
        # Connect SOR to its planes
        for plane in sor_data.get("planes", []):
            edges.append({
                "id": f"sor_to_plane:{sor_name}:{plane}",
                "source": f"sor:{sor_name}",
                "target": f"plane:{plane}",
                "type": "sor_in_plane"
            })
    
    # Get canonical stats from single source of truth
    canonical_stats = get_canonical_stats()

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            # Canonical KPIs from single source of truth
            **canonical_stats,
            # Topology-specific stats
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "source_systems": len(sorted_sors)
        },
        "generated_at": datetime.utcnow().isoformat()
    }


@app.get("/api/topology/plane/{fabric_plane}", tags=["Topology"])
async def get_plane_topology(fabric_plane: str):
    """
    Get topology for a specific fabric plane.

    Returns all pipes in the specified plane and their source systems.
    Valid planes: IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE
    """
    valid_planes = ["IPAAS", "API_GATEWAY", "EVENT_BUS", "DATA_WAREHOUSE"]
    if fabric_plane.upper() not in valid_planes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fabric plane. Must be one of: {', '.join(valid_planes)}"
        )

    result = get_topology_for_fabric_plane(fabric_plane.upper())

    from datetime import datetime
    return {
        **result,
        "generated_at": datetime.utcnow().isoformat()
    }


@app.get("/api/topology/source/{source_system}", tags=["Topology"])
async def get_source_topology(source_system: str):
    """
    Get topology for a specific source system.

    Returns all pipes and candidates connected to the specified source system.
    """
    topology = get_topology_data()

    # Filter to nodes connected to this source
    source_node_id = f"source:{source_system}"

    # Check if source exists
    source_exists = any(n["id"] == source_node_id for n in topology["nodes"])
    if not source_exists:
        raise HTTPException(status_code=404, detail=f"Source system '{source_system}' not found")

    # Get connected node IDs
    connected_ids = {source_node_id}
    for edge in topology["edges"]:
        if edge["target"] == source_node_id:
            connected_ids.add(edge["source"])
        elif edge["source"] == source_node_id:
            connected_ids.add(edge["target"])

    # Also include fabric planes for connected pipes
    for edge in topology["edges"]:
        if edge["source"] in connected_ids and edge["type"] == "pipe_in_plane":
            connected_ids.add(edge["target"])

    nodes = [n for n in topology["nodes"] if n["id"] in connected_ids]
    edges = [e for e in topology["edges"]
             if e["source"] in connected_ids and e["target"] in connected_ids]

    # Mark the source as central
    for node in nodes:
        if node["id"] == source_node_id:
            node["metadata"]["central"] = True

    from datetime import datetime
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "pipes": len([n for n in nodes if n["type"] == "pipe"]),
            "candidates": len([n for n in nodes if n["type"] == "candidate"])
        },
        "generated_at": datetime.utcnow().isoformat()
    }


@app.delete("/api/data", tags=["Admin"])
async def clear_data():
    """Clear all data (use with caution)"""
    result = clear_all_data()
    return {"message": "All data cleared", **result}


@app.get("/api/debug/handoff-state", tags=["Debug"])
async def debug_handoff_state():
    """
    Diagnostic endpoint to inspect the current state of AOD handoff data.

    Shows:
    - Fabric planes stored (from AOD handoff)
    - Candidate counts and sample data
    - Category distribution
    - Fabric plane assignment status
    """
    from .db import get_connection

    conn = get_connection()
    cursor = conn.cursor()

    # Get fabric planes
    cursor.execute("SELECT * FROM fabric_planes ORDER BY created_at DESC LIMIT 10")
    fabric_planes = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) FROM fabric_planes")
    fabric_plane_count = cursor.fetchone()[0]

    # Get candidate stats
    cursor.execute("SELECT COUNT(*) FROM connection_candidates")
    total_candidates = cursor.fetchone()[0]

    # Category distribution
    cursor.execute("""
        SELECT category, COUNT(*) as count
        FROM connection_candidates
        GROUP BY category
        ORDER BY count DESC
        LIMIT 20
    """)
    category_dist = {row[0]: row[1] for row in cursor.fetchall()}

    # Fabric plane assignment stats
    cursor.execute("""
        SELECT
            CASE WHEN fabric_plane_id IS NULL OR fabric_plane_id = '' THEN 'unassigned' ELSE 'assigned' END as status,
            COUNT(*) as count
        FROM connection_candidates
        GROUP BY status
    """)
    assignment_stats = {row[0]: row[1] for row in cursor.fetchall()}

    # Sample candidates with fabric_plane_id
    cursor.execute("""
        SELECT candidate_id, vendor_name, category, fabric_plane_id, connected_via_plane
        FROM connection_candidates
        WHERE fabric_plane_id IS NOT NULL AND fabric_plane_id != ''
        LIMIT 5
    """)
    assigned_samples = [dict(row) for row in cursor.fetchall()]

    # Sample candidates without fabric_plane_id
    cursor.execute("""
        SELECT candidate_id, vendor_name, category, fabric_plane_id, connected_via_plane
        FROM connection_candidates
        WHERE fabric_plane_id IS NULL OR fabric_plane_id = ''
        LIMIT 5
    """)
    unassigned_samples = [dict(row) for row in cursor.fetchall()]

    # Get handoff logs
    cursor.execute("""
        SELECT aod_run_id, snapshot_name, candidates_received, candidates_accepted, handoff_timestamp
        FROM aod_handoff_log
        ORDER BY handoff_timestamp DESC
        LIMIT 5
    """)
    handoff_logs = [dict(row) for row in cursor.fetchall()]

    # Get canonical stats
    canonical_stats = get_canonical_stats()

    conn.close()

    return {
        "summary": {
            "fabric_planes_stored": fabric_plane_count,
            "total_candidates": total_candidates,
            "candidates_with_plane": assignment_stats.get("assigned", 0),
            "candidates_without_plane": assignment_stats.get("unassigned", 0)
        },
        "canonical_stats": canonical_stats,
        "category_distribution": category_dist,
        "fabric_planes": fabric_planes,
        "assigned_candidate_samples": assigned_samples,
        "unassigned_candidate_samples": unassigned_samples,
        "recent_handoff_logs": handoff_logs,
        "diagnosis": {
            "fabric_planes_missing": fabric_plane_count == 0,
            "all_candidates_unassigned": assignment_stats.get("assigned", 0) == 0 and total_candidates > 0,
            "no_sor_categories": not any(cat.lower() in ['crm', 'erp', 'hcm', 'idp', 'itsm'] for cat in category_dist.keys())
        }
    }
