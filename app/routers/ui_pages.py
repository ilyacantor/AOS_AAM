"""
AAM Operator UI Pages — HTML rendering routes.

These routes render the operator-facing UI using inline HTML templates.
Extracted from the monolithic main.py for separation of concerns.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import datetime

from ..constants import (
    ALL_PLANE_TYPES, PLANE_TYPE_LABELS, PLANE_TYPE_SHORT, PLANE_TYPE_COLORS,
    SOR_CATEGORY_COLORS, SOR_CATEGORY_LABELS,
)
from ..ui.styles import NAV_STYLE, UI_STYLE, NAV_HTML, ui_nav, aod_run_banner
from ..db import (
    list_pipes,
    get_pipe,
    get_pipe_versions,
    get_drift_events,
    list_all_drift_events,
    list_candidates,
    get_canonical_stats,
    get_aod_reconciliation,
    list_tee_requests,
    list_handoff_logs,
    get_latest_aod_run,
)
from ..db.runner_jobs import list_runner_jobs

router = APIRouter(include_in_schema=False)

@router.get("/ui/pipes", response_class=HTMLResponse, include_in_schema=False)
async def ui_pipes_list(
    filter: Optional[str] = Query("all")
):
    """Pipes Inventory Screen.

    Plane filter normalization (audit fix #2):
      Current predicate (BEFORE):
        pipes = [p for p in all_pipes if p.get("fabric_plane") == filter]
        # filter values were uppercase canonical (IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE)
      Corrected predicate (AFTER):
        pipes = [p for p in all_pipes if _ui_plane(p.get("fabric_plane")) == filter]
        # filter values are lowercase canonical (ipaas, api_gateway, event_bus, warehouse)
        # _ui_plane normalizes pipe.fabric_plane (uppercase canonical in DB) to the UI form
    """
    all_pipes = list_pipes(limit=200)

    # Map DB-side canonical (uppercase) to the UI's lowercase plane keys.
    # 'warehouse' is the audit-spec key for what the DB stores as DATA_WAREHOUSE.
    _DB_TO_UI_PLANE = {
        "IPAAS": "ipaas",
        "API_GATEWAY": "api_gateway",
        "EVENT_BUS": "event_bus",
        "DATA_WAREHOUSE": "warehouse",
    }
    UI_PLANE_KEYS = ["ipaas", "api_gateway", "event_bus", "warehouse"]

    def _ui_plane(fp: Optional[str]) -> Optional[str]:
        if not fp:
            return None
        return _DB_TO_UI_PLANE.get(fp.upper())

    # Single filter for asset classes — uses pipe.fabric_plane normalized to UI keys
    if filter == "all":
        pipes = all_pipes
    elif filter in UI_PLANE_KEYS:
        pipes = [p for p in all_pipes if _ui_plane(p.get("fabric_plane")) == filter]
    else:
        # Filter by source system
        pipes = [p for p in all_pipes if p.get("source_system") == filter]

    source_systems = sorted(set(p.get("source_system", "") for p in all_pipes if p.get("source_system")))
    
    all_drift = list_all_drift_events(limit=200)
    drift_by_pipe = {}
    for d in all_drift:
        pid = d.get("pipe_id")
        if pid:
            if pid not in drift_by_pipe:
                drift_by_pipe[pid] = {"open": 0, "total": 0}
            drift_by_pipe[pid]["total"] += 1
            if d.get("status") == "open":
                drift_by_pipe[pid]["open"] += 1

    # Fetch latest runner job status per pipe
    try:
        all_jobs = list_runner_jobs(limit=200)
    except Exception as exc:
        _log.error("Failed to fetch runner jobs for dashboard: %s", exc)
        all_jobs = []
    latest_job_by_pipe = {}
    for j in all_jobs:
        pid = j.get("pipe_id")
        if pid and pid not in latest_job_by_pipe:
            latest_job_by_pipe[pid] = j
    
    fabric_plane_colors = {**PLANE_TYPE_COLORS, "UNMAPPED": "#ef4444"}
    
    rows_html = ""
    for p in pipes:
        pipe_id = p.get("pipe_id", "")
        entity_scope = p.get("entity_scope", [])
        trust_labels = p.get("trust_labels", [])
        owner_signals = p.get("owner_signals", [])
        pipe_fabric = p.get("fabric_plane", "UNMAPPED")
        fabric_color = fabric_plane_colors.get(pipe_fabric, "#64748b")
        drift_info = drift_by_pipe.get(pipe_id)
        if drift_info is None:
            drift_status = "No data"
            drift_class = "badge-deferred"
        elif drift_info["open"] > 0:
            drift_status = f"{drift_info['open']} open"
            drift_class = "badge-open"
        else:
            drift_status = "Healthy"
            drift_class = "badge-connected"

        # Runner status pill
        latest_job = latest_job_by_pipe.get(pipe_id)
        if latest_job:
            job_status = latest_job.get("status", "")
            job_id = latest_job.get("job_id", "")
            rows_done = latest_job.get("rows_transferred", 0)
            runner_pill_map = {
                "queued": ("Queued", "runner-queued"),
                "dispatched": ("Dispatched", "runner-queued"),
                "running": ("Running", "runner-running"),
                "pushing": ("Pushing", "runner-running"),
                "completed": (f"Done — {rows_done:,} rows", "runner-completed"),
                "failed": ("Failed", "runner-failed"),
                "timed_out": ("Timeout", "runner-failed"),
            }
            pill_text, pill_class = runner_pill_map.get(job_status, (job_status, "runner-queued"))
            runner_cell = f'<span class="runner-pill {pill_class}" id="pill-{pipe_id}" title="{job_id}">{pill_text}</span>'
        else:
            runner_cell = f'<button class="btn btn-sm btn-run" data-pipe-id="{pipe_id}" id="btn-run-{pipe_id}" onclick="dispatchRunner(\'{pipe_id}\')">Run</button>'

        rows_html += f"""
        <tr data-testid="pipe-row-{pipe_id}">
            <td><span class="fabric-badge" style="background:{fabric_color}20;color:{fabric_color};border:1px solid {fabric_color}40;">{pipe_fabric}</span></td>
            <td><a href="/ui/pipes/{pipe_id}" data-testid="pipe-link-{pipe_id}">{p.get('display_name', 'Unnamed')}</a></td>
            <td>{p.get('source_system', '-')}</td>
            <td>{p.get('modality', '-')}</td>
            <td>{', '.join(entity_scope[:3])}{'...' if len(entity_scope) > 3 else ''}</td>
            <td>{len(trust_labels)}</td>
            <td><span class="badge {drift_class}">{drift_status}</span></td>
            <td class="runner-cell">{runner_cell}</td>
        </tr>
        """
    
    if not pipes:
        rows_html = '<tr><td colspan="8" class="empty-state">No pipes in registry yet. Run discovery from the Topology page to populate.</td></tr>'

    # Build single combined filter dropdown — uses lowercase canonical UI keys
    _UI_PLANE_LABELS = {
        "ipaas": "iPaaS",
        "api_gateway": "API Gateway",
        "event_bus": "Event Bus",
        "warehouse": "Warehouse",
    }
    filter_options = '<option value="all"' + (' selected' if filter == "all" else '') + '>All</option>'
    for f in UI_PLANE_KEYS:
        label = _UI_PLANE_LABELS[f]
        filter_options += f'<option value="{f}"' + (' selected' if filter == f else '') + f'>{label}</option>'
    if source_systems:
        filter_options += '<optgroup label="Sources">'
        for s in source_systems:
            filter_options += f'<option value="{s}"' + (' selected' if filter == s else '') + f'>{s}</option>'
        filter_options += '</optgroup>'
    
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>AAM</title>
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
        .runner-pill {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 600;
            letter-spacing: 0.3px;
            white-space: nowrap;
        }}
        .runner-queued {{
            background: rgba(148, 163, 184, 0.2);
            color: #94a3b8;
            border: 1px solid rgba(148, 163, 184, 0.3);
        }}
        .runner-running {{
            background: rgba(59, 130, 246, 0.2);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.3);
            animation: pulse-blue 1.5s infinite;
        }}
        .runner-completed {{
            background: rgba(34, 197, 94, 0.2);
            color: #4ade80;
            border: 1px solid rgba(34, 197, 94, 0.3);
        }}
        .runner-failed {{
            background: rgba(248, 113, 113, 0.2);
            color: #f87171;
            border: 1px solid rgba(248, 113, 113, 0.3);
        }}
        .btn-run {{
            padding: 2px 12px !important;
            font-size: 0.7rem !important;
            border-radius: 12px;
        }}
        .runner-cell {{
            min-width: 80px;
            text-align: center;
        }}
        @keyframes pulse-blue {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.6; }}
        }}
    </style>
</head>
<body>
    {ui_nav('pipes')}
    <div class="container">
        <h1>Pipes</h1>
        <p class="page-subtitle">All declared data pipes with metadata, health status, and ownership. These are your canonical integration endpoints.</p>
        
        {aod_run_banner()}

        <div class="controls">
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
                    <th>Runner</th>
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
        // --- Mode-aware button gating ---
        (async function applyModeGating() {{
            try {{
                var res = await fetch('/api/aam/mode');
                var data = await res.json();
                if (data.mode === 'SYNTHETIC') {{
                    document.querySelectorAll('.btn-run').forEach(function(el) {{ el.style.display = 'none'; }});
                }}
            }} catch(e) {{
                console.error('Mode gating failed — buttons remain visible:', e);
            }}
        }})();

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

        async function dispatchRunner(pipeId) {{
            const btn = document.getElementById('btn-run-' + pipeId);
            if (!btn) return;
            btn.disabled = true;
            btn.textContent = '...';

            try {{
                const res = await fetch('/api/runners/dispatch', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ pipe_id: pipeId, trigger: 'manual' }})
                }});
                const data = await res.json();
                if (!res.ok) {{
                    showToast('Dispatch failed: ' + (data.detail || res.status), 'error');
                    btn.disabled = false;
                    btn.textContent = 'Run';
                    return;
                }}
                // Replace button with status pill
                const cell = btn.parentElement;
                const jobId = data.job_id || '';
                const status = data.status || 'queued';
                updateRunnerPill(cell, pipeId, status, data.rows_transferred || 0, jobId);
                showToast('Dispatched to Farm: ' + pipeId.substring(0, 8) + '...', 'success');

                // Terminal states — no need to poll
                if (status === 'completed' || status === 'failed') return;

                // Poll for status updates
                pollRunnerStatus(pipeId, jobId);
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
                btn.disabled = false;
                btn.textContent = 'Run';
            }}
        }}

        function updateRunnerPill(cell, pipeId, status, rows, jobId) {{
            const pillMap = {{
                'queued':    ['Queued',    'runner-queued'],
                'dispatched':['Dispatched','runner-queued'],
                'running':   ['Running',   'runner-running'],
                'pushing':   ['Pushing',   'runner-running'],
                'completed': ['Done — ' + Number(rows).toLocaleString() + ' rows', 'runner-completed'],
                'failed':    ['Failed',    'runner-failed'],
                'timed_out': ['Timeout',   'runner-failed'],
            }};
            const [text, cls] = pillMap[status] || [status, 'runner-queued'];
            cell.innerHTML = '<span class="runner-pill ' + cls + '" id="pill-' + pipeId + '" title="' + jobId + '">' + text + '</span>';
        }}

        async function pollRunnerStatus(pipeId, jobId) {{
            const terminal = ['completed', 'failed', 'timed_out'];
            let attempts = 0;
            const maxAttempts = 30;

            const poll = async () => {{
                attempts++;
                if (attempts > maxAttempts) return;
                try {{
                    const res = await fetch('/api/runners/jobs/' + jobId);
                    if (!res.ok) return;
                    const job = await res.json();
                    const status = job.status || 'queued';
                    const pill = document.getElementById('pill-' + pipeId);
                    if (pill) {{
                        updateRunnerPill(pill.parentElement, pipeId, status, job.rows_transferred || 0, jobId);
                    }}
                    if (terminal.includes(status)) {{
                        if (status === 'completed') {{
                            showToast('Runner completed: ' + (job.rows_transferred || 0) + ' rows transferred', 'success');
                        }} else {{
                            showToast('Runner ' + status + ': ' + (job.error_message || ''), 'error');
                        }}
                        return;
                    }}
                }} catch (e) {{ /* ignore polling errors */ }}
                setTimeout(poll, 1000);
            }};
            setTimeout(poll, 500);
        }}

    </script>
</body>
</html>
""")


