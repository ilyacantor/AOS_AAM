"""WP12b+e — Fabrics tab.

UI:    GET  /aam/fabrics
APIs:  GET  /api/aam/fabrics/list                  — implemented vendors + status
       GET  /api/aam/fabrics/receipts              — recent receipts (filter by vendor)
       GET  /api/aam/fabrics/receipts/{id}         — drill-down (payload + triples + resolver)
       GET  /api/aam/fabrics/aggregate             — counts over a window
       GET  /api/aam/fabrics/manual/pipes          — pipe-key list with fields
       POST /api/aam/fabrics/{vendor}/trigger      — proxy to Farm fabric-sims trigger

The page is server-rendered HTML with vanilla fetch + setInterval (5s) for
the receipts table — matches the existing AAM controls / topology pattern.
Drill-down and manual-entry result panes do not auto-refresh.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from ..adapters import IMPLEMENTED_VENDORS, IPaaSAdapter
from ..db import fabric_webhook_log
from ..ingest import mappings as mappings_mod
from .webhooks import _MANUAL_PIPE_TO_EVENT

_log = logging.getLogger("aam.routers.fabrics")
router = APIRouter(tags=["fabrics"])


# ---------------------------------------------------------------------------
# Vendor metadata + per-vendor status
# ---------------------------------------------------------------------------

# What env vars each vendor needs for its adapter to function. Used by the
# status endpoint to tell the operator "missing X" rather than failing
# silently.
_VENDOR_ENV: dict[str, list[str]] = {
    "workato": ["WORKATO_BASE_URL", "WORKATO_API_TOKEN", "WORKATO_WEBHOOK_SECRET"],
    "boomi": ["BOOMI_BASE_URL", "BOOMI_USERNAME", "BOOMI_API_TOKEN",
              "BOOMI_ACCOUNT_ID", "BOOMI_ATOM_ID", "BOOMI_WEBHOOK_SECRET"],
}


async def _vendor_status(vendor: str) -> dict[str, Any]:
    env_required = _VENDOR_ENV.get(vendor, [])
    env_present = {k: bool(os.environ.get(k)) for k in env_required}
    missing = [k for k, v in env_present.items() if not v]
    health: dict[str, Any] = {"status": "unknown", "latency_ms": None, "error": None}
    if not missing:
        try:
            adapter = IPaaSAdapter({"vendor": vendor})
            h = await adapter.check_health()
            health = {
                "status": h.status.value, "latency_ms": h.latency_ms,
                "error": h.error_message,
            }
        except Exception as exc:
            health = {"status": "failed", "latency_ms": None, "error": str(exc)[:200]}
    return {
        "vendor": vendor,
        "env_present": env_present,
        "env_missing": missing,
        "health": health,
    }


@router.get("/api/aam/fabrics/list")
async def list_fabrics() -> dict[str, Any]:
    statuses = await asyncio.gather(*[_vendor_status(v) for v in sorted(IMPLEMENTED_VENDORS)])
    return {"vendors": statuses}


@router.get("/api/aam/fabrics/receipts")
async def list_receipts(
    vendor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    return {"receipts": fabric_webhook_log.list_recent(vendor=vendor, limit=limit)}


@router.get("/api/aam/fabrics/receipts/{receipt_id}")
async def receipt_detail(receipt_id: str) -> dict[str, Any]:
    row = fabric_webhook_log.get_one(receipt_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"receipt {receipt_id} not found")
    companions: dict[str, Any] = {"ingest_status": None}
    if row.get("dcl_ingest_id"):
        companions = fabric_webhook_log.fetch_drill_companions(
            dcl_ingest_id=row["dcl_ingest_id"],
        )
    return {"receipt": row, **companions}


@router.get("/api/aam/fabrics/aggregate")
async def aggregate(
    vendor: str | None = Query(default=None),
    hours: int = Query(default=24, ge=1, le=720),
) -> dict[str, Any]:
    return {"window_hours": hours, "vendor": vendor,
            "counts": fabric_webhook_log.aggregate_counts(vendor=vendor, window_hours=hours)}


@router.get("/api/aam/fabrics/manual/pipes")
async def list_manual_pipes() -> dict[str, Any]:
    """Pipe keys with manual-entry dispatch wired (subset of MAPPINGS)."""
    out = []
    for key in sorted(_MANUAL_PIPE_TO_EVENT.keys()):
        fields = mappings_mod.MAPPINGS.get(key, [])
        out.append({
            "pipe_key": key,
            "fields": [
                {"source_field": f.source_field, "concept": f.concept,
                 "property": f.property, "confidence": f.confidence}
                for f in fields
            ],
        })
    return {"pipes": out}


@router.post("/api/aam/fabrics/{vendor}/trigger")
async def trigger_vendor(vendor: str) -> dict[str, Any]:
    if vendor not in IMPLEMENTED_VENDORS:
        raise HTTPException(status_code=404, detail=f"vendor {vendor!r} not implemented")
    farm_base = os.environ.get("FARM_URL", "http://localhost:8003").rstrip("/")
    url = f"{farm_base}/farm/fabric-sims/trigger/{vendor}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Farm trigger failed: {exc}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502,
                            detail=f"Farm trigger HTTP {resp.status_code}: {resp.text[:200]}")
    return {"vendor": vendor, "farm_response": resp.json()}


# ---------------------------------------------------------------------------
# UI page — server-rendered HTML, vanilla fetch + 5s setInterval
# ---------------------------------------------------------------------------

_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AAM — Fabrics</title>
<style>
  body { font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; margin: 24px; background: #f8fafc; color: #0f172a; }
  h1 { margin: 0 0 4px; font-size: 20px; }
  h2 { margin: 28px 0 8px; font-size: 16px; }
  h3 { margin: 16px 0 4px; font-size: 14px; }
  .nav a { margin-right: 12px; color: #0369a1; text-decoration: none; font-size: 13px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .panel { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 6px 8px; border-bottom: 1px solid #f1f5f9; text-align: left; vertical-align: top; }
  th { background: #f1f5f9; font-weight: 600; color: #475569; text-transform: uppercase; font-size: 10px; }
  tr:hover td { background: #f8fafc; cursor: pointer; }
  .badge { padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .pass  { background: #dcfce7; color: #166534; }
  .fail  { background: #fee2e2; color: #b91c1c; }
  .warn  { background: #fef3c7; color: #92400e; }
  .muted { color: #64748b; }
  .mono  { font-family: ui-monospace, SFMono-Regular, monospace; font-size: 11px; }
  button { background: #0284c7; color: #fff; border: 0; padding: 6px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; }
  button:hover { background: #0369a1; }
  button:disabled { background: #94a3b8; cursor: not-allowed; }
  input, select { padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 12px; }
  pre { background: #0f172a; color: #e2e8f0; padding: 10px; border-radius: 6px; font-size: 11px; overflow-x: auto; max-height: 360px; }
  .row-flex { display: flex; gap: 12px; align-items: center; }
  .stat { background: #f1f5f9; padding: 8px 12px; border-radius: 6px; font-size: 12px; }
  .stat strong { display: block; font-size: 18px; color: #0f172a; }
</style>
</head>
<body>
<header>
  <h1>Fabrics</h1>
  <div class="nav">
    <a href="/ui/topology">Topology</a>
    <a href="/ui/pipes">Pipes</a>
    <a href="/ui/candidates">Candidates</a>
    <a href="/ui/drift">Drift &amp; Health</a>
    <strong>Fabrics</strong>
    <a href="/ui/reconcile">Reconcile</a>
    <a href="/ui/controls">Controls</a>
    <a href="/ui/guide">Guide</a>
  </div>
  <p class="muted" style="font-size:13px;">Real-time webhook activity from registered fabric adapters. Trigger demo runs and inject manual records into the resolver/converter pipeline.</p>
</header>

<section>
  <h2>Registered fabrics</h2>
  <div id="vendor-cards" class="grid"></div>
</section>

<section>
  <h2 style="display:inline-block;">Recent receipts</h2>
  <span style="margin-left:12px;font-size:12px;" class="muted">auto-refresh 5s</span>
  <span style="margin-left:8px;">
    filter:
    <select id="filter-vendor" onchange="loadReceipts()">
      <option value="">all</option>
    </select>
  </span>
  <div class="panel" style="margin-top:8px;padding:0;">
    <table>
      <thead><tr>
        <th>received</th><th>vendor</th><th>event</th><th>src</th>
        <th>sig</th><th>rows</th><th>triples</th><th>push</th><th>err</th>
      </tr></thead>
      <tbody id="receipt-rows"></tbody>
    </table>
    <div id="receipt-empty" class="muted" style="padding:12px;text-align:center;display:none;">no receipts yet</div>
  </div>
</section>

<section id="drill-section" style="display:none;">
  <h2>Receipt drill-down <span id="drill-id" class="mono muted" style="font-size:11px;"></span>
    <button style="margin-left:8px;background:#64748b;" onclick="closeDrill()">close</button>
  </h2>
  <div class="grid">
    <div class="panel"><h3>webhook payload (as received by AAM)</h3><pre id="drill-payload"></pre></div>
    <div class="panel">
      <h3>DCL ingest status (from /api/dcl/ingest-status)</h3>
      <div id="drill-ingest-status" class="muted">—</div>
      <h3 style="margin-top:14px;">concept summary (DCL)</h3>
      <table id="drill-summary"><thead><tr><th>concept</th><th>count</th></tr></thead><tbody></tbody></table>
    </div>
  </div>
</section>

<section>
  <h2>Manual entry</h2>
  <p class="muted" style="font-size:12px;">Inject a single record into the same resolver/converter/push path as a webhook. Useful for HITL pair construction and edge-case testing.</p>
  <div class="panel">
    <div class="row-flex" style="margin-bottom:12px;">
      <label>pipe: <select id="manual-pipe" onchange="renderManualFields()"></select></label>
      <button onclick="submitManual()">submit</button>
    </div>
    <div id="manual-fields"></div>
    <h3>last result</h3>
    <pre id="manual-result" class="muted">—</pre>
  </div>
</section>

<script>
async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(url + ' -> ' + r.status + ' ' + (await r.text()).slice(0, 200));
  return r.json();
}

let MANUAL_PIPES = [];

async function loadVendors() {
  const data = await fetchJSON('/api/aam/fabrics/list');
  const sel = document.getElementById('filter-vendor');
  // preserve current selection
  const cur = sel.value;
  sel.innerHTML = '<option value="">all</option>' +
    data.vendors.map(v => `<option value="${v.vendor}">${v.vendor}</option>`).join('');
  sel.value = cur;
  const cards = document.getElementById('vendor-cards');
  cards.innerHTML = '';
  for (const v of data.vendors) {
    const agg = await fetchJSON(`/api/aam/fabrics/aggregate?vendor=${v.vendor}&hours=24`);
    const c = agg.counts;
    const healthBadge = v.health.status === 'connected' ? 'pass'
      : v.health.status === 'failed' ? 'fail' : 'warn';
    const div = document.createElement('div');
    div.className = 'panel';
    div.innerHTML = `
      <div class="row-flex" style="justify-content:space-between;">
        <h3 style="margin:0;font-size:16px;">${v.vendor}</h3>
        <span class="badge ${healthBadge}">${v.health.status}${v.health.latency_ms ? ' · ' + v.health.latency_ms + 'ms' : ''}</span>
      </div>
      <div class="muted" style="font-size:11px;margin:6px 0;">env: ${
        v.env_missing.length === 0 ? 'all set' : 'missing ' + v.env_missing.join(', ')
      }${v.health.error ? ' · err: ' + v.health.error : ''}</div>
      <div class="row-flex" style="gap:8px;flex-wrap:wrap;">
        <div class="stat"><strong>${c.received}</strong>received·24h</div>
        <div class="stat"><strong>${c.verified}</strong>sig ok</div>
        <div class="stat"><strong>${c.push_succeeded}</strong>push ok</div>
        <div class="stat"><strong>${c.triples_pushed_total}</strong>triples</div>
        <div class="stat" style="${c.errors > 0 ? 'background:#fee2e2;' : ''}"><strong>${c.errors}</strong>errors</div>
      </div>
      <div style="margin-top:12px;">
        <button onclick="triggerVendor('${v.vendor}')" id="trig-${v.vendor}">trigger demo run</button>
        <span id="trig-result-${v.vendor}" class="muted" style="margin-left:8px;font-size:11px;"></span>
      </div>`;
    cards.appendChild(div);
  }
}

async function loadReceipts() {
  const v = document.getElementById('filter-vendor').value;
  const url = v ? `/api/aam/fabrics/receipts?vendor=${v}&limit=50` : '/api/aam/fabrics/receipts?limit=50';
  const data = await fetchJSON(url);
  const tbody = document.getElementById('receipt-rows');
  const empty = document.getElementById('receipt-empty');
  tbody.innerHTML = '';
  if (data.receipts.length === 0) { empty.style.display = 'block'; return; }
  empty.style.display = 'none';
  for (const r of data.receipts) {
    const tr = document.createElement('tr');
    tr.onclick = () => openDrill(r.id);
    const sigBadge = r.signature_verified ? '<span class="badge pass">ok</span>' : '<span class="badge fail">bad</span>';
    const pushBadge = r.push_status_code == null ? '<span class="muted">…</span>'
      : r.push_status_code >= 200 && r.push_status_code < 300 ? `<span class="badge pass">${r.push_status_code}</span>`
      : `<span class="badge fail">${r.push_status_code}</span>`;
    const ts = (r.received_utc || '').slice(11, 19);
    const errText = r.error ? `<span class="fail mono">${r.error.slice(0, 50)}</span>` : '';
    tr.innerHTML = `
      <td class="mono">${ts}</td><td>${r.vendor}</td>
      <td>${r.event_type || ''}</td>
      <td><span class="muted">${r.source}</span></td>
      <td>${sigBadge}</td>
      <td>${r.rows_seen ?? ''}</td>
      <td>${r.triples_pushed ?? ''}</td>
      <td>${pushBadge}</td>
      <td>${errText}</td>`;
    tbody.appendChild(tr);
  }
}

async function openDrill(id) {
  const sec = document.getElementById('drill-section');
  sec.style.display = 'block';
  document.getElementById('drill-id').textContent = id;
  document.getElementById('drill-payload').textContent = 'loading…';
  const data = await fetchJSON(`/api/aam/fabrics/receipts/${id}`);
  document.getElementById('drill-payload').textContent =
    JSON.stringify(data.receipt.payload_jsonb || {info: 'payload not stored (verification failed)'}, null, 2);
  const status = (data.ingest_status || {});
  const statusDiv = document.getElementById('drill-ingest-status');
  if (status.error) {
    statusDiv.innerHTML = `<span class="fail">${status.error}</span>`;
  } else if (status.dcl_ingest_id) {
    statusDiv.innerHTML = `<span class="badge pass">${status.is_active ? 'active' : 'inactive'}</span>
      &nbsp;<span class="mono">${status.dcl_ingest_id}</span>
      &nbsp;<strong>${status.triple_count}</strong> triples
      &nbsp;<span class="muted">created ${status.created_at || ''}</span>`;
  } else {
    statusDiv.innerHTML = '<span class="muted">no DCL state</span>';
  }
  const sumBody = document.querySelector('#drill-summary tbody');
  const summary = (status.concept_summary || {});
  sumBody.innerHTML = Object.keys(summary).sort().map(k =>
    `<tr><td>${k}</td><td>${summary[k]}</td></tr>`
  ).join('');
  sec.scrollIntoView({behavior: 'smooth'});
}

function closeDrill() { document.getElementById('drill-section').style.display = 'none'; }

async function triggerVendor(v) {
  const btn = document.getElementById(`trig-${v}`);
  const out = document.getElementById(`trig-result-${v}`);
  btn.disabled = true; out.textContent = 'triggering…';
  try {
    const r = await fetchJSON(`/api/aam/fabrics/${v}/trigger`, {method: 'POST'});
    out.innerHTML = `<span class="pass">ok</span> fired ${r.farm_response.fired.length}; receipts will appear within 5s`;
    setTimeout(loadReceipts, 1500);
  } catch (e) {
    out.innerHTML = `<span class="fail">err: ${e.message}</span>`;
  }
  btn.disabled = false;
}

async function loadManualPipes() {
  const data = await fetchJSON('/api/aam/fabrics/manual/pipes');
  MANUAL_PIPES = data.pipes;
  const sel = document.getElementById('manual-pipe');
  sel.innerHTML = data.pipes.map(p => `<option value="${p.pipe_key}">${p.pipe_key}</option>`).join('');
  renderManualFields();
}

function renderManualFields() {
  const key = document.getElementById('manual-pipe').value;
  const pipe = MANUAL_PIPES.find(p => p.pipe_key === key);
  const div = document.getElementById('manual-fields');
  if (!pipe) { div.innerHTML = ''; return; }
  div.innerHTML = '<table style="width:auto;"><tbody>' + pipe.fields.map(f =>
    `<tr><td class="mono" style="padding-right:12px;">${f.source_field}</td>
       <td><input data-field="${f.source_field}" placeholder="(${f.concept}.${f.property})" size="40"></td></tr>`
  ).join('') + '</tbody></table>';
}

async function submitManual() {
  const key = document.getElementById('manual-pipe').value;
  const inputs = document.querySelectorAll('#manual-fields input[data-field]');
  const row = {};
  inputs.forEach(i => { if (i.value !== '') row[i.dataset.field] = i.value; });
  const out = document.getElementById('manual-result');
  out.textContent = 'submitting…';
  try {
    const r = await fetchJSON('/api/aam/manual-entry', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({pipe_key: key, row}),
    });
    out.textContent = JSON.stringify(r, null, 2);
    setTimeout(loadReceipts, 1000);
  } catch (e) {
    out.textContent = 'error: ' + e.message;
  }
}

loadVendors();
loadReceipts();
loadManualPipes();
setInterval(loadReceipts, 5000);
setInterval(loadVendors, 30000);
</script>
</body>
</html>
"""


@router.get("/aam/fabrics", response_class=HTMLResponse)
async def fabrics_page() -> HTMLResponse:
    return HTMLResponse(content=_PAGE_HTML)
