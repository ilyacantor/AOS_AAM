"""
AAM Controls Dashboard — operator UI for triple-modality controls.

Single-page dashboard at /ui/controls (also aliased to /controls for iframe embedding).
Seven panels: Mode Indicator, Triple Write Ledger, Triple Health,
Data Drift, Pipe Inventory, Legacy Runner, Connection Health.

All panels render real data from the controls API endpoints.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..ui.styles import NAV_STYLE, UI_STYLE, ui_nav

router = APIRouter(include_in_schema=False)

_CONTROLS_STYLE = """
<style>
    .mode-badge {
        display: inline-block;
        padding: 6px 16px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 1rem;
        letter-spacing: 0.05em;
    }
    .mode-SYNTHETIC {
        background: rgba(59, 130, 246, 0.2);
        color: #60a5fa;
        border: 1px solid rgba(59, 130, 246, 0.4);
    }
    .mode-PRODUCTION_SE {
        background: rgba(34, 197, 94, 0.2);
        color: #4ade80;
        border: 1px solid rgba(34, 197, 94, 0.4);
    }
    .mode-PRODUCTION_ME {
        background: rgba(168, 85, 247, 0.2);
        color: #c084fc;
        border: 1px solid rgba(168, 85, 247, 0.4);
    }
    .ledger-status-committed { color: #4ade80; }
    .ledger-status-failed { color: #f87171; }
    .ledger-status-pending { color: #facc15; }
    .coverage-present { color: #4ade80; }
    .coverage-missing { color: #f87171; }
    .freshness-green { color: #4ade80; }
    .freshness-yellow { color: #facc15; }
    .freshness-red { color: #f87171; }
    .freshness-unknown { color: #94a3b8; }
    .severity-HIGH { color: #f87171; font-weight: 600; }
    .severity-MEDIUM { color: #fb923c; }
    .severity-LOW { color: #facc15; }
    .expandable-row { cursor: pointer; }
    .expandable-row:hover { background: rgba(34, 211, 238, 0.08) !important; }
    .expand-detail { display: none; background: rgba(15, 23, 42, 0.6); padding: 12px 16px; }
    .expand-detail.open { display: table-row; }
    .toggle-btn {
        background: rgba(148, 163, 184, 0.15);
        color: #94a3b8;
        border: 1px solid rgba(148, 163, 184, 0.3);
        padding: 4px 12px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 0.8rem;
    }
    .toggle-btn:hover { background: rgba(148, 163, 184, 0.25); }
    .delta-positive { color: #4ade80; }
    .delta-negative { color: #f87171; }
    .delta-zero { color: #94a3b8; }
    .no-drift { color: #4ade80; font-weight: 500; }
    .panel-loading { text-align: center; color: #94a3b8; padding: 20px; }
    .pipe-backing-yes { color: #4ade80; }
    .pipe-backing-no { color: #f87171; }
    #legacy-panel { display: none; }
    #legacy-panel.visible { display: block; }
    .placeholder-panel {
        text-align: center;
        padding: 40px;
        color: #64748b;
        font-style: italic;
    }
</style>
"""


def _build_dashboard_html() -> str:
    """Build the full controls dashboard HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <title>AAM Controls Dashboard</title>
    {NAV_STYLE}
    {UI_STYLE}
    {_CONTROLS_STYLE}
</head>
<body>
    {ui_nav('controls')}
    <div class="container">
        <h1>AAM Controls Dashboard</h1>

        <!-- PANEL A: Mode Indicator -->
        <div class="panel" id="mode-panel" data-testid="panel-mode">
            <div class="panel-title">Operating Mode</div>
            <div id="mode-content" class="panel-loading">Loading...</div>
        </div>

        <!-- PANEL B: Triple Write Ledger -->
        <div class="panel" id="ledger-panel" data-testid="panel-ledger">
            <div class="panel-title">Triple Write Ledger</div>
            <div id="ledger-summary" style="margin-bottom: 16px;"></div>
            <div id="ledger-content" class="panel-loading">Loading...</div>
        </div>

        <!-- PANEL C: Triple Health -->
        <div class="panel" id="health-panel" data-testid="panel-health">
            <div class="panel-title">Triple Health</div>
            <div id="health-content" class="panel-loading">Loading...</div>
        </div>

        <!-- PANEL D: Data Drift -->
        <div class="panel" id="drift-panel" data-testid="panel-drift">
            <div class="panel-title">Data Drift</div>
            <div id="drift-content" class="panel-loading">Loading...</div>
        </div>

        <!-- PANEL E: Pipe Inventory -->
        <div class="panel" id="pipe-panel" data-testid="panel-pipes">
            <div class="panel-title">Pipe Inventory</div>
            <div id="pipe-content" class="panel-loading">Loading...</div>
        </div>

        <!-- PANEL F: Legacy Runner (hidden by default) -->
        <div style="margin-bottom: 20px;">
            <button class="toggle-btn" onclick="toggleLegacy()" data-testid="toggle-legacy">Show Legacy Runner</button>
        </div>
        <div class="panel" id="legacy-panel" data-testid="panel-legacy">
            <div class="panel-title">Legacy Runner Status</div>
            <div id="legacy-content" class="panel-loading">Loading...</div>
        </div>

        <!-- PANEL G: Connection Health (placeholder) -->
        <div class="panel" id="connection-panel" data-testid="panel-connection">
            <div class="panel-title">Connection Health</div>
            <div class="placeholder-panel" data-testid="connection-placeholder">
                Connection health monitoring activates when live fabric plane connections are established.
            </div>
        </div>
    </div>

    <script>
    // ---- Utility ----
    function esc(s) {{
        if (s === null || s === undefined) return '';
        var d = document.createElement('div');
        d.textContent = String(s);
        return d.innerHTML;
    }}

    function toggleLegacy() {{
        var p = document.getElementById('legacy-panel');
        var btn = document.querySelector('[data-testid="toggle-legacy"]');
        if (p.classList.contains('visible')) {{
            p.classList.remove('visible');
            btn.textContent = 'Show Legacy Runner';
        }} else {{
            p.classList.add('visible');
            btn.textContent = 'Hide Legacy Runner';
            loadLegacy();
        }}
    }}

    // ---- Panel A: Mode ----
    async function loadMode() {{
        try {{
            var res = await fetch('/api/aam/mode');
            var data = await res.json();
            var mode = data.mode;
            var html = '<div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap;">';
            html += '<span class="mode-badge mode-' + esc(mode) + '" data-testid="mode-badge">' + esc(mode) + '</span>';
            if (mode === 'SYNTHETIC' && data.superseded_controls && data.superseded_controls.length > 0) {{
                html += '<div style="color: #94a3b8; font-size: 0.85rem;">';
                html += '<strong>Superseded controls:</strong><br>';
                data.superseded_controls.forEach(function(c) {{
                    html += '<span style="margin-left: 8px;">&bull; ' + esc(c.control) + ' &mdash; <em>' + esc(c.reason) + '</em></span><br>';
                }});
                html += '</div>';
            }}
            html += '</div>';
            document.getElementById('mode-content').innerHTML = html;
        }} catch(e) {{
            document.getElementById('mode-content').innerHTML = '<span style="color:#f87171;">Failed to load mode: ' + esc(e.message) + '</span>';
        }}
    }}

    // ---- Panel B: Ledger ----
    async function loadLedger() {{
        try {{
            var [ledgerRes, summaryRes] = await Promise.all([
                fetch('/api/aam/triple-ledger?limit=20'),
                fetch('/api/aam/triple-ledger/summary')
            ]);
            var ledger = await ledgerRes.json();
            var summary = await summaryRes.json();

            // Summary section
            var shtml = '<div class="stats" data-testid="ledger-summary">';
            shtml += '<div class="stat-card"><div class="stat-value">' + (summary.total_triples || 0) + '</div><div class="stat-label">Total Triples</div></div>';
            var byWp = summary.by_write_path || {{}};
            Object.keys(byWp).forEach(function(wp) {{
                shtml += '<div class="stat-card"><div class="stat-value">' + (byWp[wp].triples || 0) + '</div><div class="stat-label">' + esc(wp) + '</div></div>';
            }});
            var byPfx = summary.by_concept_prefix || {{}};
            Object.keys(byPfx).forEach(function(pfx) {{
                shtml += '<div class="stat-card"><div class="stat-value">' + byPfx[pfx] + '</div><div class="stat-label">' + esc(pfx) + '</div></div>';
            }});
            if (summary.latest_timestamp) {{
                shtml += '<div class="stat-card"><div class="stat-value" style="font-size: 0.9rem;">' + esc(summary.latest_timestamp.substring(0, 19)) + '</div><div class="stat-label">Latest Write</div></div>';
            }}
            shtml += '<div class="stat-card"><div class="stat-value">' + ((summary.failure_rate_24h || 0) * 100).toFixed(1) + '%</div><div class="stat-label">Failure Rate (24h)</div></div>';
            shtml += '</div>';
            document.getElementById('ledger-summary').innerHTML = shtml;

            // Table
            var entries = ledger.entries || [];
            if (entries.length === 0) {{
                document.getElementById('ledger-content').innerHTML = '<div class="empty-state">No ledger entries yet. Run pipe inference to populate.</div>';
                return;
            }}
            var html = '<table data-testid="ledger-table"><thead><tr>';
            html += '<th>Run ID</th><th>Trigger</th><th>Write Path</th><th>Prefixes</th><th>Count</th><th>Status</th><th>Duration</th><th>Created</th>';
            html += '</tr></thead><tbody>';
            entries.forEach(function(e, i) {{
                var statusClass = 'ledger-status-' + (e.status || 'pending');
                var prefixes = Array.isArray(e.concept_prefixes) ? e.concept_prefixes.join(', ') : (e.concept_prefixes || '');
                var rowClass = e.status === 'failed' ? 'expandable-row' : '';
                html += '<tr class="' + rowClass + '" ' + (e.status === 'failed' ? 'onclick="toggleExpand(' + i + ')"' : '') + ' data-testid="ledger-row">';
                html += '<td style="font-family: monospace; font-size: 0.8rem;">' + esc((e.run_id || '').substring(0, 8)) + '</td>';
                html += '<td>' + esc(e.trigger) + '</td>';
                html += '<td>' + esc(e.write_path) + '</td>';
                html += '<td style="font-size: 0.8rem;">' + esc(prefixes) + '</td>';
                html += '<td>' + (e.triple_count !== null ? e.triple_count : '-') + '</td>';
                html += '<td><span class="' + statusClass + '">' + esc(e.status) + '</span></td>';
                html += '<td>' + (e.duration_ms !== null ? e.duration_ms + 'ms' : '-') + '</td>';
                html += '<td style="font-size: 0.8rem;">' + esc((e.created_at || '').substring(0, 19)) + '</td>';
                html += '</tr>';
                if (e.status === 'failed' && e.error_detail) {{
                    html += '<tr class="expand-detail" id="expand-' + i + '" data-testid="ledger-error-detail"><td colspan="8">';
                    html += '<strong style="color: #f87171;">Error:</strong> <span style="font-family: monospace; font-size: 0.8rem;">' + esc(e.error_detail) + '</span>';
                    html += '</td></tr>';
                }}
            }});
            html += '</tbody></table>';
            document.getElementById('ledger-content').innerHTML = html;
        }} catch(e) {{
            document.getElementById('ledger-content').innerHTML = '<span style="color:#f87171;">Failed to load ledger: ' + esc(e.message) + '</span>';
        }}
    }}

    function toggleExpand(i) {{
        var el = document.getElementById('expand-' + i);
        if (el) el.classList.toggle('open');
    }}

    // ---- Panel C: Triple Health ----
    async function loadHealth() {{
        try {{
            var res = await fetch('/api/aam/triple-health');
            var data = await res.json();
            var html = '<div class="grid-2">';

            // Count + Entity
            html += '<div>';
            html += '<div class="field"><div class="field-label">Entity</div><div class="field-value">' + esc(data.entity_id || 'Not resolved') + '</div></div>';
            html += '<div class="field"><div class="field-label">AAM Triple Count</div><div class="field-value" style="font-size: 1.3rem; font-weight: 700; color: var(--cyan-400);" data-testid="triple-count">' + (data.total_count || 0) + '</div></div>';
            html += '</div>';

            // Freshness
            html += '<div>';
            var freshStatus = (data.freshness || {{}}).status || 'unknown';
            var freshClass = 'freshness-' + freshStatus;
            html += '<div class="field"><div class="field-label">Freshness</div><div class="field-value ' + freshClass + '" data-testid="freshness-status">' + freshStatus.toUpperCase() + '</div></div>';
            if (data.freshness && data.freshness.latest_write) {{
                html += '<div class="field"><div class="field-label">Last Write</div><div class="field-value" style="font-size: 0.85rem;">' + esc(data.freshness.latest_write) + '</div></div>';
            }}
            html += '</div>';
            html += '</div>';

            // Coverage
            html += '<div style="margin-top: 16px;"><div class="field-label">Concept Coverage</div><div style="display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px;" data-testid="coverage-list">';
            var coverage = data.coverage || {{}};
            Object.keys(coverage).forEach(function(prefix) {{
                var status = coverage[prefix];
                var cls = 'coverage-' + status;
                var icon = status === 'present' ? '&#10003;' : '&#10007;';
                html += '<div style="display: flex; align-items: center; gap: 4px;" data-testid="coverage-item"><span class="' + cls + '">' + icon + '</span> <span style="font-size: 0.85rem;">' + esc(prefix) + '</span></div>';
            }});
            html += '</div></div>';

            // Run comparison
            if (data.run_comparison) {{
                var rc = data.run_comparison;
                var deltaClass = rc.delta > 0 ? 'delta-positive' : (rc.delta < 0 ? 'delta-negative' : 'delta-zero');
                var deltaText = rc.delta > 0 ? '+' + rc.delta : String(rc.delta);
                html += '<div style="margin-top: 16px;"><div class="field-label">Run Comparison</div>';
                html += '<div style="font-size: 0.85rem; margin-top: 4px;">Latest: ' + rc.latest_count + ' triples <span class="' + deltaClass + '" data-testid="run-delta">(' + deltaText + ')</span></div>';
                html += '</div>';
            }}

            document.getElementById('health-content').innerHTML = html;
        }} catch(e) {{
            document.getElementById('health-content').innerHTML = '<span style="color:#f87171;">Failed to load health: ' + esc(e.message) + '</span>';
        }}
    }}

    // ---- Panel D: Drift ----
    async function loadDrift() {{
        try {{
            var res = await fetch('/api/aam/drift-status');
            var data = await res.json();
            var html = '';

            // Signal check timestamps
            html += '<div class="field-label" style="margin-bottom: 8px;">Signal Check Timestamps</div>';
            html += '<div style="display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px;" data-testid="drift-timestamps">';
            var signals = data.signals || [];
            var lastChecks = data.last_check_times || {{}};
            signals.forEach(function(sig) {{
                var ts = lastChecks[sig];
                html += '<div style="font-size: 0.85rem;"><strong>' + esc(sig) + ':</strong> ';
                html += ts ? '<span style="color: #94a3b8;">' + esc(ts.substring(0, 19)) + '</span>' : '<span style="color: #64748b;">Not checked</span>';
                html += '</div>';
            }});
            html += '</div>';

            // Active drift events
            var events = data.active_events || [];
            if (events.length === 0) {{
                html += '<div class="no-drift" data-testid="no-drift">No drift detected</div>';
                if (data.has_checked) {{
                    html += '<div style="color: #94a3b8; font-size: 0.8rem; margin-top: 4px;">All signals checked &mdash; clean run confirmed.</div>';
                }}
            }} else {{
                html += '<div class="field-label" style="margin-bottom: 8px;">Active Drift Events (' + events.length + ')</div>';
                html += '<table data-testid="drift-events-table"><thead><tr>';
                html += '<th>Type</th><th>Severity</th><th>Concept</th><th>Run ID</th><th>Detected</th>';
                html += '</tr></thead><tbody>';
                events.forEach(function(ev) {{
                    var severity = (ev.value || '').toString();
                    if (ev.property === 'drift_type') return; // Skip type rows, show severity
                    html += '<tr data-testid="drift-event-row">';
                    html += '<td>' + esc(ev.concept) + '</td>';
                    html += '<td>' + esc(ev.property) + '</td>';
                    html += '<td>' + esc(ev.value) + '</td>';
                    html += '<td style="font-family: monospace; font-size: 0.8rem;">' + esc((ev.run_id || '').substring(0, 8)) + '</td>';
                    html += '<td style="font-size: 0.8rem;">' + esc((ev.created_at || '').toString().substring(0, 19)) + '</td>';
                    html += '</tr>';
                }});
                html += '</tbody></table>';
            }}

            // Trigger check button
            html += '<div style="margin-top: 16px;"><button class="btn btn-sm" onclick="triggerDriftCheck()" data-testid="drift-check-btn">Run Drift Check</button> <span id="drift-check-status"></span></div>';

            document.getElementById('drift-content').innerHTML = html;
        }} catch(e) {{
            document.getElementById('drift-content').innerHTML = '<span style="color:#f87171;">Failed to load drift: ' + esc(e.message) + '</span>';
        }}
    }}

    async function triggerDriftCheck() {{
        var status = document.getElementById('drift-check-status');
        status.textContent = 'Checking...';
        status.style.color = '#94a3b8';
        try {{
            var res = await fetch('/api/aam/drift-check', {{ method: 'POST' }});
            var data = await res.json();
            if (res.ok) {{
                status.textContent = data.event_count + ' events found';
                status.style.color = data.event_count > 0 ? '#fb923c' : '#4ade80';
                loadDrift();
            }} else {{
                status.textContent = data.detail || 'Check failed';
                status.style.color = '#f87171';
            }}
        }} catch(e) {{
            status.textContent = 'Error: ' + e.message;
            status.style.color = '#f87171';
        }}
    }}

    // ---- Panel E: Pipe Inventory ----
    async function loadPipes() {{
        try {{
            var res = await fetch('/api/pipes?limit=100');
            var data = await res.json();
            var pipes = data.pipes || [];
            if (pipes.length === 0) {{
                document.getElementById('pipe-content').innerHTML = '<div class="empty-state">No declared pipes. Run inference first.</div>';
                return;
            }}

            // Get triple health for backing info
            var healthRes = await fetch('/api/aam/triple-health');
            var health = await healthRes.json();

            var html = '<table data-testid="pipe-table"><thead><tr>';
            html += '<th>Source System</th><th>Fabric Plane</th><th>Modality</th><th>Transport</th><th>Status</th><th>Triple Backing</th>';
            html += '</tr></thead><tbody>';
            pipes.forEach(function(p) {{
                var hasBacking = (health.total_count || 0) > 0;
                var backingClass = hasBacking ? 'pipe-backing-yes' : 'pipe-backing-no';
                var backingText = hasBacking ? 'Yes' : 'No';
                html += '<tr data-testid="pipe-row">';
                html += '<td>' + esc(p.source_system) + '</td>';
                html += '<td><span class="badge">' + esc(p.fabric_plane) + '</span></td>';
                html += '<td>' + esc(p.modality) + '</td>';
                html += '<td>' + esc(p.transport_kind) + '</td>';
                html += '<td>' + esc(p.version || '1') + '</td>';
                html += '<td><span class="' + backingClass + '">' + backingText + '</span></td>';
                html += '</tr>';
            }});
            html += '</tbody></table>';
            document.getElementById('pipe-content').innerHTML = html;
        }} catch(e) {{
            document.getElementById('pipe-content').innerHTML = '<span style="color:#f87171;">Failed to load pipes: ' + esc(e.message) + '</span>';
        }}
    }}

    // ---- Panel F: Legacy Runner ----
    async function loadLegacy() {{
        try {{
            var res = await fetch('/api/runners/jobs?limit=10');
            var data = await res.json();
            var jobs = data.jobs || [];
            if (jobs.length === 0) {{
                document.getElementById('legacy-content').innerHTML = '<div class="empty-state">No runner jobs found.</div>';
                return;
            }}
            var html = '<table data-testid="legacy-table"><thead><tr>';
            html += '<th>Pipe ID</th><th>Status</th><th>Dispatched</th><th>Rows</th>';
            html += '</tr></thead><tbody>';
            jobs.forEach(function(j) {{
                html += '<tr data-testid="legacy-row">';
                html += '<td style="font-family: monospace; font-size: 0.8rem;">' + esc((j.pipe_id || '').substring(0, 8)) + '</td>';
                html += '<td><span class="badge badge-' + esc(j.status || 'queued') + '">' + esc(j.status) + '</span></td>';
                html += '<td style="font-size: 0.8rem;">' + esc((j.dispatched_at || '').substring(0, 19)) + '</td>';
                html += '<td>' + (j.rows_transferred || '-') + '</td>';
                html += '</tr>';
            }});
            html += '</tbody></table>';
            document.getElementById('legacy-content').innerHTML = html;
        }} catch(e) {{
            document.getElementById('legacy-content').innerHTML = '<span style="color:#f87171;">Failed to load runner jobs: ' + esc(e.message) + '</span>';
        }}
    }}

    // ---- Load all panels on page load ----
    document.addEventListener('DOMContentLoaded', function() {{
        loadMode();
        loadLedger();
        loadHealth();
        loadDrift();
        loadPipes();
    }});
    </script>
</body>
</html>"""


@router.get("/ui/controls", response_class=HTMLResponse)
@router.get("/controls", response_class=HTMLResponse)
async def controls_dashboard():
    """AAM Controls Dashboard — single-page operator view."""
    return HTMLResponse(content=_build_dashboard_html())
