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
    get_drift_event,
    clear_all_data,
    get_pipe_stats
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
        <a href="/ui/pipes" class="nav-link{pipes_active}">Pipes</a>
        <a href="/ui/candidates" class="nav-link{candidates_active}">Candidates</a>
        <a href="/ui/drift" class="nav-link{drift_active}">Drift & Health</a>
        <a href="/ui/guide" class="nav-link{guide_active}">Guide</a>
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
    {NAV_HTML.format(pipes_active="", candidates_active="", drift_active="", guide_active="", docs_active="")}
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
    <a href="/" class="nav-brand">AAM</a>
    <div class="nav-links">
        <a href="/ui/pipes" class="nav-link{active_class('pipes')}" data-testid="nav-pipes">Pipes</a>
        <a href="/ui/candidates" class="nav-link{active_class('candidates')}" data-testid="nav-candidates">Candidates</a>
        <a href="/ui/drift" class="nav-link{active_class('drift')}" data-testid="nav-drift">Drift & Health</a>
        <a href="/ui/guide" class="nav-link{active_class('guide')}" data-testid="nav-guide">Guide</a>
    </div>
</nav>
"""


@app.get("/ui/pipes", response_class=HTMLResponse, include_in_schema=False)
async def ui_pipes_list(
    source_system: Optional[str] = Query(None),
    modality: Optional[str] = Query(None),
    fabric_plane: Optional[str] = Query(None)
):
    """Pipes Inventory Screen"""
    pipes = list_pipes(source_system=source_system, fabric_plane=fabric_plane)
    if modality:
        pipes = [p for p in pipes if p.get("modality") == modality]
    
    all_pipes = list_pipes()
    source_systems = sorted(set(p.get("source_system", "") for p in all_pipes if p.get("source_system")))
    modalities = sorted(set(p.get("modality", "") for p in all_pipes if p.get("modality")))
    fabric_planes = ["IPAAS", "API_GATEWAY", "EVENT_BUS", "DATA_WAREHOUSE"]
    
    all_drift = list_all_drift_events(limit=1000)
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
    
    source_options = '<option value="">All Sources</option>' + ''.join(
        f'<option value="{s}"{" selected" if s == source_system else ""}>{s}</option>' for s in source_systems
    )
    modality_options = '<option value="">All Modalities</option>' + ''.join(
        f'<option value="{m}"{" selected" if m == modality else ""}>{m}</option>' for m in modalities
    )
    fabric_options = '<option value="">All Fabric Planes</option>' + ''.join(
        f'<option value="{f}"{" selected" if f == fabric_plane else ""}>{f}</option>' for f in fabric_planes
    )
    
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
        <h1>Pipes Inventory</h1>
        
        <div class="preset-section" data-testid="preset-section">
            <h3>Load Enterprise Preset</h3>
            <div class="preset-grid" id="preset-grid">Loading presets...</div>
        </div>
        
        <div class="stats-bar" id="stats-bar" data-testid="stats-bar">
            <div class="stat-item"><div class="stat-value" id="stat-total">{len(pipes)}</div><div class="stat-label">Total Pipes</div></div>
        </div>
        
        <div class="controls">
            <button class="btn" id="btn-run-collector" data-testid="btn-run-collector">Run Mock Collector</button>
            <button class="btn" id="btn-export-dcl" data-testid="btn-export-dcl">Export to DCL</button>
            <select id="filter-fabric" data-testid="filter-fabric" onchange="applyFilters()">{fabric_options}</select>
            <select id="filter-source" data-testid="filter-source" onchange="applyFilters()">{source_options}</select>
            <select id="filter-modality" data-testid="filter-modality" onchange="applyFilters()">{modality_options}</select>
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
        
        function applyFilters() {{
            const fabric = document.getElementById('filter-fabric').value;
            const source = document.getElementById('filter-source').value;
            const modality = document.getElementById('filter-modality').value;
            const params = new URLSearchParams();
            if (fabric) params.set('fabric_plane', fabric);
            if (source) params.set('source_system', source);
            if (modality) params.set('modality', modality);
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
async def ui_candidates_list(status: Optional[str] = Query(None)):
    """Candidates Screen"""
    candidates = list_candidates(status=status)
    
    all_candidates = list_candidates()
    statuses = sorted(set(c.get("status", "") for c in all_candidates if c.get("status")))
    
    status_options = '<option value="">All Statuses</option>' + ''.join(
        f'<option value="{s}"{" selected" if s == status else ""}>{s.title()}</option>' for s in statuses
    )
    
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
        <h1>Connection Candidates</h1>
        <div class="controls">
            <select id="filter-status" data-testid="filter-status" onchange="applyFilter()">{status_options}</select>
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
            window.location.href = '/ui/candidates' + (params.toString() ? '?' + params.toString() : '');
        }}
        
        async function matchCandidate(candidateId) {{
            const pipeId = prompt('Enter Pipe ID to match (leave empty for auto-match):');
            try {{
                const body = pipeId ? {{ pipe_id: pipeId }} : {{}};
                const res = await fetch('/api/candidates/' + candidateId + '/match', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(body)
                }});
                const data = await res.json();
                if (res.ok) {{
                    showToast('Matched to pipe: ' + data.matched_pipe_id, 'success');
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Match failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
        }}
        
        async function deferCandidate(candidateId) {{
            const reason = prompt('Reason for deferring:');
            if (!reason) return;
            try {{
                const res = await fetch('/api/candidates/' + candidateId + '/defer', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ reason: reason }})
                }});
                const data = await res.json();
                if (res.ok) {{
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
            <a href="#pipes-screen">Pipes Inventory Screen</a>
            <a href="#pipe-detail">Pipe Detail Screen</a>
            <a href="#candidates-screen">Candidates Screen</a>
            <a href="#drift-screen">Drift & Health Screen</a>
            <a href="#workflows">Common Workflows</a>
            <a href="#glossary">Glossary</a>
        </div>
        
        <div class="guide-section" id="what-is-aam">
            <h2>What is AAM?</h2>
            <p><strong>AAM (Adaptive API Mesh)</strong> is the integration layer that inventories your enterprise's reusable data pipes and makes their behavior and meaning explicit. Think of it as a catalog of all the ways data can flow between your systems.</p>
            
            <h3>The Big Picture</h3>
            <p>AAM sits between two other systems:</p>
            <div class="guide-diagram">
                AOD (discovers what exists) → <span class="highlight">AAM (catalogs the pipes)</span> → DCL (unifies meaning)
            </div>
            <ul>
                <li><strong>AOD</strong> discovers what systems and connections exist in your enterprise and sends "connection candidates" to AAM</li>
                <li><strong>AAM</strong> (this system) catalogs those connections as "declared pipes" with metadata about how they behave</li>
                <li><strong>DCL</strong> consumes those declared pipes to build a unified understanding of your data</li>
            </ul>
            
            <div class="guide-card">
                <div class="guide-card-title">What AAM Does NOT Do</div>
                <p>AAM does not move data, transform data, or act as an integration platform. It only <strong>observes</strong> and <strong>documents</strong> what already exists.</p>
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
                <tr><td>Run Collector</td><td>Triggers a collector to observe systems and update pipe information</td></tr>
                <tr><td>Run Inference</td><td>Processes raw observations into declared pipes</td></tr>
                <tr><td>Export to DCL</td><td>Generates a snapshot of all pipes in DCL format</td></tr>
            </table>
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
                <div class="guide-card-title">Discovering New Pipes</div>
                <ol>
                    <li>Go to <strong>Pipes</strong> screen</li>
                    <li>Click <strong>Run Collector</strong> to observe systems</li>
                    <li>Click <strong>Run Inference</strong> to process observations</li>
                    <li>Review newly created pipes</li>
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
                <tr><td>Modality</td><td>The approach for connecting (control plane, declared interface, etc.)</td></tr>
                <tr><td>Observation</td><td>Raw data from a collector before being processed into a pipe</td></tr>
                <tr><td>Pipe</td><td>A reusable data connection between systems</td></tr>
                <tr><td>Provenance</td><td>Origin and lineage information about a pipe</td></tr>
                <tr><td>Schema Hash</td><td>A fingerprint of the data structure for detecting changes</td></tr>
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
    
    for pipe_data in data.get("pipes", []):
        provenance = {
            "discovered_by": f"preset:{preset_id}",
            "discovered_at": datetime.utcnow().isoformat(),
            "lineage_hints": [f"preset:{preset_id}"]
        }
        pipe_data["provenance"] = provenance
        create_pipe(pipe_data)
        pipes_created += 1
    
    for candidate_data in data.get("candidates", []):
        create_candidate(candidate_data)
        candidates_created += 1
    
    return {
        "preset_id": preset_id,
        "name": data.get("name"),
        "pipes_created": pipes_created,
        "candidates_created": candidates_created,
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


@app.delete("/api/data", tags=["Admin"])
async def clear_data():
    """Clear all data (use with caution)"""
    result = clear_all_data()
    return {"message": "All data cleared", **result}