@router.get("/ui/pipes/{pipe_id}", response_class=HTMLResponse, include_in_schema=False)
async def ui_pipe_detail(pipe_id: str):
    """Pipe Detail Screen"""
    pipe = get_pipe(pipe_id)
    if not pipe:
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>AAM</title>
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
    <title>AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
</head>
<body>
    {ui_nav('pipes')}
    <div class="container">
        <div class="controls">
            <a href="/ui/pipes" class="btn" data-testid="btn-back">← Back to Pipes</a>
            <button class="btn btn-success" id="btn-dispatch" data-testid="btn-dispatch">Dispatch Runner</button>
            <span id="runner-status-pill" style="margin-left:8px;"></span>
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
        // --- Mode-aware button gating ---
        (async function applyModeGating() {{
            try {{
                var res = await fetch('/api/aam/mode');
                var data = await res.json();
                if (data.mode === 'SYNTHETIC') {{
                    var el = document.getElementById('btn-dispatch');
                    if (el) el.style.display = 'none';
                }}
            }} catch(e) {{
                console.error('Mode gating failed — buttons remain visible:', e);
            }}
        }})();

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
                if (!res.ok) throw new Error('Request failed: ' + res.status);
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

        // --- Dispatch Runner ---
        document.getElementById('btn-dispatch').addEventListener('click', async function() {{
            const btn = this;
            btn.disabled = true;
            btn.textContent = 'Dispatching...';
            const pill = document.getElementById('runner-status-pill');

            try {{
                const res = await fetch('/api/runners/dispatch', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ pipe_id: '{pipe_id}', trigger: 'manual' }})
                }});
                const data = await res.json();
                if (!res.ok) {{
                    showToast('Dispatch failed: ' + (data.detail || res.status), 'error');
                    btn.disabled = false;
                    btn.textContent = 'Dispatch Runner';
                    return;
                }}

                const jobId = data.job_id || '';
                const status = data.status || 'queued';
                const rows = data.rows_transferred || 0;

                function setPill(s, r) {{
                    const map = {{
                        'queued':    ['Queued',    '#94a3b8', 'rgba(148,163,184,0.2)'],
                        'dispatched':['Dispatched','#94a3b8', 'rgba(148,163,184,0.2)'],
                        'running':   ['Running',   '#60a5fa', 'rgba(59,130,246,0.2)'],
                        'pushing':   ['Pushing',   '#60a5fa', 'rgba(59,130,246,0.2)'],
                        'completed': ['Done — ' + Number(r).toLocaleString() + ' rows', '#4ade80', 'rgba(34,197,94,0.2)'],
                        'failed':    ['Failed',    '#f87171', 'rgba(248,113,113,0.2)'],
                        'timed_out': ['Timeout',   '#f87171', 'rgba(248,113,113,0.2)'],
                    }};
                    const [text, color, bg] = map[s] || [s, '#94a3b8', 'rgba(148,163,184,0.2)'];
                    pill.innerHTML = '<span style="display:inline-block;padding:4px 12px;border-radius:12px;font-size:0.8rem;font-weight:600;color:' + color + ';background:' + bg + ';border:1px solid ' + color + '40;">' + text + '</span>';
                }}

                setPill(status, rows);
                showToast('Runner dispatched: ' + jobId, 'success');
                btn.textContent = 'Dispatch Runner';
                btn.disabled = false;

                // Poll if not terminal
                const terminal = ['completed', 'failed', 'timed_out'];
                if (terminal.includes(status)) return;

                let attempts = 0;
                const pollDetail = async () => {{
                    attempts++;
                    if (attempts > 30) return;
                    try {{
                        const r = await fetch('/api/runners/jobs/' + jobId);
                        if (!r.ok) return;
                        const job = await r.json();
                        setPill(job.status, job.rows_transferred || 0);
                        if (terminal.includes(job.status)) {{
                            if (job.status === 'completed') showToast('Runner completed: ' + (job.rows_transferred || 0) + ' rows', 'success');
                            else showToast('Runner ' + job.status, 'error');
                            return;
                        }}
                    }} catch (e) {{}}
                    setTimeout(pollDetail, 1000);
                }};
                setTimeout(pollDetail, 500);

            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
                btn.disabled = false;
                btn.textContent = 'Dispatch Runner';
            }}
        }});
    </script>
</body>
</html>
""")


@router.get("/ui/candidates", response_class=HTMLResponse, include_in_schema=False)
async def ui_candidates_list(
    view: Optional[str] = Query("sors_fabrics", description="View filter: all, sors, fabrics, sors_fabrics, ipaas, api_gateway, event_bus, warehouse")
):
    """Candidates Screen.

    Plane filter normalization (audit fix #2):
      Current predicate (BEFORE):
        _plane_view_map = {"ipaas": "IPAAS", "warehouse": "DATA_WAREHOUSE",
                           "gateway": "API_GATEWAY", "eventbus": "EVENT_BUS"}
      Corrected predicate (AFTER):
        _plane_view_map = {"ipaas": "IPAAS", "api_gateway": "API_GATEWAY",
                           "event_bus": "EVENT_BUS", "warehouse": "DATA_WAREHOUSE"}
      Field unchanged — still filters via _plane_type(c) which derives from
      candidate.fabric_plane_id / connected_via_plane (the candidate-side
      equivalent of pipe.fabric_plane).
    """
    all_candidates = list_candidates(limit=200)

    from ..db.stats import _is_aod_sor

    # Resolve a candidate's fabric plane TYPE from its linkage or routing hint
    _plane_view_map = {
        "ipaas": "IPAAS",
        "api_gateway": "API_GATEWAY",
        "event_bus": "EVENT_BUS",
        "warehouse": "DATA_WAREHOUSE",
    }

    def _plane_type(c: dict):
        fpid = c.get("fabric_plane_id") or ""
        if fpid and ":" in fpid:
            return fpid.split(":")[0].upper()
        cvp = c.get("connected_via_plane") or ""
        return cvp.upper() if cvp else None

    # Filter based on view mode
    if view == "all":
        candidates = all_candidates
    elif view == "sors":
        candidates = [c for c in all_candidates if _is_aod_sor(c)]
    elif view == "fabrics":
        candidates = [c for c in all_candidates if _plane_type(c) is not None]
    elif view == "sors_fabrics":
        candidates = [c for c in all_candidates
                      if _is_aod_sor(c) or _plane_type(c) is not None]
    elif view in _plane_view_map:
        target = _plane_view_map[view]
        candidates = [c for c in all_candidates if _plane_type(c) == target]
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
    <title>AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
</head>
<body>
    {ui_nav('candidates')}
    <div class="container">
        <h1>Candidates</h1>
        <p class="page-subtitle">Connection requests from AOD discovery. Triage, match to pipes, or defer candidates that don't fit your integration mesh.</p>
        
        {aod_run_banner()}
        
        <div class="controls">
            <span style="color: var(--text-secondary, #94a3b8); font-size: 0.85rem;">Showing {len(candidates)} of {len(all_candidates)}</span>
            <select id="filter-view" data-testid="filter-view" onchange="applyFilter()">
                <option value="all"{" selected" if view == "all" else ""}>All</option>
                <option value="sors"{" selected" if view == "sors" else ""}>SORs</option>
                <option value="fabrics"{" selected" if view == "fabrics" else ""}>Fabrics</option>
                <option value="sors_fabrics"{" selected" if view == "sors_fabrics" else ""}>SORs + Fabrics</option>
                <option value="ipaas"{" selected" if view == "ipaas" else ""}>iPaaS</option>
                <option value="api_gateway"{" selected" if view == "api_gateway" else ""}>API Gateway</option>
                <option value="event_bus"{" selected" if view == "event_bus" else ""}>Event Bus</option>
                <option value="warehouse"{" selected" if view == "warehouse" else ""}>Warehouse</option>
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
                if (!res.ok) throw new Error('Request failed: ' + res.status);
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


@router.get("/ui/guide", response_class=HTMLResponse, include_in_schema=False)
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
    <title>AAM</title>
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
                <tr><td>Run Inference</td><td>Converts candidates from AOD into declared pipes with metadata</td></tr>
                <tr><td>Export to DCL</td><td>Generates a snapshot of all pipes in DCL format for downstream consumption</td></tr>
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
                <div class="guide-card-title">Exploring the Integration Mesh</div>
                <ol>
                    <li>Start at the <strong>Topology</strong> screen (the landing page)</li>
                    <li>Use the View filter to focus on a specific fabric plane</li>
                    <li>Click nodes to see their metadata in the side panel</li>
                    <li>Double-click a pipe to drill into its detail page</li>
                </ol>
            </div>

            <div class="guide-card">
                <div class="guide-card-title">Creating Pipes from AOD Data</div>
                <ol>
                    <li>Fetch AOD data from the <strong>Pipes</strong> screen</li>
                    <li>Click <strong>Run Inference</strong> to convert candidates into declared pipes</li>
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


@router.get("/ui/drift", response_class=HTMLResponse, include_in_schema=False)
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
    <title>AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
</head>
<body>
    {ui_nav('drift')}
    <div class="container">
        <h1>Drift & Health</h1>
        <p class="page-subtitle">Monitor schema changes and connectivity issues. Acknowledge, suppress, or take action on drift events.</p>
        <div class="controls">
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
        
    </script>
</body>
</html>
""")


