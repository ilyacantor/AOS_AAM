"""
AAM Operator UI Pages — HTML rendering routes.

These routes render the operator-facing UI using inline HTML templates.
Extracted from the monolithic main.py for separation of concerns.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import datetime

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
)

router = APIRouter(include_in_schema=False)

@router.get("/ui/pipes", response_class=HTMLResponse, include_in_schema=False)
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
        rows_html = '<tr><td colspan="8" class="empty-state">No pipes found. Fetch AOD data and run inference to create pipes from candidates.</td></tr>'
    
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
        <h1>Pipes</h1>
        <p class="page-subtitle">All declared data pipes with metadata, health status, and ownership. These are your canonical integration endpoints.</p>
        
        {aod_run_banner(extra_buttons='<button class="btn btn-sm" style="font-size: 0.75rem;" id="btn-run-inference" data-testid="btn-run-inference">Run Inference</button><button class="btn btn-sm" style="font-size: 0.75rem;" id="btn-export-dcl" data-testid="btn-export-dcl">Export to DCL</button>')}
        
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
        
        document.getElementById('btn-run-inference').addEventListener('click', async function() {{
            this.disabled = true;
            this.textContent = 'Running...';
            try {{
                const res = await fetch('/api/aam/infer', {{ method: 'POST' }});
                const data = await res.json();
                if (res.ok) {{
                    showToast('Inference complete: ' + data.pipes_created + ' pipes created', 'success');
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    showToast('Error: ' + (data.detail || 'Failed'), 'error');
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message, 'error');
            }}
            this.disabled = false;
            this.textContent = 'Run Inference';
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


@router.get("/ui/pipes/{pipe_id}", response_class=HTMLResponse, include_in_schema=False)
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


@router.get("/ui/candidates", response_class=HTMLResponse, include_in_schema=False)
async def ui_candidates_list(
    view: Optional[str] = Query("sors_fabrics", description="View filter: all, sors, fabrics, sors_fabrics, ipaas, warehouse, gateway, eventbus")
):
    """Candidates Screen"""
    all_candidates = list_candidates()
    
    from ..constants import SOR_CATEGORIES as sor_categories

    # Resolve a candidate's fabric plane TYPE from its linkage or routing hint
    _plane_view_map = {
        "ipaas": "IPAAS", "warehouse": "DATA_WAREHOUSE",
        "gateway": "API_GATEWAY", "eventbus": "EVENT_BUS",
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
        candidates = [c for c in all_candidates if c.get("category", "").lower() in sor_categories]
    elif view == "fabrics":
        candidates = [c for c in all_candidates if _plane_type(c) is not None]
    elif view == "sors_fabrics":
        candidates = [c for c in all_candidates
                      if c.get("category", "").lower() in sor_categories or _plane_type(c) is not None]
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
        
        <div class="controls">
            <span style="color: var(--text-secondary, #94a3b8); font-size: 0.85rem;">Showing {len(candidates)} of {len(all_candidates)}</span>
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
        .topology-header {{
            display: flex;
            align-items: baseline;
            gap: 16px;
            flex-wrap: wrap;
            margin-bottom: 12px;
        }}
        .topology-header h1 {{
            margin: 0;
        }}
        .topology-header .inline-stats {{
            display: flex;
            gap: 12px;
            font-size: 0.8rem;
            color: var(--slate-400);
        }}
        .topology-header .inline-stats span {{
            color: var(--cyan-400);
            font-weight: 600;
        }}
        .legend-below {{
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            margin-top: 12px;
            padding: 10px 16px;
            background: rgba(30, 41, 59, 0.6);
            border-radius: 6px;
            justify-content: center;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.85rem;
            color: var(--slate-300);
        }}
        .legend-shape {{
            width: 18px;
            height: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .legend-shape svg {{
            width: 16px;
            height: 16px;
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
        <div class="topology-header">
            <h1>Topology</h1>
            <div class="inline-stats">
                <div><span id="stat-pipes">-</span> Pipes</div>
                <div><span id="stat-fabrics">-</span> Fabrics</div>
                <div><span id="stat-sors">-</span> SORs</div>
                <div><span id="stat-drift">-</span> Drift</div>
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
                <select id="layout-select" onchange="handleLayoutAction(this.value)">
                    <option value="physics">Force-Directed</option>
                    <option value="hierarchical">Hierarchical</option>
                    <option value="circular">Circular</option>
                    <option disabled>───────────</option>
                    <option value="_fit">Fit to Screen</option>
                    <option value="_unlock">Unlock Positions</option>
                </select>
            </div>
            <button class="btn" onclick="resetView()">Reset View</button>
            <button class="btn btn-success" onclick="refreshData()">Refresh Data</button>
        </div>

        <div style="padding-right: 80px;">
        <div id="topology-container"></div>
        </div>

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
            <div class="legend-item">
                <div class="legend-shape"><svg viewBox="0 0 12 12"><rect x="1" y="1" width="10" height="10" fill="#f59e0b" stroke="#fbbf24" stroke-width="2"/></svg></div>
                <span>SOR (Farm)</span>
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

            allNodes = data.nodes.map(n => {{
                let color = n.type === 'fabric_plane'
                    ? nodeColors.fabric_plane[n.metadata.plane_type] || '#64748b'
                    : nodeColors[n.type] || '#64748b';
                let borderWidth = 1;
                let borderColor = undefined;
                if (n.metadata && n.metadata.is_authoritative) {{
                    color = '#f59e0b';
                    borderWidth = 3;
                    borderColor = '#fbbf24';
                }}
                return {{
                    id: n.id,
                    label: n.label,
                    shape: nodeShapes[n.type] || 'dot',
                    color: borderColor ? {{ background: color, border: borderColor }} : color,
                    borderWidth: borderWidth,
                    size: n.type === 'fabric_plane' ? 30 : (n.type === 'pipe' ? 20 : 15),
                    font: {{ color: '#ffffff', size: 12 }},
                    title: buildTooltip(n),
                    nodeData: n
                }};
            }});

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
            if (node.metadata.is_authoritative) html += `<span style="color:#fbbf24;font-weight:600;">Farm-Authoritative SOR</span><br/>`;
            else if (node.metadata.is_sor) html += `<span style="color:#22d3ee;">SOR (candidate-derived)</span><br/>`;
            if (node.metadata.domain) html += `Domain: ${{node.metadata.domain}}<br/>`;
            if (node.metadata.confidence) html += `Confidence: ${{node.metadata.confidence}}<br/>`;
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
            renderNetwork();
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



@router.get("/ui/reconcile", response_class=HTMLResponse, include_in_schema=False)
async def ui_reconcile_latest():
    """Redirect to the latest reconciliation run."""
    logs = list_handoff_logs(limit=1)
    if not logs:
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html><head><title>Reconcile - AAM</title>{NAV_STYLE}</head>
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
    from ..constants import SOR_CATEGORIES as sor_categories
    cat_colors = {
        "crm": "var(--cyan-400)", "erp": "var(--blue-400)", "hcm": "var(--green-400)",
        "idp": "var(--purple-400)", "itsm": "var(--orange-400)", "finance": "var(--emerald-400)",
        "saas": "var(--pink-400)", "hr": "var(--green-400)", "cmdb": "var(--amber-400)",
        "identity": "var(--purple-400)", "other": "var(--slate-400)", "unknown": "var(--slate-500)"
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
        fc_content += '<div style="color: #fcd34d; font-size: 0.85rem; margin-bottom: 12px; padding: 8px; background: rgba(251,191,36,0.05); border: 1px solid rgba(251,191,36,0.2); border-radius: 6px;">AOD did not send explicit fabric planes. The planes below were auto-inferred by AAM from candidate data. This comparison cannot be validated without AOD-declared planes.</div>'
    
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
    
    cat_labels_sor = {
        "crm": "CRM", "erp": "ERP", "hcm": "HCM", "idp": "Identity", "itsm": "ITSM",
        "saas": "SaaS", "hr": "HR", "finance": "Finance", "cmdb": "CMDB", "identity": "Identity",
    }
    
    sor_undispositioned = sc_sor.get("undispositioned", 0)
    
    sor_content = ""
    
    if not has_aod_sor:
        sor_content += '<div style="color: var(--slate-400); font-size: 0.85rem; margin-bottom: 12px; padding: 8px; background: rgba(255,255,255,0.02); border-radius: 6px;">No SOR declarations found for this run. SORs are sent by Farm via AOD handoff.</div>'
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
                source_badge = '<span style="background: rgba(251,191,36,0.15); color: #fbbf24; padding: 2px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 600;">Farm</span>'
            else:
                source_badge = '<span style="background: rgba(99,102,241,0.15); color: #a5b4fc; padding: 2px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 500;">AOD</span>'
            
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
    
    aod_fields = {"vendor_name", "display_name", "category", "known_endpoints"}
    enrichment_fields = {"preferred_modality", "connected_via_plane"}
    
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
        <p class="page-subtitle" style="margin-top: -8px;">Detailed data quality analysis across 5 dimensions</p>

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
                {check_header("Schema Completeness", False, 0, "AOD data quality overview (informational)")}
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
        .then(r => r.json())
        .then(() => location.reload())
        .catch(e => alert('Error setting disposition: ' + e));
    }}
    </script>
</body>
</html>
""")
