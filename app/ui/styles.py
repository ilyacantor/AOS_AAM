"""
AAM UI Constants — CSS styles, navigation HTML, and UI helper functions.

Extracted from the monolithic main.py for separation of concerns.
"""
from ..db import get_latest_aod_run

NAV_STYLE = """
<script>
(function(){
  if (window !== window.parent) {
    document.documentElement.style.scrollBehavior = 'auto';
    var scrollTop = function(){
      window.scrollTo(0,0);
      document.body.scrollTop = 0;
      document.documentElement.scrollTop = 0;
    };
    window.addEventListener('DOMContentLoaded', scrollTop);
    window.addEventListener('load', scrollTop);
    setTimeout(scrollTop, 100);
  }
})();
</script>
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { overflow-x: hidden; }
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
    .nav-separator {
        width: 1px;
        height: 24px;
        background: rgba(148, 163, 184, 0.25);
        flex-shrink: 0;
    }
    .nav-links { display: flex; gap: 8px; flex-wrap: nowrap; overflow-x: auto; }
    .nav-link {
        white-space: nowrap;
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
<link rel="icon" type="image/png" href="/static/favicon.png" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600;700&display=swap" rel="stylesheet">
"""

NAV_HTML = """
<nav class="nav">
    <a href="/ui/topology" class="nav-brand">AAM</a>
    <div class="nav-separator"></div>
    <div class="nav-links">
        <a href="/ui/pipes" class="nav-link{pipes_active}">Pipes</a>
        <a href="/ui/candidates" class="nav-link{candidates_active}">Candidates</a>
        <a href="/ui/drift" class="nav-link{drift_active}">Drift & Health</a>
        <a href="/ui/guide" class="nav-link{guide_active}">Guide</a>
    </div>
</nav>
"""

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
        --emerald-400: #34d399;
        --amber-400: #fbbf24;
        --pink-400: #f472b6;
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
    .btn-warning { color: var(--orange-400); border-color: rgba(251, 146, 60, 0.3); background: rgba(251, 146, 60, 0.1); }
    .btn-warning:hover { background: rgba(251, 146, 60, 0.2); border-color: rgba(251, 146, 60, 0.5); }
    .btn-danger { color: var(--red-400); border-color: rgba(248, 113, 113, 0.3); background: rgba(248, 113, 113, 0.1); }
    .btn-danger:hover { background: rgba(248, 113, 113, 0.2); border-color: rgba(248, 113, 113, 0.5); }
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
    .badge-new { background: rgba(59, 130, 246, 0.2); color: var(--blue-400); }
    .badge-triaged { background: rgba(192, 132, 252, 0.2); color: var(--purple-400); }
    .badge-connected { background: rgba(34, 197, 94, 0.2); color: var(--green-500); }
    .badge-deferred { background: rgba(148, 163, 184, 0.2); color: var(--slate-400); }
    .badge-open { background: rgba(248, 113, 113, 0.2); color: var(--red-400); }
    .badge-acknowledged { background: rgba(251, 146, 60, 0.2); color: var(--orange-400); }
    .badge-suppressed { background: rgba(148, 163, 184, 0.2); color: var(--slate-400); }
    .badge-resolved { background: rgba(34, 197, 94, 0.2); color: var(--green-500); }
    .badge-critical { background: rgba(239, 68, 68, 0.2); color: var(--red-500); }
    .badge-high { background: rgba(248, 113, 113, 0.2); color: var(--red-400); }
    .badge-medium { background: rgba(251, 146, 60, 0.2); color: var(--orange-400); }
    .badge-low { background: rgba(250, 204, 21, 0.2); color: var(--yellow-400); }
    .badge-api { background: rgba(34, 211, 238, 0.2); color: var(--cyan-400); }
    .badge-event { background: rgba(192, 132, 252, 0.2); color: var(--purple-400); }
    .badge-table { background: rgba(59, 130, 246, 0.2); color: var(--blue-400); }
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
    .stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
    .stat-card { background: rgba(30, 41, 59, 0.6); border: 1px solid var(--slate-700); border-radius: 8px; padding: 16px 20px; min-width: 140px; }
    .stat-value { font-size: 1.5rem; font-weight: 700; color: var(--cyan-400); }
    .stat-label { font-size: 0.75rem; color: var(--slate-400); text-transform: uppercase; letter-spacing: 0.05em; }
    @media (max-width: 768px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
</style>
"""


def ui_nav(active: str = "") -> str:
    """Generate navigation for operator UI screens."""
    def active_class(page: str) -> str:
        return " active" if page == active else ""
    return f"""
<nav class="nav">
    <a href="/ui/topology" class="nav-brand" data-testid="nav-brand">AAM</a>
    <div class="nav-separator"></div>
    <div class="nav-links">
        <a href="/ui/topology" class="nav-link{active_class('topology')}" data-testid="nav-topology">Topology</a>
        <a href="/ui/pipes" class="nav-link{active_class('pipes')}" data-testid="nav-pipes">Pipes</a>
        <a href="/ui/candidates" class="nav-link{active_class('candidates')}" data-testid="nav-candidates">Candidates</a>
        <a href="/ui/drift" class="nav-link{active_class('drift')}" data-testid="nav-drift">Drift & Health</a>
        <a href="/ui/reconcile" class="nav-link{active_class('reconcile')}" data-testid="nav-reconcile">Reconcile</a>
        <a href="/ui/controls" class="nav-link{active_class('controls')}" data-testid="nav-controls">Controls</a>
        <a href="/ui/guide" class="nav-link{active_class('guide')}" data-testid="nav-guide">Guide</a>
    </div>
</nav>
"""


def aod_run_banner(extra_buttons: str = "") -> str:
    """Generate AOD run information banner with Fetch AOD Data button."""
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
    <div style="display: flex; gap: 8px; align-items: center;">
        {fetch_btn}
        {extra_buttons}
    </div>
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
        {extra_buttons}
    </div>
</div>
{fetch_script}
"""