@router.get("/ui/topology", response_class=HTMLResponse, include_in_schema=False)
async def ui_topology():
    """Topology Visualization Screen"""
    latest_run = get_latest_aod_run()
    if latest_run:
        _snap = latest_run.get("entity_id") or latest_run.get("snapshot_name") or "Unnamed"
        _pipes = latest_run.get("candidates_accepted", 0)
        _ts = (latest_run.get("handoff_timestamp") or "")[:10]
        _rid = latest_run.get("aod_run_id", "")
        _run_html = (
            f'<div class="sb-val" style="color:#f0abfc;">{_snap}</div>'
            f'<div class="sb-kpi"><span>{_pipes}</span> pipes</div>'
            f'<div class="sb-dim">{_ts}</div>'
        )
        _recon_html = f'<a href="/ui/reconcile/{_rid}" class="sb-link">Reconcile</a>'
    else:
        _run_html = '<div class="sb-val" style="color:#fb923c;">No AOD data</div>'
        _recon_html = ''

    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        .topo-page {{ padding: 0 12px 12px; }}
        .topo-layout {{ display: flex; gap: 10px; height: calc(100vh - 60px); }}
        .topo-sidebar {{
            width: 176px; flex-shrink: 0;
            display: flex; flex-direction: column;
            background: rgba(30, 41, 59, 0.5);
            border: 1px solid var(--slate-700);
            border-radius: 8px;
            overflow-y: auto;
        }}
        .topo-sidebar::-webkit-scrollbar {{ width: 3px; }}
        .topo-sidebar::-webkit-scrollbar-thumb {{ background: var(--slate-700); border-radius: 3px; }}
        .topo-main {{ flex: 1; min-width: 0; position: relative; }}
        #topology-container {{
            width: 100%; height: 100%; border: 1px solid var(--slate-700); border-radius: 8px;
            background-color: rgba(15, 23, 42, 0.8);
            background-image: radial-gradient(circle, rgba(148, 163, 184, 0.07) 1px, transparent 1px);
            background-size: 20px 20px;
        }}
        .sb-section {{ padding: 8px 10px; }}
        .sb-section + .sb-section {{ border-top: 1px solid rgba(51, 65, 85, 0.5); }}
        .sb-title {{ font-size: 0.58rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--slate-500); margin-bottom: 5px; font-weight: 600; }}
        .sb-val {{ font-weight: 600; font-size: 0.82rem; line-height: 1.25; word-break: break-word; color: var(--slate-200); }}
        .sb-kpi {{ margin-top: 3px; font-size: 0.7rem; color: var(--slate-400); }}
        .sb-kpi span {{ font-size: 1.15rem; font-weight: 700; color: var(--cyan-400); margin-right: 2px; }}
        .sb-dim {{ font-size: 0.62rem; color: var(--slate-500); margin-top: 2px; }}
        .sb-link {{ font-size: 0.68rem; color: var(--slate-400); display: inline-block; margin-top: 4px; }}
        .sb-stats {{ display: flex; flex-direction: column; gap: 2px; }}
        .sb-stat {{ font-size: 0.7rem; color: var(--slate-400); display: flex; justify-content: space-between; align-items: center; }}
        .sb-stat span:last-child {{ color: var(--cyan-400); font-weight: 600; }}
        .sb-stat-health {{ flex-direction: column; align-items: stretch; gap: 2px; }}
        .sb-stat-health > span:first-child {{ color: var(--slate-400); }}
        .sb-health-grid {{
            display: grid; grid-template-columns: repeat(4, 1fr); gap: 2px;
            font-size: 0.62rem; color: var(--slate-500);
        }}
        .sb-health-grid b {{ color: var(--cyan-400); font-weight: 600; }}
        .sb-cred-results {{
            display: flex; flex-direction: column; gap: 2px;
            margin: 2px 0 4px; font-size: 0.62rem; color: var(--slate-400);
        }}
        .sb-cred-results .cred-row {{ display: flex; justify-content: space-between; }}
        .sb-cred-results .cred-status.connected {{ color: #4ade80; }}
        .sb-cred-results .cred-status.failed {{ color: #f87171; }}
        .sb-cred-results .cred-status.pending {{ color: #fbbf24; }}
        .sb-stop-link {{
            font-size: 0.65rem; color: #f87171; text-decoration: underline; margin-top: 2px;
        }}
        .sb-btn {{
            width: 100%; padding: 4px 8px; border-radius: 4px;
            font-size: 0.7rem; font-weight: 500; cursor: pointer;
            border: 1px solid var(--slate-700); background: transparent;
            color: var(--slate-300); text-align: left;
            transition: all 0.15s; font-family: inherit; margin-bottom: 2px;
        }}
        .sb-btn:hover {{ background: rgba(34, 211, 238, 0.08); border-color: rgba(34, 211, 238, 0.3); color: var(--cyan-400); }}
        .sb-btn:disabled {{ opacity: 0.4; cursor: not-allowed; }}
        .sb-btn-accent {{ border-color: rgba(251, 146, 60, 0.3); color: #fb923c; }}
        .sb-btn-accent:hover {{ background: rgba(251, 146, 60, 0.1); }}
        .sb-btn-runner {{ border-color: rgba(34, 197, 94, 0.3); color: #4ade80; }}
        .sb-btn-runner:hover {{ background: rgba(34, 197, 94, 0.1); }}
        .sb-btn-runner:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .sb-btn-primary {{
            background: var(--cyan-400); color: #0f172a; font-weight: 700;
            border-color: var(--cyan-400);
        }}
        .sb-btn-primary:hover {{ background: var(--cyan-500); border-color: var(--cyan-500); color: #0f172a; }}
        .sb-btn-primary:disabled {{ opacity: 0.5; cursor: not-allowed; background: var(--cyan-400); color: #0f172a; }}
        .sb-btn-stop {{ border-color: rgba(248, 113, 113, 0.3); color: #f87171; }}
        .sb-btn-stop:hover {{ background: rgba(248, 113, 113, 0.15); }}
        .sb-btn-ghost {{
            background: transparent; border: 1px dashed var(--slate-600);
            color: var(--slate-500); font-weight: 400;
        }}
        .sb-btn-ghost:hover {{ background: rgba(34, 211, 238, 0.06); border-color: rgba(34, 211, 238, 0.25); color: var(--cyan-400); border-style: solid; }}
        .sb-badge {{
            width: 100%; padding: 3px 8px; border-radius: 10px;
            font-size: 0.65rem; font-weight: 500; text-align: center;
            background: rgba(51, 65, 85, 0.6); color: var(--slate-400);
            border: 1px solid var(--slate-700); cursor: default;
            margin-bottom: 2px; display: none;
        }}
        .dispatch-pill {{
            display: inline-block; padding: 1px 7px; border-radius: 8px;
            font-size: 0.62rem; font-weight: 600; letter-spacing: 0.3px;
        }}
        .dispatch-pill.queued {{ background: rgba(148,163,184,0.2); color: #94a3b8; }}
        .dispatch-pill.running {{ background: rgba(59,130,246,0.2); color: #60a5fa; animation: pulse-blue 1.5s infinite; }}
        .dispatch-pill.completed {{ background: rgba(34,197,94,0.2); color: #4ade80; }}
        .dispatch-pill.failed {{ background: rgba(248,113,113,0.2); color: #f87171; }}
        @keyframes pulse-blue {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.6; }} }}
        .sb-select {{
            width: 100%; padding: 3px 20px 3px 6px; font-size: 0.7rem;
            background: rgba(15, 23, 42, 0.6); border: 1px solid var(--slate-700);
            border-radius: 4px; color: var(--slate-300);
            font-family: inherit; cursor: pointer; margin-bottom: 3px;
            appearance: none; -webkit-appearance: none; -moz-appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%2394a3b8' stroke-width='1.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 6px center;
            background-size: 10px;
        }}
        .sb-select:focus {{ outline: none; border-color: rgba(34, 211, 238, 0.4); }}
        .sb-legend {{ display: flex; flex-direction: column; gap: 2px; }}
        .sb-legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 0.65rem; color: var(--slate-400); }}
        .topo-zoom-controls {{
            position: absolute; bottom: 12px; right: 12px; z-index: 50;
            display: flex; flex-direction: column; gap: 4px;
        }}
        .topo-zoom-btn {{
            width: 32px; height: 32px; border-radius: 6px;
            background: rgba(30, 41, 59, 0.9); border: 1px solid var(--slate-700);
            color: var(--slate-300); font-size: 1rem; cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            font-family: inherit; padding: 0; line-height: 1;
            transition: all 0.15s;
        }}
        .topo-zoom-btn:hover {{ border-color: rgba(34, 211, 238, 0.3); color: var(--cyan-400); }}
        .topo-legend-overlay {{
            position: absolute; bottom: 12px; left: 12px; z-index: 50;
            background: rgba(30, 41, 59, 0.9); border: 1px solid var(--slate-700);
            border-radius: 6px; padding: 8px 10px;
        }}
        .sb-legend-item svg {{ width: 10px; height: 10px; flex-shrink: 0; }}
        .sb-accordion-hdr {{
            display: flex; align-items: center; gap: 5px; cursor: pointer;
            user-select: none;
        }}
        .sb-accordion-hdr .sb-title {{ margin-bottom: 0; }}
        .sb-accordion-chev {{
            font-size: 0.55rem; color: var(--slate-500);
            transition: transform 0.2s ease;
            display: inline-block;
        }}
        .sb-accordion-hdr.open .sb-accordion-chev {{ transform: rotate(90deg); }}
        .sb-accordion-body {{
            max-height: 0; overflow: hidden;
            transition: max-height 0.25s ease;
        }}
        .sb-accordion-body.open {{ max-height: 400px; }}
        .sb-accordion-count {{
            font-size: 0.55rem; color: var(--slate-500); font-weight: 400;
        }}
        @keyframes sb-spin {{ to {{ transform: rotate(360deg); }} }}
        .sb-btn-loading {{
            position: relative; padding-left: 22px; pointer-events: none;
        }}
        .sb-btn-loading::before {{
            content: ''; position: absolute; left: 6px; top: 50%;
            width: 10px; height: 10px; margin-top: -5px;
            border: 2px solid var(--slate-600); border-top-color: var(--cyan-400);
            border-radius: 50%; animation: sb-spin 0.6s linear infinite;
        }}
        .node-details {{
            position: absolute; top: 10px; right: 10px; width: 260px;
            background: rgba(30, 41, 59, 0.95); border: 1px solid var(--slate-700);
            border-radius: 8px; padding: 12px; z-index: 100;
            opacity: 0; transform: translateY(-8px); pointer-events: none;
            transition: opacity 0.2s ease, transform 0.2s ease;
        }}
        .node-details.visible {{ opacity: 1; transform: translateY(0); pointer-events: auto; }}
        .node-details h3 {{ margin: 0 0 8px 0; color: var(--cyan-400); font-size: 0.85rem; padding-right: 20px; }}
        .node-details .close-btn {{ position: absolute; top: 6px; right: 8px; background: none; border: none; color: var(--slate-400); cursor: pointer; font-size: 1rem; }}
        .node-details .close-btn:hover {{ color: #fff; }}
        .node-details .field {{ display: flex; justify-content: space-between; align-items: baseline; padding: 3px 0; border-bottom: 1px solid rgba(51, 65, 85, 0.4); }}
        .node-details .field:last-child {{ border-bottom: none; }}
        .node-details .field-label {{ font-size: 0.65rem; color: var(--slate-500); text-transform: uppercase; letter-spacing: 0.05em; }}
        .node-details .field-value {{ font-size: 0.72rem; color: var(--slate-200); text-align: right; max-width: 60%; word-break: break-word; }}
        .topo-search-wrap {{
            position: absolute; top: 10px; left: 50%; transform: translateX(-50%);
            z-index: 50; display: flex; align-items: center;
        }}
        .topo-search {{
            width: 200px; padding: 5px 26px 5px 10px; font-size: 0.72rem;
            background: rgba(30, 41, 59, 0.9); border: 1px solid var(--slate-700);
            border-radius: 6px; color: var(--slate-200); font-family: inherit;
            outline: none; transition: border-color 0.15s;
        }}
        .topo-search::placeholder {{ color: var(--slate-500); }}
        .topo-search:focus {{ border-color: rgba(34, 211, 238, 0.4); }}
        .topo-search-clear {{
            position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
            background: none; border: none; color: var(--slate-500); cursor: pointer;
            font-size: 0.85rem; padding: 0 2px; display: none; line-height: 1;
        }}
        .topo-search-clear:hover {{ color: var(--slate-300); }}

        .dispatch-overlay {{
            position: fixed; inset: 0; background: rgba(0,0,0,0.6);
            z-index: 9000; display: none; justify-content: center; align-items: center;
        }}
        .dispatch-overlay.visible {{ display: flex; }}
        .dispatch-panel {{
            background: #0f172a; border: 1px solid var(--slate-700);
            border-radius: 10px; width: 720px; max-width: 92vw;
            height: 72vh; display: flex; flex-direction: column;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            position: relative;
        }}
        .dispatch-panel.dp-dragging {{ user-select: none; }}
        .dp-header {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 14px 18px; border-bottom: 1px solid var(--slate-700);
            cursor: grab;
        }}
        .dp-header:active {{ cursor: grabbing; }}
        .dp-header h2 {{ font-size: 0.95rem; color: var(--slate-100); margin: 0; }}
        .dp-header .dp-close {{
            background: none; border: none; color: var(--slate-400);
            cursor: pointer; font-size: 1.2rem; padding: 2px 6px;
        }}
        .dp-header .dp-close:hover {{ color: var(--slate-200); }}
        .dp-stop-btn {{
            margin-left: auto; margin-right: 8px;
            background: rgba(248, 113, 113, 0.1); border: 1px solid rgba(248, 113, 113, 0.3);
            color: #f87171; border-radius: 6px; padding: 4px 14px;
            font-size: 0.72rem; font-weight: 600; cursor: pointer;
        }}
        .dp-stop-btn:hover {{ background: rgba(248, 113, 113, 0.2); }}
        .dp-summary {{
            display: flex; gap: 12px; padding: 12px 18px;
            border-bottom: 1px solid rgba(51,65,85,0.5);
        }}
        .dp-stat {{
            display: flex; flex-direction: column; align-items: center;
            padding: 8px 14px; border-radius: 6px;
            background: rgba(30,41,59,0.8); min-width: 70px;
            cursor: pointer; border: 1px solid transparent;
            transition: border-color 0.15s, background 0.15s;
        }}
        .dp-stat:hover {{ border-color: var(--slate-500); background: rgba(30,41,59,1); }}
        .dp-stat.dp-active {{ border-color: var(--cyan-400); background: rgba(34,211,238,0.08); }}
        .dp-stat .dp-val {{ font-size: 1.3rem; font-weight: 700; }}
        .dp-stat .dp-lbl {{ font-size: 0.6rem; color: var(--slate-400); text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px; }}
        .dp-stat.completed .dp-val {{ color: #4ade80; }}
        .dp-stat.failed .dp-val {{ color: #f87171; }}
        .dp-stat.running .dp-val {{ color: #60a5fa; }}
        .dp-stat.queued .dp-val {{ color: #94a3b8; }}
        .dp-stat.total .dp-val {{ color: var(--cyan-400); }}
        .dp-stat.skipped .dp-val {{ color: #fb923c; }}
        .dp-stat.rows .dp-val {{ color: #a78bfa; }}
        .dp-jobs {{
            flex: 1; overflow-y: auto; padding: 8px 18px 14px;
        }}
        .dp-jobs table {{
            width: 100%; border-collapse: collapse; font-size: 0.7rem;
        }}
        .dp-jobs th {{
            text-align: left; padding: 6px 8px; color: var(--slate-400);
            border-bottom: 1px solid var(--slate-700); font-weight: 600;
            font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.5px;
            position: sticky; top: 0; background: #0f172a;
        }}
        .dp-jobs td {{
            padding: 5px 8px; border-bottom: 1px solid rgba(51,65,85,0.3);
            color: var(--slate-300);
        }}
        .dp-jobs tr:hover td {{ background: rgba(51,65,85,0.2); }}
        .dp-status {{
            display: inline-block; padding: 1px 7px; border-radius: 8px;
            font-size: 0.6rem; font-weight: 600;
        }}
        .dp-status.completed {{ background: rgba(34,197,94,0.15); color: #4ade80; }}
        .dp-status.failed {{ background: rgba(248,113,113,0.15); color: #f87171; }}
        .dp-status.cancelled {{ background: rgba(248,113,113,0.10); color: #fb923c; }}
        .dp-status.running {{ background: rgba(59,130,246,0.15); color: #60a5fa; }}
        .dp-status.pushing {{ background: rgba(167,139,250,0.15); color: #a78bfa; }}
        .dp-status.dispatched {{ background: rgba(34,211,238,0.12); color: #22d3ee; }}
        .dp-status.queued {{ background: rgba(148,163,184,0.15); color: #94a3b8; }}
        .dp-status.skipped {{ background: rgba(251,146,60,0.15); color: #fb923c; }}
        .dp-status.idem-skip {{ background: rgba(251,146,60,0.15); color: #fb923c; }}
        .dp-error {{ color: #f87171; font-size: 0.6rem; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
        .dp-error:hover {{ white-space: normal; word-break: break-all; }}
        .dp-detail {{ background: rgba(15,23,42,0.9); }}
        .dp-detail td {{ padding: 0 !important; border-bottom: 1px solid rgba(51,65,85,0.3); }}
        .dp-detail-inner {{
            padding: 8px 12px; font-size: 0.62rem; color: var(--slate-400);
            display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px;
        }}
        .dp-detail-inner .dp-kv {{ display: flex; gap: 6px; }}
        .dp-detail-inner .dp-k {{ color: var(--slate-500); min-width: 70px; }}
        .dp-detail-inner .dp-v {{ color: var(--slate-300); word-break: break-all; }}
        .dp-detail-inner .dp-v.err {{ color: #f87171; }}
        .dp-detail-inner .dp-full {{ grid-column: 1 / -1; }}
        .dp-jobs tr.dp-clickable {{ cursor: pointer; }}
        .dp-jobs tr.dp-clickable:hover td {{ background: rgba(51,65,85,0.3); }}
        .dp-stat[data-tooltip] {{ position: relative; }}
        .dp-stat[data-tooltip]:hover::after {{
            content: attr(data-tooltip); position: absolute; top: calc(100% + 6px); left: 50%;
            transform: translateX(-50%); background: #1e293b; border: 1px solid var(--slate-600);
            color: var(--slate-300); padding: 6px 10px; border-radius: 6px;
            font-size: 0.6rem; white-space: normal; width: 180px; text-align: center;
            z-index: 100; line-height: 1.4; pointer-events: none;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }}
    </style>
</head>
<body>
    {ui_nav("topology")}
    <div class="topo-page">
    <div class="topo-layout">
        <aside class="topo-sidebar">
            <div class="sb-section" id="sb-run-section">
                <div class="sb-title">Run</div>
                <div id="sb-run-info">{_run_html}</div>
                <div id="sb-recon-link">{_recon_html}</div>
            </div>
            <div class="sb-section">
                <div class="sb-title">Instrumentation</div>
                <div class="sb-stats">
                    <div class="sb-stat" data-testid="stat-planes"><span>Planes</span> <span id="stat-planes">-</span></div>
                    <div class="sb-stat" data-testid="stat-sors"><span>SORs</span> <span id="stat-sors">-</span></div>
                    <div class="sb-stat" data-testid="stat-pipes"><span>Pipes</span> <span id="stat-pipes">-</span></div>
                    <div class="sb-stat" data-testid="stat-drift"><span>Drift</span> <span id="stat-drift">-</span></div>
                    <div class="sb-stat sb-stat-health" data-testid="stat-health">
                        <span>Health</span>
                        <span class="sb-health-grid">
                            <span title="Reachable">R:<b id="health-reachable" data-testid="health-reachable">-</b></span>
                            <span title="Degraded">D:<b id="health-degraded" data-testid="health-degraded">-</b></span>
                            <span title="Unreachable">U:<b id="health-unreachable" data-testid="health-unreachable">-</b></span>
                            <span title="Auth expired">A:<b id="health-auth-expired" data-testid="health-auth-expired">-</b></span>
                        </span>
                    </div>
                </div>
            </div>
            <div class="sb-section">
                <div class="sb-title">Actions</div>
                <button class="sb-btn sb-btn-primary" id="btn-run-inference" data-testid="btn-run-inference">Run Inference</button>
                <button class="sb-btn" id="btn-run-discovery" data-testid="btn-run-discovery" disabled>Run Discovery</button>
                <button class="sb-btn" id="btn-validate-credentials" data-testid="btn-validate-credentials" disabled>Validate Credentials</button>
                <div id="cred-results" class="sb-cred-results" style="display:none;"></div>
                <button class="sb-btn" id="btn-start-ingest" data-testid="btn-start-ingest" disabled>Start Ingest</button>
                <a class="sb-link sb-stop-link" id="ingest-stop-link" data-testid="ingest-stop-link" href="#" style="display:none;">Stop ingest</a>
            </div>
            <div class="sb-section">
                <div class="sb-title">View</div>
                <select class="sb-select" id="asset-filter" onchange="applyTopologyFilters()">
                    <option value="all" selected>All Assets</option>
                    <option value="sors">SORs Only</option>
                    <option value="fabrics">Fabrics Only</option>
                    <option value="api_gateway">API Gateway</option>
                    <option value="ipaas">iPaaS</option>
                    <option value="event_bus">Event Bus</option>
                    <option value="warehouse">Warehouse</option>
                </select>
                <select class="sb-select" id="detail-filter" onchange="applyTopologyFilters()">
                    <option value="summary" selected>Summary</option>
                    <option value="all">All Nodes</option>
                </select>
                <select class="sb-select" id="layout-select" onchange="handleLayoutAction(this.value)">
                    <option value="physics">Force-Directed</option>
                    <option value="hierarchical">Hierarchical</option>
                    <option value="circular">Circular</option>
                    <option disabled>─────────</option>
                    <option value="_fit">Fit to Screen</option>
                    <option value="_unlock">Unlock Nodes</option>
                </select>
                <button class="sb-btn sb-btn-ghost" onclick="resetView()" style="margin-top:1px;">Reset</button>
            </div>
        </aside>
        <main class="topo-main">
            <div id="topology-container"></div>
            <div class="topo-search-wrap">
                <input type="text" class="topo-search" id="topo-search" placeholder="Search nodes..." oninput="filterNodesBySearch(this.value)">
                <button class="topo-search-clear" id="topo-search-clear" onclick="clearNodeSearch()">&times;</button>
            </div>
            <div class="topo-zoom-controls">
                <button class="topo-zoom-btn" onclick="if(network)network.moveTo({{scale:network.getScale()*1.3}})" title="Zoom in">+</button>
                <button class="topo-zoom-btn" onclick="if(network)network.moveTo({{scale:network.getScale()/1.3}})" title="Zoom out">&minus;</button>
                <button class="topo-zoom-btn" onclick="fitToScreen()" title="Fit to screen">&#x2b1c;</button>
            </div>
            <div class="topo-legend-overlay">
                <div class="sb-title">Legend</div>
                <div class="sb-legend">
                    <div class="sb-legend-item"><svg viewBox="0 0 12 12"><polygon points="6,0 12,6 6,12 0,6" fill="#a78bfa"/></svg> Gateway</div>
                    <div class="sb-legend-item"><svg viewBox="0 0 12 12"><polygon points="6,0 12,6 6,12 0,6" fill="#22d3ee"/></svg> iPaaS</div>
                    <div class="sb-legend-item"><svg viewBox="0 0 12 12"><polygon points="6,0 12,6 6,12 0,6" fill="#f97316"/></svg> Event Bus</div>
                    <div class="sb-legend-item"><svg viewBox="0 0 12 12"><polygon points="6,0 12,6 6,12 0,6" fill="#10b981"/></svg> Warehouse</div>
                    <div class="sb-legend-item"><svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="5" fill="#60a5fa"/></svg> Pipe</div>
                    <div class="sb-legend-item"><svg viewBox="0 0 12 12"><rect x="1" y="1" width="10" height="10" fill="#94a3b8"/></svg> Source</div>
                    <div class="sb-legend-item"><svg viewBox="0 0 12 12"><polygon points="6,1 11,11 1,11" fill="#c084fc"/></svg> Candidate</div>
                    <div class="sb-legend-item"><svg viewBox="0 0 12 12"><rect x="1" y="1" width="10" height="10" fill="#f59e0b" stroke="#fbbf24" stroke-width="2"/></svg> SOR</div>
                </div>
            </div>
            <div id="node-details" class="node-details">
                <button class="close-btn" onclick="closeDetails()">&times;</button>
                <h3 id="detail-title">Node Details</h3>
                <div id="detail-content"></div>
            </div>
        </main>
    </div>
    </div>
    <div id="toast" class="toast"></div>

    <script>
        // --- View state (Fix 1): URL params are the source of truth ---
        // Persist asset-filter, detail-filter, layout selections in
        // ?view=...&detail=...&layout=... so they survive data re-fetches
        // and navigation away/back. The dropdowns are mirrors of the URL.
        var VALID_VIEWS = ['all','sors','fabrics','ipaas','api_gateway','event_bus','warehouse'];
        var VALID_DETAILS = ['summary','all'];
        var VALID_LAYOUTS = ['physics','hierarchical','circular'];
        function getViewState() {{
            var p = new URLSearchParams(window.location.search);
            var v = p.get('view'); var d = p.get('detail'); var l = p.get('layout');
            return {{
                view: VALID_VIEWS.indexOf(v) >= 0 ? v : 'all',
                detail: VALID_DETAILS.indexOf(d) >= 0 ? d : 'summary',
                layout: VALID_LAYOUTS.indexOf(l) >= 0 ? l : 'physics',
            }};
        }}
        function setViewState(partial) {{
            var p = new URLSearchParams(window.location.search);
            for (var k in partial) {{ if (partial[k] != null) p.set(k, partial[k]); }}
            var qs = p.toString();
            history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
        }}

        async function refreshSidebarRun() {{
            var el = document.getElementById('sb-run-info');
            try {{
                var res = await fetch('/api/handoff/aod/latest');
                if (!res.ok) {{
                    console.error('refreshSidebarRun: /api/handoff/aod/latest returned ' + res.status);
                    if (el) {{
                        el.innerHTML = '<div class="sb-dim" style="color:#f87171;">handoff fetch failed (' + res.status + ')</div>';
                    }}
                    return;
                }}
                var run = await res.json();
                if (el && run && (run.entity_id || run.snapshot_name)) {{
                    var snap = run.entity_id || run.snapshot_name || 'Unnamed';
                    var pipes = run.candidates_accepted || 0;
                    var ts = (run.handoff_timestamp || '').substring(0, 10);
                    el.innerHTML = '<div class="sb-val" style="color:#f0abfc;">' + snap + '</div>' +
                        '<div class="sb-kpi"><span>' + pipes + '</span> pipes</div>' +
                        '<div class="sb-dim">' + ts + '</div>';
                }}
                var reconEl = document.getElementById('sb-recon-link');
                if (reconEl && run && run.aod_run_id) {{
                    reconEl.innerHTML = '<a href="/ui/reconcile/' + run.aod_run_id + '" class="sb-link">Reconcile</a>';
                }}
            }} catch(e) {{
                console.error('refreshSidebarRun: network error', e);
                if (el) {{
                    el.innerHTML = '<div class="sb-dim" style="color:#f87171;">handoff fetch network error</div>';
                }}
            }}
        }}

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

        async function loadTopology() {{
            // Source of truth: URL params via getViewState(). The dropdowns
            // are mirrors that this function reads from indirectly.
            var state = getViewState();
            var view = state.view;
            var detailLevel = state.detail;

            // Map asset-filter to fabric/sor parameters
            var fabricFilter = 'all';
            var sorFilter = 'all';
            if (view === 'sors') {{
                sorFilter = 'show';
            }} else if (view === 'fabrics') {{
                sorFilter = 'hide';
            }} else if (view !== 'all') {{
                fabricFilter = view;
            }}

            let url = '/api/topology/summary';
            if (detailLevel === 'all') {{
                url = '/api/topology';
            }} else if (fabricFilter !== 'all') {{
                url = `/api/topology/plane/${{fabricFilter}}`;
            }}

            const response = await fetch(url);
            if (!response.ok) throw new Error('Request failed: ' + response.status);
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

            allNodes = data.nodes.map(n => {{
                let bg = n.type === 'fabric_plane'
                    ? nodeColors.fabric_plane[n.metadata.plane_type] || '#64748b'
                    : nodeColors[n.type] || '#64748b';
                let borderWidth = 1;
                let isDeclared = n.metadata && n.metadata.origin === 'Declared';
                if (isDeclared) {{
                    bg = '#f59e0b';
                    borderWidth = 3;
                }}
                var isGreySource = n.type === 'source_system' && !isDeclared;
                var nodeColor = isDeclared
                    ? {{ background: bg, border: '#fbbf24',
                         highlight: {{ background: bg, border: '#22d3ee' }},
                         hover: {{ background: bg, border: '#94a3b8' }} }}
                    : {{ background: bg, border: '#475569',
                         highlight: {{ background: bg, border: '#22d3ee' }},
                         hover: {{ background: bg, border: '#94a3b8' }} }};
                var humanized = n.label.indexOf('\\n') >= 0
                    ? n.label.split('\\n').map(humanizeLabel).join('\\n')
                    : humanizeLabel(n.label);
                var node = {{
                    id: n.id,
                    label: humanized,
                    _rawLabel: n.label,
                    shape: isGreySource ? 'custom' : (nodeShapes[n.type] || 'dot'),
                    color: nodeColor,
                    borderWidth: borderWidth,
                    size: n.type === 'fabric_plane' ? 30 : (n.type === 'pipe' ? 20 : 15),
                    font: {{ color: '#ffffff', size: 12, face: 'Quicksand, sans-serif' }},
                    title: buildTooltip(n),
                    nodeData: n
                }};
                if (isGreySource) node.ctxRenderer = drawSourceNode;
                return node;
            }});

            allEdges = data.edges.map(e => ({{
                id: e.id,
                from: e.source,
                to: e.target,
                color: {{ color: '#64748b', opacity: 0.8 }},
                width: e.type === 'candidate_to_pipe' ? 2 : 1.5,
                dashes: e.type === 'candidate_for_source',
                arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }}
            }}));

            // Update sidebar stats — new instrumentation tiles
            if (data.stats) {{
                document.getElementById('stat-planes').textContent = data.stats.fabrics || 0;
                document.getElementById('stat-sors').textContent = data.stats.sors || 0;
                document.getElementById('stat-drift').textContent = data.stats.pipes_with_drift || 0;
            }}

            // Pipe count comes from /api/aam/pipes/count
            try {{
                var pcRes = await fetch('/api/aam/pipes/count');
                if (pcRes.ok) {{
                    var pc = await pcRes.json();
                    document.getElementById('stat-pipes').textContent = pc.count || 0;
                }}
            }} catch(e) {{}}

            // Health summary comes from /api/aam/health/summary
            try {{
                var hRes = await fetch('/api/aam/health/summary');
                if (hRes.ok) {{
                    var h = await hRes.json();
                    document.getElementById('health-reachable').textContent = h.reachable != null ? h.reachable : 0;
                    document.getElementById('health-degraded').textContent = h.degraded != null ? h.degraded : 0;
                    document.getElementById('health-unreachable').textContent = h.unreachable != null ? h.unreachable : 0;
                    document.getElementById('health-auth-expired').textContent = h.auth_expired != null ? h.auth_expired : 0;
                }}
            }} catch(e) {{}}

            renderNetwork();
        }}

        function drawSourceNode({{ctx, x, y, state: {{selected, hover}}, style, label}}) {{
            var sz = style.size;
            var r = 4;
            var fontSize = 12;
            var lineHeight = fontSize * 1.3;
            return {{
                drawNode: function() {{
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(x - sz + r, y - sz);
                    ctx.lineTo(x + sz - r, y - sz);
                    ctx.quadraticCurveTo(x + sz, y - sz, x + sz, y - sz + r);
                    ctx.lineTo(x + sz, y + sz - r);
                    ctx.quadraticCurveTo(x + sz, y + sz, x + sz - r, y + sz);
                    ctx.lineTo(x - sz + r, y + sz);
                    ctx.quadraticCurveTo(x - sz, y + sz, x - sz, y + sz - r);
                    ctx.lineTo(x - sz, y - sz + r);
                    ctx.quadraticCurveTo(x - sz, y - sz, x - sz + r, y - sz);
                    ctx.closePath();
                    var grad = ctx.createLinearGradient(x, y - sz, x, y + sz);
                    grad.addColorStop(0, '#1e293b');
                    grad.addColorStop(1, '#334155');
                    ctx.fillStyle = grad;
                    ctx.fill();
                    if (selected) {{
                        ctx.shadowColor = 'rgba(34, 211, 238, 0.5)';
                        ctx.shadowBlur = 15;
                        ctx.shadowOffsetX = 0;
                        ctx.shadowOffsetY = 0;
                    }}
                    ctx.strokeStyle = selected ? '#22d3ee' : (hover ? '#94a3b8' : '#475569');
                    ctx.lineWidth = selected ? 2.5 : 1.5;
                    ctx.stroke();
                    ctx.restore();
                    // Draw label
                    if (label) {{
                        ctx.save();
                        ctx.font = fontSize + 'px Quicksand, sans-serif';
                        ctx.fillStyle = '#ffffff';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'middle';
                        var lines = label.split('\\n');
                        var totalH = lines.length * lineHeight;
                        var startY = y + sz + 10 + lineHeight / 2;
                        for (var i = 0; i < lines.length; i++) {{
                            ctx.fillText(lines[i], x, startY + i * lineHeight);
                        }}
                        ctx.restore();
                    }}
                }},
                nodeDimensions: {{ width: sz * 2, height: sz * 2 }}
            }};
        }}

        function humanizeLabel(raw) {{
            var acronyms = ['AWS','API','SAP','ERP','CRM','HR','IT','UI','ID','IP','SQL','ETL','CSV','SSO','DCL','AAM','AOD','IOT'];
            return raw.split('_').map(function(w) {{
                var up = w.toUpperCase();
                if (acronyms.indexOf(up) >= 0) return up;
                return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
            }}).join(' ');
        }}

        function buildTooltip(node) {{
            var rawLabel = node._rawLabel || node.label;
            let lines = [rawLabel.replace('\\n', ' — ')];
            if (node.type === 'fabric_plane') {{
                if (node.metadata.vendor) lines.push('Vendor: ' + node.metadata.vendor);
                lines.push('Type: ' + (node.metadata.plane_type || 'unknown'));
                if (node.metadata.connected !== undefined) lines.push('Connected: ' + node.metadata.connected + ' / ' + node.metadata.total);
            }} else if (node.type === 'source_system') {{
                if (node.metadata.origin) lines.push('Origin: ' + node.metadata.origin);
                if (node.metadata.domain) lines.push('Domain: ' + node.metadata.domain);
                if (node.metadata.confidence) lines.push('Confidence: ' + node.metadata.confidence);
                if (node.metadata.category) lines.push('Category: ' + node.metadata.category);
                if (node.metadata.connected !== undefined) lines.push('Connected: ' + node.metadata.connected + ' / ' + node.metadata.total);
            }} else {{
                if (node.metadata.fabric_plane) lines.push('Plane: ' + node.metadata.fabric_plane);
                if (node.metadata.source_system) lines.push('Source: ' + node.metadata.source_system);
                if (node.metadata.category) lines.push('Category: ' + node.metadata.category);
                if (node.metadata.status) lines.push('Status: ' + node.metadata.status);
            }}
            return lines.join('\\n');
        }}

        function renderNetwork() {{
            const container = document.getElementById('topology-container');
            const data = {{
                nodes: new vis.DataSet(allNodes),
                edges: new vis.DataSet(allEdges)
            }};

            const options = getLayoutOptions();

            network = new vis.Network(container, data, options);

            // Fit viewport once physics stabilization finishes
            network.once('stabilizationIterationsDone', function() {{
                network.fit({{ animation: {{ duration: 400, easingFunction: 'easeInOutQuad' }} }});
            }});
            // Fallback for layouts with physics disabled (hierarchical)
            if (options.physics === false) {{
                network.once('afterDrawing', function() {{
                    network.fit({{ animation: false }});
                }});
            }}
            // When embedded in an iframe that starts hidden (display:none),
            // the container has zero dimensions and fit() has no effect.
            // Re-fit when the container first gets real dimensions.
            var _hasFittedAfterResize = false;
            var _resizeObserver = new ResizeObserver(function(entries) {{
                if (_hasFittedAfterResize) return;
                var entry = entries[0];
                if (entry && entry.contentRect.width > 0 && entry.contentRect.height > 0) {{
                    _hasFittedAfterResize = true;
                    network.redraw();
                    network.fit({{ animation: false }});
                }}
            }});
            _resizeObserver.observe(container);

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
                    shadow: true,
                    chosen: {{
                        node: function(values, id, selected, hovering) {{
                            if (selected) {{
                                values.shadowColor = 'rgba(34, 211, 238, 0.5)';
                                values.shadowSize = 15;
                                values.shadowX = 0;
                                values.shadowY = 0;
                            }}
                        }}
                    }}
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
            var typeLabel = humanizeLabel(node.nodeData.type);

            let html = `<div class="field"><div class="field-label">Type</div><div class="field-value">${{typeLabel}}</div></div>`;

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

        function filterNodesBySearch(query) {{
            var clearBtn = document.getElementById('topo-search-clear');
            clearBtn.style.display = query ? 'block' : 'none';
            if (!network) return;
            var q = query.toLowerCase().trim();
            var updates = allNodes.map(function(n) {{
                if (!q || n.label.toLowerCase().indexOf(q) >= 0) {{
                    return {{ id: n.id, opacity: 1.0 }};
                }} else {{
                    return {{ id: n.id, opacity: 0.15 }};
                }}
            }});
            network.body.data.nodes.update(updates);
        }}

        function clearNodeSearch() {{
            var input = document.getElementById('topo-search');
            input.value = '';
            filterNodesBySearch('');
            input.focus();
        }}

        function applyTopologyFilters() {{
            // Read from dropdowns, then push to URL state.
            // loadTopology() reads from URL state (single source of truth).
            var view = document.getElementById('asset-filter').value;
            var detail = document.getElementById('detail-filter').value;
            setViewState({{ view: view, detail: detail }});
            loadTopology();
        }}

        var _lastLayout = 'physics';
        function handleLayoutAction(val) {{
            const sel = document.getElementById('layout-select');
            if (val === '_fit') {{
                if (network) network.fit();
                sel.value = _lastLayout;
                return;
            }}
            if (val === '_unlock') {{
                togglePhysics();
                sel.value = _lastLayout;
                return;
            }}
            _lastLayout = val;
            setViewState({{ layout: val }});
            renderNetwork();
        }}

        function changeLayout() {{
            renderNetwork();
        }}

        function resetView() {{
            // Clear URL params, then reset dropdowns and reload
            history.replaceState(null, '', window.location.pathname);
            document.getElementById('asset-filter').value = 'all';
            document.getElementById('detail-filter').value = 'summary';
            document.getElementById('layout-select').value = 'physics';
            _lastLayout = 'physics';
            physicsEnabled = true;
            loadTopology();
        }}

        function fitToScreen() {{
            if (network) network.fit();
        }}

        function refreshData() {{
            applyTopologyFilters();
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

        function showToast(message, type) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast ' + type;
            toast.style.display = 'block';
            setTimeout(() => toast.style.display = 'none', 3000);
        }}

        // ────────────────────────────────────────────────────────
        // Action handlers
        // ────────────────────────────────────────────────────────

        document.getElementById('btn-run-inference').addEventListener('click', async function() {{
            var btn = this;
            btn.disabled = true;
            var orig = btn.textContent;
            btn.textContent = 'Inferring...';
            try {{
                var res = await fetch('/api/aam/infer', {{ method: 'POST' }});
                var data = await res.json().catch(function() {{ return {{}}; }});
                if (res.ok) {{
                    var msg = 'Inference complete — ' + (data.pipes_created || 0) + ' pipes created';
                    showToast(msg, 'success');
                    await loadTopology();
                }} else {{
                    showToast('Inference failed: ' + (data.detail || res.status), 'error');
                }}
            }} catch (e) {{
                showToast('Inference error: ' + e.message, 'error');
            }} finally {{
                btn.textContent = orig;
                btn.disabled = false;
            }}
        }});

        // ────────────────────────────────────────────────────────
        // Initialize — URL state aware, silent 60s background refresh (Fix 6)
        // ────────────────────────────────────────────────────────
        (function initFromUrl() {{
            var s = getViewState();
            var af = document.getElementById('asset-filter'); if (af) af.value = s.view;
            var df = document.getElementById('detail-filter'); if (df) df.value = s.detail;
            var ls = document.getElementById('layout-select'); if (ls) ls.value = s.layout;
            _lastLayout = s.layout;
        }})();
        loadTopology();
        refreshSidebarRun();
        setInterval(refreshSidebarRun, 10000);  // poll every 10s for external handoffs
    </script>
</body>
</html>
""")



@router.get("/ui/reconcile", response_class=HTMLResponse, include_in_schema=False)
async def ui_reconcile_latest():
    """Redirect to the latest reconciliation run."""
    logs = list_handoff_logs(limit=1)
    if not logs:
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html><head><title>AAM</title>{NAV_STYLE}</head>
<body>{ui_nav('reconcile')}
<div style="max-width:800px;margin:40px auto;padding:24px;text-align:center;color:#94a3b8;">
<h2>No Handoff Runs Found</h2>
<p style="margin-top:16px;">No AOD handoff data has been received yet. Send data from AOD first.</p>
<a href="/ui/handoff" class="btn" style="margin-top:24px;display:inline-block;padding:8px 20px;background:rgba(34,211,238,0.15);border:1px solid rgba(34,211,238,0.3);border-radius:6px;color:var(--cyan-400);text-decoration:none;">Go to Handoff</a>
</div></body></html>""", status_code=200)
    from starlette.responses import RedirectResponse
    return RedirectResponse(url=f"/ui/reconcile/{logs[0]['aod_run_id']}", status_code=302)


@router.get("/ui/reconcile/{aod_run_id}", response_class=HTMLResponse, include_in_schema=False)
async def ui_reconcile(aod_run_id: str):
    """Reconciliation UI - human-readable view of AOD handoff reconciliation"""
    data = get_aod_reconciliation(aod_run_id)
    
    if data.get("error"):
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>AAM</title>
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
    snapshot = data.get("entity_id") or data.get("snapshot_name") or ""
    timestamp = data.get("handoff_timestamp", "")[:19] if data.get("handoff_timestamp") else "N/A"
    
    # Overall status
    all_match = recon["candidates_match"]
    status_color = "var(--green-400)" if all_match else "var(--red-400)"
    status_icon = "&#10003;" if all_match else "&#10007;"
    status_text = "All Reconciled" if all_match else "Discrepancy Detected"
    
    # Fabric plane bars
    fabric_types = ALL_PLANE_TYPES
    fabric_colors = {
        "API_GATEWAY": "var(--cyan-400)",
        "DATA_WAREHOUSE": "var(--blue-400)",
        "IPAAS": "var(--purple-400)",
        "EVENT_BUS": "var(--orange-400)",
    }
    fabric_labels = PLANE_TYPE_LABELS
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
    from ..constants import SOR_CATEGORIES as sor_categories
    cat_colors = SOR_CATEGORY_COLORS
    
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
    
    checks_html = check_row("AOD Candidates Stored", aod_sent["candidates_accepted"], aam.get("aod_origin_candidates", aam["candidates"]), recon["candidates_match"])
    
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
    
    # --- Deep Check 3: Fabric Plane Comparison ---
    fc = deep.get("fabric_comparison", {})
    fc_vendors = fc.get("vendors", [])
    fc_mismatches = fc.get("mismatches", 0)
    has_aod_fabric = fc.get("has_aod_data", False)
    fc_only_aod = fc.get("only_in_aod", [])
    fc_only_aam = fc.get("only_in_aam", [])
    fc_in_both = fc.get("in_both", [])
    
    plane_labels = PLANE_TYPE_SHORT
    
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
        fc_content += '<div style="color: #fcd34d; font-size: 0.85rem; margin-bottom: 12px; padding: 8px; background: rgba(251,191,36,0.05); border: 1px solid rgba(251,191,36,0.2); border-radius: 6px;">AOD did not send fabric planes in this handoff. Fabric-plane comparison is unavailable until AOD provides plane declarations.</div>'
    
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
                        <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Linked</th>
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
            
            linked = v.get("linked_candidates", 0)
            if status == "match":
                status_html = '<span style="color: var(--green-400);">&#10003; Match</span>'
                row_bg = "rgba(34,197,94,0.03)"
            elif status == "match_empty":
                status_html = '<span style="color: #fcd34d;">&#9888; 0 candidates</span>'
                row_bg = "rgba(251,191,36,0.03)"
            elif status == "type_mismatch":
                status_html = '<span style="color: #fcd34d;">&#9888; Type differs</span>'
                row_bg = "rgba(251,191,36,0.03)"
            elif status == "only_aod":
                status_html = '<span style="color: #fca5a5;">Missing in AAM</span>'
                row_bg = "rgba(248,113,113,0.03)"
            else:
                status_html = '<span style="color: #93c5fd;">Extra in AAM</span>'
                row_bg = "rgba(147,197,253,0.03)"

            linked_color = "var(--green-400)" if linked > 0 else "#fca5a5"
            aod_cell = f'<span style="color: #a5b4fc;">{aod_type}</span>' if v.get("aod_plane_type") else '<span style="color: var(--slate-600);">-</span>'
            aam_cell = f'<span style="color: #86efac;">{aam_type}</span>' if v.get("aam_plane_type") else '<span style="color: var(--slate-600);">-</span>'

            fc_content += f"""
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: {row_bg};">
                        <td style="padding: 8px; font-weight: 500; color: #e2e8f0;">{vendor_name}</td>
                        <td style="padding: 8px; text-align: center;">{aod_cell}</td>
                        <td style="padding: 8px; text-align: center;">{aam_cell}</td>
                        <td style="padding: 8px; text-align: center; color: {linked_color}; font-weight: 600;">{linked}</td>
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
    
    # --- Deep Check 3b: SOR Line-Item Ingestion/Classification ---
    sc_sor = deep.get("sor_comparison", {})
    sor_line_items = sc_sor.get("line_items", [])
    sor_mismatches = sc_sor.get("mismatches", 0)
    has_aod_sor = sc_sor.get("has_aod_data", False)
    sor_all_ok = sc_sor.get("all_ok", False)
    sor_accuracy = sc_sor.get("ingestion_accuracy", 0)
    sor_total = sc_sor.get("total_sors", 0)
    sor_matched_count = sc_sor.get("matched", 0)
    sor_cat_mismatches = sc_sor.get("category_mismatches", 0)
    sor_missing_count = sc_sor.get("missing", 0)
    
    cat_labels_sor = SOR_CATEGORY_LABELS
    
    sor_undispositioned = sc_sor.get("undispositioned", 0)
    
    sor_content = ""
    
    if not has_aod_sor:
        sor_content += '<div style="color: var(--slate-400); font-size: 0.85rem; margin-bottom: 12px; padding: 8px; background: rgba(255,255,255,0.02); border-radius: 6px;">No SOR declarations found for this run. SORs are declared via AOD handoff.</div>'
    else:
        # Accuracy bar
        acc_color = "var(--green-400)" if sor_accuracy >= 80 else ("var(--orange-400)" if sor_accuracy >= 50 else "var(--red-400)")
        if sor_all_ok:
            verdict_text = "All SORs ingested and classified correctly"
        elif sor_undispositioned == 0 and sor_mismatches > 0:
            verdict_text = f"{sor_matched_count} of {sor_total} SORs verified &mdash; all issues dispositioned"
        else:
            verdict_text = f"{sor_matched_count} of {sor_total} SORs verified"
        verdict_color = "var(--green-400)" if (sor_all_ok or sor_undispositioned == 0) else "var(--orange-400)"
        
        sor_content += f"""
        <div style="margin-bottom: 16px; padding: 12px; background: {'rgba(34,197,94,0.06)' if (sor_all_ok or sor_undispositioned == 0) else 'rgba(251,191,36,0.06)'}; border: 1px solid {'rgba(34,197,94,0.2)' if (sor_all_ok or sor_undispositioned == 0) else 'rgba(251,191,36,0.2)'}; border-radius: 8px;">
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;">
                <div>
                    <span style="color: {verdict_color}; font-size: 1.1rem; margin-right: 6px;">{'&#10003;' if (sor_all_ok or sor_undispositioned == 0) else '&#9888;'}</span>
                    <span style="font-weight: 600; color: {verdict_color};">{verdict_text}</span>
                </div>
                <div style="display: flex; gap: 16px; font-size: 0.8rem;">
                    <span style="color: var(--green-400);">{sor_matched_count} OK</span>
                    {'<span style="color: var(--orange-400);">' + str(sor_cat_mismatches) + ' Category Mismatch</span>' if sor_cat_mismatches > 0 else ''}
                    {'<span style="color: var(--red-400);">' + str(sor_missing_count) + ' Not Ingested</span>' if sor_missing_count > 0 else ''}
                    {'<span style="color: var(--slate-400);">' + str(sor_undispositioned) + ' need disposition</span>' if sor_undispositioned > 0 else ''}
                </div>
            </div>
            <div style="margin-top: 8px;">
                <div style="height: 6px; background: var(--slate-800); border-radius: 3px; overflow: hidden;">
                    <div style="height: 100%; width: {sor_accuracy}%; background: {acc_color}; border-radius: 3px;"></div>
                </div>
                <div style="font-size: 0.75rem; color: var(--slate-400); margin-top: 4px;">Ingestion accuracy: {sor_accuracy}%</div>
            </div>
        </div>
        """
        
        disp_labels = {
            "acknowledged": ("Acknowledged", "#a5b4fc", "rgba(99,102,241,0.15)"),
            "expected": ("Expected", "#86efac", "rgba(34,197,94,0.15)"),
            "follow_up": ("Follow Up", "#fcd34d", "rgba(251,191,36,0.15)"),
            "resolved": ("Resolved", "#86efac", "rgba(34,197,94,0.15)"),
        }
        
        # Line-item table
        sor_content += """
        <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
            <thead>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                    <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Source</th>
                    <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Domain</th>
                    <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Vendor</th>
                    <th style="text-align: center; padding: 8px; color: #a5b4fc; font-weight: 500;">Expected</th>
                    <th style="text-align: center; padding: 8px; color: #86efac; font-weight: 500;">AAM Found</th>
                    <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Candidates</th>
                    <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Verdict</th>
                    <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Disposition</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for item in sor_line_items:
            vendor_name = item["vendor"]
            vendor_enc = vendor_name.replace("'", "\\'").replace('"', '&quot;')
            domain = item.get("domain", "") or ""
            expected = cat_labels_sor.get(item["expected_category"], item["expected_category"].upper() if item["expected_category"] else "-")
            aam_cat = cat_labels_sor.get(item.get("aam_category", ""), (item.get("aam_category") or "-").upper())
            aam_count = item.get("aam_count", 0)
            verdict = item["verdict"]
            source = item.get("source", "")
            disposition = item.get("disposition")
            disp_notes = item.get("disposition_notes") or ""
            
            source_badge = ""
            if source == "farm":
                source_badge = '<span style="background: rgba(251,191,36,0.15); color: #fbbf24; padding: 2px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 600;">Declared</span>'
            else:
                source_badge = '<span style="background: rgba(99,102,241,0.15); color: #a5b4fc; padding: 2px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 500;">Inferred</span>'
            
            if verdict == "ok":
                verdict_html = '<span style="color: var(--green-400);">&#10003; OK</span>'
                row_bg = "rgba(34,197,94,0.03)"
                aam_cat_html = f'<span style="color: #86efac;">{aam_cat}</span>'
            elif verdict == "category_mismatch":
                verdict_html = '<span style="color: var(--orange-400);">&#9888; Category</span>'
                row_bg = "rgba(251,191,36,0.03)"
                aam_cat_html = f'<span style="color: #fcd34d;">{aam_cat}</span>'
            else:
                verdict_html = '<span style="color: var(--red-400);">&#10007; Missing</span>'
                row_bg = "rgba(248,113,113,0.03)"
                aam_cat_html = '<span style="color: var(--slate-600);">-</span>'
            
            expected_html = f'<span style="color: #a5b4fc;">{expected}</span>'
            count_html = f'<span style="color: #86efac;">{aam_count}</span>' if aam_count > 0 else '<span style="color: var(--slate-600);">0</span>'
            
            # Disposition cell
            disp_cell = ""
            if verdict == "ok":
                disp_cell = '<span style="color: var(--slate-600); font-size: 0.75rem;">-</span>'
            elif disposition:
                dl = disp_labels.get(disposition, (disposition, "#94a3b8", "rgba(148,163,184,0.15)"))
                title_attr = f' title="{disp_notes}"' if disp_notes else ''
                disp_cell = f'<span data-testid="disp-badge-{vendor_name}" style="background: {dl[2]}; color: {dl[1]}; padding: 2px 8px; border-radius: 3px; font-size: 0.7rem; font-weight: 500; cursor: default;"{title_attr}>{dl[0]}</span>'
                disp_cell += f' <button data-testid="disp-clear-{vendor_name}" onclick="setSorDisp(\'{vendor_enc}\', \'open\', \'\')" style="background: none; border: none; color: var(--slate-500); cursor: pointer; font-size: 0.7rem; padding: 2px;" title="Clear disposition">&#10005;</button>'
            else:
                disp_cell = f"""<select data-testid="disp-select-{vendor_name}" onchange="setSorDisp('{vendor_enc}', this.value, '')" style="background: var(--slate-800); color: #e2e8f0; border: 1px solid var(--slate-600); border-radius: 4px; padding: 2px 4px; font-size: 0.7rem; cursor: pointer;">
                    <option value="">Action...</option>
                    <option value="acknowledged">Acknowledged</option>
                    <option value="expected">Expected</option>
                    <option value="follow_up">Follow Up</option>
                    <option value="resolved">Resolved</option>
                </select>"""
            
            sor_content += f"""
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: {row_bg};">
                    <td style="padding: 8px;">{source_badge}</td>
                    <td style="padding: 8px; color: #cbd5e1; font-size: 0.8rem;">{domain}</td>
                    <td style="padding: 8px; font-weight: 500; color: #e2e8f0;">{vendor_name}</td>
                    <td style="padding: 8px; text-align: center;">{expected_html}</td>
                    <td style="padding: 8px; text-align: center;">{aam_cat_html}</td>
                    <td style="padding: 8px; text-align: center;">{count_html}</td>
                    <td style="padding: 8px; text-align: center; font-size: 0.8rem;">{verdict_html}</td>
                    <td style="padding: 8px; text-align: center;">{disp_cell}</td>
                </tr>
            """
        
        sor_content += """
            </tbody>
        </table>
        """
    
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
            <span style="font-size: 0.85rem; color: #cbd5e1;">AOD Data Completeness</span>
            <span style="font-size: 0.85rem; font-weight: 600; color: {sc_bar_color};">{sc_score}%</span>
        </div>
        <div style="height: 8px; background: var(--slate-800); border-radius: 4px; overflow: hidden;">
            <div style="height: 100%; width: {sc_score}%; background: {sc_bar_color}; border-radius: 4px;"></div>
        </div>
        <div style="font-size: 0.8rem; color: var(--slate-400); margin-top: 4px;">{sc.get("incomplete_count", 0)} of {sc_total} candidates missing AOD-provided fields</div>
    </div>
    """
    
    aod_fields = {"vendor_name", "display_name", "category", "known_endpoints", "connected_via_plane"}
    enrichment_fields = {"preferred_modality"}
    
    if sc_field_counts:
        field_labels = {
            "vendor_name": "Vendor Name",
            "display_name": "Display Name",
            "category": "Category",
            "known_endpoints": "Endpoints",
            "preferred_modality": "Modality",
            "connected_via_plane": "Fabric Plane"
        }
        
        aod_missing = {f: c for f, c in sc_field_counts.items() if f in aod_fields and c > 0}
        enrich_missing = {f: c for f, c in sc_field_counts.items() if f in enrichment_fields and c > 0}
        
        if aod_missing:
            max_aod = max(aod_missing.values()) if aod_missing else 1
            sc_content += '<div style="font-size: 0.8rem; font-weight: 500; color: var(--orange-400); margin-bottom: 8px;">AOD Data Quality Issues</div>'
            for field, count in sorted(aod_missing.items(), key=lambda x: -x[1]):
                pct = int((count / max(max_aod, 1)) * 100)
                label = field_labels.get(field, field)
                sc_content += f"""
                <div style="margin-bottom: 6px;">
                    <div style="display: flex; justify-content: space-between; gap: 8px; margin-bottom: 2px;">
                        <span style="font-size: 0.8rem; color: #cbd5e1;">{label}</span>
                        <span style="font-size: 0.8rem; color: var(--orange-400);">{count} missing</span>
                    </div>
                    <div style="height: 4px; background: var(--slate-800); border-radius: 2px; overflow: hidden;">
                        <div style="height: 100%; width: {pct}%; background: var(--orange-400); border-radius: 2px;"></div>
                    </div>
                </div>
                """
        elif not aod_missing:
            sc_content += '<div style="color: var(--green-400); font-size: 0.8rem; margin-bottom: 12px;">All AOD-provided fields are complete.</div>'
        
        if enrich_missing:
            sc_content += '<div style="font-size: 0.8rem; font-weight: 500; color: var(--slate-400); margin-top: 12px; margin-bottom: 8px;">AAM Enrichment Fields (not from AOD - expected to be empty)</div>'
            for field, count in sorted(enrich_missing.items(), key=lambda x: -x[1]):
                label = field_labels.get(field, field)
                sc_content += f"""
                <div style="margin-bottom: 4px; display: flex; justify-content: space-between; gap: 8px;">
                    <span style="font-size: 0.8rem; color: var(--slate-500);">{label}</span>
                    <span style="font-size: 0.8rem; color: var(--slate-500);">{count} pending</span>
                </div>
                """
            sc_content += '<div style="font-size: 0.75rem; color: var(--slate-500); margin-top: 4px; font-style: italic;">These fields are populated during operator assignment or inference, not by AOD.</div>'
    
    # --- Deep Check 5: Pipe Schema Content ---
    ps = deep.get("pipe_schema_content", {})
    ps_total = ps.get("total_pipes", 0)
    ps_with = ps.get("pipes_with_fields", 0)
    ps_without = ps.get("pipes_without_fields", 0)
    ps_coverage = ps.get("field_coverage_pct", 0)
    ps_by_source = ps.get("by_source", {})
    ps_missing = ps.get("missing_pipes", [])

    ps_bar_color = "var(--green-400)" if ps_coverage >= 80 else ("var(--orange-400)" if ps_coverage >= 50 else "var(--red-400)")

    ps_content = ""
    if ps_total == 0:
        ps_content = '<div style="color: var(--slate-400); font-size: 0.85rem;">No declared pipes found for this run. Run inference first (POST /api/aam/infer).</div>'
    else:
        ps_content += f"""
        <div style="margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; gap: 8px; margin-bottom: 4px;">
                <span style="font-size: 0.85rem; color: #cbd5e1;">Pipe Field Coverage</span>
                <span style="font-size: 0.85rem; font-weight: 600; color: {ps_bar_color};">{ps_coverage}%</span>
            </div>
            <div style="height: 8px; background: var(--slate-800); border-radius: 4px; overflow: hidden;">
                <div style="height: 100%; width: {ps_coverage}%; background: {ps_bar_color}; border-radius: 4px;"></div>
            </div>
            <div style="font-size: 0.8rem; color: var(--slate-400); margin-top: 4px;">
                <span style="color: var(--green-400); font-weight: 600;">{ps_with}</span> of {ps_total} pipes have entity_scope, identity_keys, and schema_info populated
            </div>
        </div>
        """

        if ps_by_source:
            source_labels = {
                "category_inferred": "Category Inferred",
                "observation": "Live Observation",
                "present": "Present",
                "unknown": "Unknown Source",
            }
            ps_content += '<div style="font-size: 0.8rem; font-weight: 500; color: #cbd5e1; margin-bottom: 8px;">Field Resolution Source</div>'
            ps_content += '<div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px;">'
            source_colors = {
                "category_inferred": ("#a5b4fc", "rgba(99,102,241,0.15)"),
                "observation": ("#86efac", "rgba(34,197,94,0.15)"),
            }
            for src, count in sorted(ps_by_source.items(), key=lambda x: -x[1]):
                label = source_labels.get(src, src.replace("_", " ").title())
                colors = source_colors.get(src, ("#cbd5e1", "rgba(255,255,255,0.05)"))
                ps_content += f'<span style="background: {colors[1]}; color: {colors[0]}; padding: 3px 10px; border-radius: 4px; font-size: 0.8rem;">{label}: {count}</span>'
            ps_content += '</div>'

        if ps_missing:
            ps_content += f"""
            <div style="font-size: 0.8rem; font-weight: 500; color: var(--orange-400); margin-bottom: 8px;">Pipes Missing Schema Content ({ps_without})</div>
            <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
                <thead>
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                        <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Vendor</th>
                        <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Display Name</th>
                        <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Entity Scope</th>
                        <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Identity Keys</th>
                        <th style="text-align: center; padding: 8px; color: var(--slate-400); font-weight: 500;">Schema Info</th>
                    </tr>
                </thead>
                <tbody>
            """
            for mp in ps_missing:
                es_count = mp.get("entity_scope_count", 0)
                ik_count = mp.get("identity_keys_count", 0)
                has_si = mp.get("has_schema_info", False)
                es_cell = f'<span style="color: var(--green-400);">{es_count}</span>' if es_count > 0 else '<span style="color: var(--red-400);">0</span>'
                ik_cell = f'<span style="color: var(--green-400);">{ik_count}</span>' if ik_count > 0 else '<span style="color: var(--red-400);">0</span>'
                si_cell = '<span style="color: var(--green-400);">&#10003;</span>' if has_si else '<span style="color: var(--red-400);">&#10007;</span>'
                ps_content += f"""
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                        <td style="padding: 8px; font-weight: 500; color: #e2e8f0;">{mp.get("vendor", "")}</td>
                        <td style="padding: 8px; color: #cbd5e1;">{mp.get("display_name", "")}</td>
                        <td style="padding: 8px; text-align: center;">{es_cell}</td>
                        <td style="padding: 8px; text-align: center;">{ik_cell}</td>
                        <td style="padding: 8px; text-align: center;">{si_cell}</td>
                    </tr>
                """
            ps_content += """
                </tbody>
            </table>
            """

    # --- Deep Check 6: Duplicate Detection ---
    dd = deep.get("duplicates", {})
    dd_groups = dd.get("duplicate_groups", [])
    dd_total = dd.get("total_duplicate_rows", 0)

    # --- Deep Check 7: DCL Export Reconciliation ---
    from ..dcl_export import build_dcl_export
    try:
        dcl_export = build_dcl_export(aod_run_id)
        dcl_exported = dcl_export.total_connections
        dcl_skipped = dcl_export.skipped_connections
        dcl_skipped_count = dcl_export.skipped_count
        dcl_snapshot = dcl_export.entity_id or dcl_export.snapshot_name
        dcl_aod_run = dcl_export.aod_run_id
    except Exception as exc:
        _log.error("Failed to build DCL export for deep check: %s", exc)
        dcl_exported = 0
        dcl_skipped = []
        dcl_skipped_count = 0
        dcl_snapshot = None
        dcl_aod_run = None

    total_candidates_for_export = aam["candidates"]
    dcl_pending_inference = len([s for s in dcl_skipped if s.reason == "pending_inference"])
    dcl_duplicates = len([s for s in dcl_skipped if s.reason == "duplicate_pipe_id"])
    dcl_total_accounted = dcl_exported + dcl_skipped_count
    dcl_all_ok = dcl_exported > 0 and dcl_pending_inference == 0

    dcl_content = ""
    # Summary bar
    if total_candidates_for_export > 0:
        export_pct = int((dcl_exported / total_candidates_for_export) * 100)
    else:
        export_pct = 0
    export_bar_color = "var(--green-400)" if export_pct >= 80 else ("var(--orange-400)" if export_pct >= 50 else "var(--red-400)")

    dcl_content += f"""
    <div style="margin-bottom: 16px; padding: 12px; background: {'rgba(34,197,94,0.06)' if dcl_all_ok else 'rgba(251,191,36,0.06)'}; border: 1px solid {'rgba(34,197,94,0.2)' if dcl_all_ok else 'rgba(251,191,36,0.2)'}; border-radius: 8px;">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;">
            <div>
                <span style="color: {'var(--green-400)' if dcl_all_ok else 'var(--orange-400)'}; font-size: 1.1rem; margin-right: 6px;">{'&#10003;' if dcl_all_ok else '&#9888;'}</span>
                <span style="font-weight: 600; color: {'var(--green-400)' if dcl_all_ok else 'var(--orange-400)'};">
                    {'All candidates exported' if dcl_all_ok else f'{dcl_exported} of {total_candidates_for_export} candidates exported to DCL'}
                </span>
            </div>
            <div style="display: flex; gap: 16px; font-size: 0.8rem;">
                <span style="color: var(--green-400);">{dcl_exported} exported</span>
                {'<span style="color: var(--orange-400);">' + str(dcl_duplicates) + ' deduplicated</span>' if dcl_duplicates > 0 else ''}
                {'<span style="color: var(--red-400);">' + str(dcl_pending_inference) + ' pending inference</span>' if dcl_pending_inference > 0 else ''}
            </div>
        </div>
        <div style="margin-top: 8px;">
            <div style="height: 6px; background: var(--slate-800); border-radius: 3px; overflow: hidden;">
                <div style="height: 100%; width: {export_pct}%; background: {export_bar_color}; border-radius: 3px;"></div>
            </div>
            <div style="font-size: 0.75rem; color: var(--slate-400); margin-top: 4px;">Export coverage: {export_pct}% &mdash; {dcl_total_accounted} accounted for</div>
        </div>
    </div>
    """

    # Provenance
    if dcl_snapshot or dcl_aod_run:
        dcl_content += f"""
        <div style="display: flex; gap: 16px; flex-wrap: wrap; font-size: 0.8rem; color: var(--slate-400); margin-bottom: 16px;">
            {'<div><strong style="color: #cbd5e1;">Snapshot:</strong> <span style="color: #f0abfc;">' + (dcl_snapshot or '-') + '</span></div>' if dcl_snapshot else ''}
            {'<div><strong style="color: #cbd5e1;">AOD Run:</strong> <span style="font-family: monospace;">' + (dcl_aod_run or '-') + '</span></div>' if dcl_aod_run else ''}
        </div>
        """

    # Waterfall: Candidates → Exported + Skipped
    dcl_content += f"""
    <div style="margin-bottom: 16px;">
        <div style="font-size: 0.8rem; font-weight: 500; color: #cbd5e1; margin-bottom: 8px;">Pipeline Waterfall</div>
        <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
            <thead>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                    <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Stage</th>
                    <th style="text-align: right; padding: 8px; color: var(--slate-400); font-weight: 500;">Count</th>
                    <th style="text-align: left; padding: 8px; color: var(--slate-400); font-weight: 500;">Description</th>
                </tr>
            </thead>
            <tbody>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                    <td style="padding: 8px; font-weight: 500; color: #e2e8f0;">AOD Candidates Stored</td>
                    <td style="padding: 8px; text-align: right; font-weight: 600; color: var(--cyan-400);">{total_candidates_for_export}</td>
                    <td style="padding: 8px; color: var(--slate-400);">Total candidates from AOD handoff</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: rgba(34,197,94,0.03);">
                    <td style="padding: 8px; font-weight: 500; color: #86efac;">Exported to DCL</td>
                    <td style="padding: 8px; text-align: right; font-weight: 600; color: var(--green-400);">{dcl_exported}</td>
                    <td style="padding: 8px; color: var(--slate-400);">Unique pipes with matched_pipe_id sent to DCL</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: rgba(251,191,36,0.03);">
                    <td style="padding: 8px; font-weight: 500; color: #fcd34d;">Deduplicated</td>
                    <td style="padding: 8px; text-align: right; font-weight: 600; color: var(--orange-400);">{dcl_duplicates}</td>
                    <td style="padding: 8px; color: var(--slate-400);">Multiple candidates mapped to same pipe_id (kept most recent)</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); background: rgba(248,113,113,0.03);">
                    <td style="padding: 8px; font-weight: 500; color: #fca5a5;">Pending Inference</td>
                    <td style="padding: 8px; text-align: right; font-weight: 600; color: var(--red-400);">{dcl_pending_inference}</td>
                    <td style="padding: 8px; color: var(--slate-400);">Candidates without matched_pipe_id (inference not yet run or no match)</td>
                </tr>
            </tbody>
        </table>
    </div>
    """

    # Skipped details (show first few if many)
    if dcl_skipped and dcl_duplicates > 0:
        dup_items = [s for s in dcl_skipped if s.reason == "duplicate_pipe_id"]
        dcl_content += f"""
        <div style="margin-top: 12px;">
            <div style="font-size: 0.8rem; font-weight: 500; color: var(--orange-400); margin-bottom: 8px;">Deduplicated Candidates ({dcl_duplicates})</div>
            <div style="display: flex; flex-wrap: wrap; gap: 4px;">
        """
        for s in dup_items[:20]:
            dcl_content += f'<span style="display: inline-block; background: rgba(251,191,36,0.1); border: 1px solid rgba(251,191,36,0.2); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; color: #fcd34d;">{s.vendor}</span>'
        if dcl_duplicates > 20:
            dcl_content += f'<span style="font-size: 0.75rem; color: var(--slate-500);">+{dcl_duplicates - 20} more</span>'
        dcl_content += "</div></div>"
    
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
    <title>AAM</title>
    {NAV_STYLE}
    {UI_STYLE}
    <style>
        .recon-header {{
            display: flex;
            align-items: baseline;
            gap: 16px;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }}
        .recon-header h1 {{
            margin: 0;
        }}
        .recon-status {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.85rem;
        }}
        .recon-meta {{
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            align-items: center;
            color: var(--slate-400);
            font-size: 0.8rem;
            margin-bottom: 20px;
        }}
        .recon-meta strong {{
            color: #cbd5e1;
        }}
        .recon-meta .inline-kpi {{
            display: flex;
            gap: 12px;
            margin-left: auto;
        }}
        .recon-meta .inline-kpi .kpi {{
            color: var(--slate-400);
        }}
        .recon-meta .inline-kpi .kpi span {{
            font-weight: 600;
        }}
        .deep-check {{
            margin-bottom: 24px;
        }}
    </style>
</head>
<body>
    {ui_nav('reconcile')}
    <div class="container">
        <div class="recon-header">
            <h1>Reconciliation</h1>
            <div class="recon-status" style="background: {overall_bg_color}; border: {overall_border}; color: {overall_color};">
                <span>{overall_icon}</span>
                {overall_text}
            </div>
        </div>
        
        <div class="recon-meta">
            {'<div><strong>Snapshot:</strong> <span style="color: #f0abfc;">' + snapshot + '</span></div>' if snapshot else ''}
            <div><strong>Run:</strong> <span style="font-family: monospace;">{aod_run_id[:12]}</span></div>
            <div><strong>At:</strong> {timestamp}</div>
            <div class="inline-kpi">
                <div class="kpi"><span style="color: var(--cyan-400);">{aod_sent["candidates_accepted"]}</span> sent</div>
                <div class="kpi"><span style="color: var(--green-400);">{aam["candidates"]}</span> stored</div>
                <div class="kpi"><span style="color: var(--purple-400);">{aam["fabric_planes"]}</span> fabrics</div>
                <div class="kpi"><span style="color: var(--blue-400);">{aam["sors"]}</span> SORs</div>
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
        <p class="page-subtitle" style="margin-top: -8px;">Detailed data quality analysis across 7 dimensions</p>

        <!-- Check 1: Vendor Matching -->
        <div class="deep-check">
            <div class="panel" data-testid="check-vendor-matching">
                {check_header("Vendor Name Consistency", vm.get("has_issues", False), len(vm_issues), "Detects case-sensitivity duplicates across vendor names")}
                {vm_content}
            </div>
        </div>

        <!-- Check 2: Fabric Plane Comparison -->
        <div class="deep-check">
            <div class="panel" data-testid="check-fabric-comparison">
                {check_header("Fabric Plane Comparison", fc.get("has_issues", False), fc_mismatches, "Compares AOD-explicit fabric planes vs AAM-stored planes for this run")}
                {fc_content}
            </div>
        </div>

        <!-- Check 3b: SOR Ingestion/Classification -->
        <div class="deep-check">
            <div class="panel" data-testid="check-sor-comparison">
                {check_header("SOR Ingestion &amp; Classification", sc_sor.get("has_issues", False), sor_mismatches, "Line-item check: each SOR declaration matched against AAM candidates for vendor ingestion and category accuracy")}
                {sor_content}
            </div>
        </div>

        <!-- Check 4: Schema Completeness -->
        <div class="deep-check">
            <div class="panel" data-testid="check-schema-completeness">
                {check_header("Schema Completeness", sc.get("has_issues", False), sc.get("incomplete_count", 0) if sc.get("has_issues") else 0, "Checks for missing vendor_name, display_name, or category")}
                {sc_content}
            </div>
        </div>

        <!-- Check 5: Pipe Schema Content -->
        <div class="deep-check">
            <div class="panel" data-testid="check-pipe-schema-content">
                {check_header("Pipe Schema Content", ps.get("has_issues", False), ps_without, "Validates that declared pipes have entity_scope, identity_keys, and schema_info populated for DCL export")}
                {ps_content}
            </div>
        </div>

        <!-- Check 6: Duplicate Detection -->
        <div class="deep-check">
            <div class="panel" data-testid="check-duplicates">
                {check_header("Duplicate Detection", dd.get("has_issues", False), dd.get("total_groups", 0), "Finds candidates with identical vendor + display name combinations")}
                {dd_content}
            </div>
        </div>

        <!-- Check 7: DCL Export Reconciliation -->
        <div class="deep-check">
            <div class="panel" data-testid="check-dcl-export">
                {check_header("DCL Export Reconciliation", dcl_pending_inference > 0, dcl_pending_inference, "Traces candidates through export pipeline: stored → inferred → exported to DCL")}
                {dcl_content}
            </div>
        </div>

        <div style="text-align: center; margin-top: 24px; padding-bottom: 32px;">
            <a href="/ui/pipes" class="btn" data-testid="link-back-pipes" style="margin-right: 8px;">Back to Pipes</a>
            <a href="/api/handoff/aod/run/{aod_run_id}/reconciliation/download" class="btn btn-sm" data-testid="link-download-csv" style="margin-right: 8px; color: var(--cyan-400); border-color: rgba(34,211,238,0.3);">Download CSV</a>
            <a href="/api/handoff/aod/run/{aod_run_id}/reconciliation/download-json" class="btn btn-sm" data-testid="link-download-json" style="margin-right: 8px; color: var(--cyan-400); border-color: rgba(34,211,238,0.3);">Download JSON</a>
            <a href="/api/handoff/aod/run/{aod_run_id}/reconciliation" target="_blank" class="btn btn-sm" data-testid="link-raw-json" style="color: var(--slate-400); border-color: var(--slate-600);">View Raw JSON</a>
        </div>
    </div>
    <script>
    function setSorDisp(vendor, status, notes) {{
        fetch('/api/handoff/aod/run/{aod_run_id}/sor/' + encodeURIComponent(vendor) + '/disposition', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{status: status, operator_notes: notes || ''}})
        }})
        .then(r => {{
            if (!r.ok) throw new Error('Request failed: ' + r.status);
            return r.json();
        }})
        .then(() => location.reload())
        .catch(e => alert('Error setting disposition: ' + e));
    }}
    </script>
</body>
</html>
""")
