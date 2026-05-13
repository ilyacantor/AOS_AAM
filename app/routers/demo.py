"""AAM Demo Experience Layer — §3.5 of the AAM Blueprint.

Four operator-facing UI screens plus the consumer-side answer API:

  GET  /ui/demo/                        — landing page with links
  GET  /ui/demo/pipe-catalog            — DeclaredPipes table (vendor/source/target)
  GET  /ui/demo/semantic-mapping        — LLM-mapping flow with mid-confidence click
  GET  /ui/demo/identity-resolution     — match queue with 0.71 review case
  GET  /ui/demo/consumer-view           — answer + provenance drill-through

  GET  /api/aam/demo/pipes              — list of pipes for catalog view
  GET  /api/aam/demo/mappings           — field mappings per pipe with confidence
  POST /api/aam/demo/mappings/approve   — apply a mid-confidence mapping (operator click)
  GET  /api/aam/demo/identity-matches   — pre-computed identity matches
  POST /api/aam/demo/identity-matches/resolve — operator action on a review case
  GET  /api/aam/demo/answer?question=…  — answer the demo question with provenance
  GET  /api/aam/demo/provenance         — drill-through: source records for one value

The answer endpoint speaks AOS unified context. It does not call an LLM. The
demo question is matched to a deterministic handler so the answer is
auditable and provenance is real.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import psycopg2.sql as psql
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..db import supabase_client as sb
from ..ui.styles import NAV_HTML, NAV_STYLE
from ..ingest.mappings import MAPPINGS, FieldMapping

router = APIRouter(tags=["demo"])
_log = logging.getLogger("aam.routers.demo")

_DATA_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "harness" / "combined_financials_data"

# In-memory mid-confidence approvals so the demo UI is interactive.
_MAPPING_APPROVALS: dict[str, dict[str, Any]] = {}
_IDENTITY_REVIEW_STATE: dict[str, str] = {}  # canonical_id -> "approved" | "rejected"


@router.post("/api/aam/demo/reset")
async def demo_reset() -> dict[str, Any]:
    """Clear in-memory mapping approvals + identity review decisions.

    Used by Playwright suites that need a clean per-test starting state. Does
    not touch persisted triples or pipes — only the demo's interactive UI
    state.
    """
    cleared_mappings = len(_MAPPING_APPROVALS)
    cleared_reviews = len(_IDENTITY_REVIEW_STATE)
    _MAPPING_APPROVALS.clear()
    _IDENTITY_REVIEW_STATE.clear()
    return {"cleared_mappings": cleared_mappings, "cleared_reviews": cleared_reviews}


def _load_json(name: str) -> Any:
    path = _DATA_DIR / name
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"demo data not loaded: missing {path}")
    return json.loads(path.read_text())


def _resolve_entity_id(req_entity_id: str | None = None) -> str:
    if req_entity_id and req_entity_id.strip():
        return req_entity_id.strip()
    return os.environ.get("AOS_DEMO_ENTITY_ID", "harness-entity")


# ---------------------------------------------------------------------------
# API: pipes
# ---------------------------------------------------------------------------

@router.get("/api/aam/demo/pipes")
async def demo_pipes() -> dict[str, Any]:
    """List the DeclaredPipes for the combined_financials demo by calling MCP
    discovery live for each supported vendor. Returns the same shape the
    Pipe Catalog UI renders.
    """
    from ..adapters.factory import get_mcp_pair_for_vendor, supported_vendors
    from ..mcp.translator import ToolOutputTranslator
    pipes: list[dict[str, Any]] = []
    for vendor in supported_vendors():
        try:
            discovery, _ = get_mcp_pair_for_vendor(vendor)
        except Exception as exc:
            _log.warning("demo_pipes: factory failure vendor=%s err=%s", vendor, exc)
            continue
        tools = discovery.list_tools()
        if not tools:
            continue
        tool_name = tools[0].name
        try:
            result = discovery.invoke_tool(tool_name)
        except Exception as exc:
            _log.warning("demo_pipes: invoke_tool failure vendor=%s tool=%s err=%s", vendor, tool_name, exc)
            continue
        translated = ToolOutputTranslator(vendor=vendor).translate(tool_name, result)
        for p in translated:
            pipes.append(p)
    return {"pipes": pipes, "count": len(pipes)}


# ---------------------------------------------------------------------------
# API: semantic mapping flow
# ---------------------------------------------------------------------------

class ApproveMappingRequest(BaseModel):
    mapping_key: str = Field(..., description="MAPPINGS dict key e.g. workato::netsuite::tran_id")
    source_field: str
    approved: bool = True


@router.get("/api/aam/demo/mappings")
async def demo_mappings() -> dict[str, Any]:
    """Return the field-mapping flow for the demo, including the mid-confidence
    field that needs explicit operator approval.

    Includes any in-memory approval state so the UI can render check marks.
    """
    DEMO_KEYS = [
        "workato::netsuite::entity_id",
        "workato::netsuite::tran_id",
        "workato::netsuite::vendor_name",
        "workato::netsuite::internal_id",
        "boomi::sage intacct::customerid",
        "boomi::sage intacct::billno",
        "boomi::sage intacct::vendorid",
        "boomi::sage intacct::recordno",
    ]
    out: list[dict[str, Any]] = []
    for key in DEMO_KEYS:
        if key not in MAPPINGS:
            continue
        pipe_name = key.replace("::", " · ")
        fields: list[dict[str, Any]] = []
        for m in MAPPINGS[key]:
            approval = _MAPPING_APPROVALS.get(f"{key}::{m.source_field}")
            confidence = m.confidence
            if approval:
                confidence = approval["confidence"]
            tier = "auto" if confidence >= 0.9 else "review" if confidence >= 0.7 else "low"
            fields.append({
                "source_field": m.source_field,
                "concept": m.concept,
                "property": m.property,
                "confidence": confidence,
                "tier": tier,
                "approved": bool(approval and approval.get("approved")),
                "needs_click": tier == "review" and not (approval and approval.get("approved")),
                "rationale": _rationale_for(key, m.source_field, m.confidence),
            })
        out.append({"pipe_key": key, "display_name": pipe_name, "fields": fields})
    return {"pipes": out}


def _rationale_for(pipe_key: str, source_field: str, confidence: float) -> str:
    if pipe_key == "workato::netsuite::tran_id" and source_field == "entity_id":
        return (
            "Field name 'entity_id' is ambiguous in NetSuite (it carries the "
            "customer reference on an invoice, but the same word is used by "
            "Salesforce for a different concept). Resolver picked Invoice.customer_id "
            "with 0.78 confidence — needs operator confirmation."
        )
    if confidence >= 0.9:
        return "Exact concept match; auto-applied."
    return f"Resolver returned {confidence:.2f}; needs review."


@router.post("/api/aam/demo/mappings/approve")
async def demo_mappings_approve(req: ApproveMappingRequest) -> dict[str, Any]:
    """Operator click: approve (or reject) a mid-confidence mapping.

    Sets the confidence to 0.99 on approval so the downstream pipeline treats
    it as authoritative.
    """
    if req.mapping_key not in MAPPINGS:
        raise HTTPException(status_code=404, detail=f"unknown mapping_key {req.mapping_key}")
    key = f"{req.mapping_key}::{req.source_field}"
    _MAPPING_APPROVALS[key] = {
        "approved": req.approved,
        "confidence": 0.99 if req.approved else 0.0,
    }
    return {"mapping_key": req.mapping_key, "source_field": req.source_field, "approved": req.approved}


# ---------------------------------------------------------------------------
# API: identity matches
# ---------------------------------------------------------------------------

class IdentityResolveRequest(BaseModel):
    canonical_id: str
    decision: str = Field(..., description="approved | rejected")


@router.get("/api/aam/demo/identity-matches")
async def demo_identity_matches() -> dict[str, Any]:
    """Return the pre-computed identity matches. Applies any in-memory review
    decisions for the demo so the queue collapses as the operator approves.
    """
    matches = _load_json("identity_matches.json")
    out: list[dict[str, Any]] = []
    for m in matches:
        cid = m.get("canonical_id")
        decision = _IDENTITY_REVIEW_STATE.get(cid)
        rec = dict(m)
        if decision == "approved" and m.get("review_status") == "pending_review":
            rec["review_status"] = "auto_accepted"
            rec["confidence"] = 0.99
        if decision == "rejected":
            rec["review_status"] = "rejected"
        out.append(rec)
    pending = sum(1 for m in out if m.get("review_status") == "pending_review")
    return {"matches": out, "count": len(out), "pending_review": pending}


@router.post("/api/aam/demo/identity-matches/resolve")
async def demo_identity_resolve(req: IdentityResolveRequest) -> dict[str, Any]:
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")
    _IDENTITY_REVIEW_STATE[req.canonical_id] = req.decision
    return {"canonical_id": req.canonical_id, "decision": req.decision}


# ---------------------------------------------------------------------------
# API: answer + provenance
# ---------------------------------------------------------------------------

@router.get("/api/aam/demo/answer")
async def demo_answer(
    question: str = Query(..., description="natural-language question"),
    entity_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Answer a demo question against the ingested combined_financials data.

    The current demo handles ONE canonical question:
      'Show me combined Q3 AR aging across both entities, with vendors that
       appear in both books flagged for consolidation.'

    Any other question returns a clear 'not implemented' response — no silent
    fallback, no fabricated answer.
    """
    eid = _resolve_entity_id(entity_id)
    q = question.lower()
    if "ar aging" in q or "ar-aging" in q or "aging" in q:
        return _answer_ar_aging(eid, question)
    return JSONResponse(
        status_code=200,
        content={
            "question": question,
            "answer": "Demo handler not implemented for this question. The demo currently answers AR aging + vendor consolidation questions only.",
            "supported_questions": [
                "Show me combined Q3 AR aging across both entities, with vendors that appear in both books flagged for consolidation",
            ],
        },
    )


def _answer_ar_aging(entity_id: str, question: str) -> dict[str, Any]:
    """Compute the answer payload for the demo's AR aging question."""
    rows = sb._execute_composed(
        psql.SQL("""
            SELECT pipe_id, run_id, source_table, source_run_tag, source_field, property, value
              FROM semantic_triples
             WHERE entity_id = %s
               AND concept   = 'ARAging'
               AND source_table LIKE 'aam_via:%%'
        """),
        params=(entity_id,),
        fetch=True,
    )
    # Group triples by source_run_tag (which carries the per-record key suffix)
    # to reconstruct ARAging records.
    records: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r["source_run_tag"]
        rec = records.setdefault(key, {
            "pipe_id": r["pipe_id"],
            # I1: read the PG column but expose under the namespaced name.
            "aam_inference_id": r["run_id"],
            "source_table": r["source_table"],
            "source_run_tag": key,
            "fields": {},
        })
        rec["fields"][r["property"]] = r["value"]

    # Q3-2024 filter: due_date in [2024-07-01, 2024-09-30].
    q3_start, q3_end = "2024-07-01", "2024-09-30"
    workato_q3: list[dict[str, Any]] = []
    boomi_q3: list[dict[str, Any]] = []
    for rec in records.values():
        fields = rec["fields"]
        due_date = str(fields.get("due_date", "")).strip('"')
        if not (q3_start <= due_date <= q3_end):
            continue
        amount_due = float(fields.get("amount_due_usd") or 0)
        amount_paid = float(fields.get("amount_paid_usd") or 0)
        net = round(amount_due - amount_paid, 2)
        aging_bucket = str(fields.get("aging_bucket", "Unknown")).strip('"')
        line = {
            "pipe_id": rec["pipe_id"],
            "source_table": rec["source_table"],
            "due_date": due_date,
            "aging_bucket": aging_bucket,
            "amount_due_usd": amount_due,
            "amount_paid_usd": amount_paid,
            "net_outstanding_usd": net,
            "customer_id": str(fields.get("customer_id", "")).strip('"'),
        }
        if "workato" in rec["source_table"]:
            workato_q3.append(line)
        else:
            boomi_q3.append(line)

    def bucket_totals(rows: list[dict[str, Any]]) -> dict[str, float]:
        out: dict[str, float] = {b: 0.0 for b in ("Current", "1-30", "31-60", "61-90", "90+")}
        for r in rows:
            b = r["aging_bucket"] if r["aging_bucket"] in out else "Current"
            out[b] = round(out[b] + r["net_outstanding_usd"], 2)
        return out

    workato_buckets = bucket_totals(workato_q3)
    boomi_buckets = bucket_totals(boomi_q3)
    combined_buckets = {
        b: round(workato_buckets[b] + boomi_buckets[b], 2)
        for b in workato_buckets
    }

    # Vendor consolidation: read identity_matches.json, filter domain=vendor.
    matches_doc = _load_json("identity_matches.json")
    vendor_overlap = [
        {
            "canonical_id": m["canonical_id"],
            "vendor_name": m["left_display_name"],
            "left_pipe": m["left_pipe"],
            "right_pipe": m["right_pipe"],
            "confidence": m["confidence"],
        }
        for m in matches_doc
        if m.get("domain") == "vendor" and m.get("review_status") == "auto_accepted"
    ]
    pending_customer_overlap = [
        m for m in matches_doc
        if m.get("domain") == "customer" and m.get("review_status") == "pending_review"
    ]

    answer_text = (
        f"Q3 2024 AR Aging across NetSuite (Workato) + Sage Intacct (Boomi): "
        f"${combined_buckets['Current']:,.0f} current, "
        f"${combined_buckets['1-30']:,.0f} 1-30 days, "
        f"${combined_buckets['31-60']:,.0f} 31-60 days, "
        f"${combined_buckets['61-90']:,.0f} 61-90 days, "
        f"${combined_buckets['90+']:,.0f} 90+ days. "
        f"{len(vendor_overlap)} vendors appear in both books and are candidates for consolidation."
    )

    return {
        "question": question,
        "entity_id": entity_id,
        "answer_text": answer_text,
        "answer_table": {
            "headers": ["Bucket", "Workato → NetSuite", "Boomi → Sage Intacct", "Combined"],
            "rows": [
                {
                    "bucket": b,
                    "workato_netsuite": workato_buckets[b],
                    "boomi_sage_intacct": boomi_buckets[b],
                    "combined": combined_buckets[b],
                }
                for b in ("Current", "1-30", "31-60", "61-90", "90+")
            ],
        },
        "vendor_consolidation_candidates": vendor_overlap,
        "pending_review_customer_matches": [
            {
                "canonical_id": m["canonical_id"],
                "left_display_name": m["left_display_name"],
                "right_display_name": m["right_display_name"],
                "confidence": m["confidence"],
                "reason": m["reason"],
            }
            for m in pending_customer_overlap
        ],
        "provenance_drill_through": {
            "workato_q3_records": [
                {"pipe_id": r["pipe_id"], "customer_id": r["customer_id"],
                 "amount": r["net_outstanding_usd"], "bucket": r["aging_bucket"],
                 "due_date": r["due_date"]}
                for r in workato_q3[:25]
            ],
            "boomi_q3_records": [
                {"pipe_id": r["pipe_id"], "customer_id": r["customer_id"],
                 "amount": r["net_outstanding_usd"], "bucket": r["aging_bucket"],
                 "due_date": r["due_date"]}
                for r in boomi_q3[:25]
            ],
        },
    }


@router.get("/api/aam/demo/provenance")
async def demo_provenance(
    pipe_id: str = Query(...),
    customer_id: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Provenance drill-through: given a pipe_id (and optional customer_id),
    return the underlying triples plus the pipe metadata. This is what the
    Consumer View renders when an operator clicks a value.
    """
    eid = _resolve_entity_id(entity_id)
    if customer_id:
        rows = sb._execute_composed(
            psql.SQL("""
                SELECT t1.pipe_id, t1.run_id, t1.source_table, t1.source_system,
                       t1.source_field, t1.property, t1.value, t1.confidence_score
                  FROM semantic_triples t1
                 WHERE t1.entity_id = %s
                   AND t1.pipe_id   = %s
                   AND t1.run_id IN (
                     SELECT t2.run_id FROM semantic_triples t2
                      WHERE t2.entity_id = %s AND t2.pipe_id = %s
                        AND t2.property IN ('customer_id', 'id')
                        AND t2.value::text = %s
                   )
                 ORDER BY t1.run_id, t1.property
                 LIMIT 200
            """),
            params=(eid, pipe_id, eid, pipe_id, json.dumps(customer_id)),
            fetch=True,
        )
    else:
        rows = sb._execute_composed(
            psql.SQL("""
                SELECT pipe_id, run_id, source_table, source_system,
                       source_field, property, value, confidence_score
                  FROM semantic_triples
                 WHERE entity_id = %s AND pipe_id = %s
                 ORDER BY run_id, property
                 LIMIT 50
            """),
            params=(eid, pipe_id),
            fetch=True,
        )
    return {
        "entity_id": eid,
        "pipe_id": pipe_id,
        "customer_id": customer_id,
        "triple_count": len(rows),
        "triples": [
            {
                "aam_inference_id": r["run_id"],
                "source_table": r["source_table"],
                "source_system": r["source_system"],
                "source_field": r["source_field"],
                "concept_property": r["property"],
                "value": r["value"],
                "confidence_score": r["confidence_score"],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# UI — landing
# ---------------------------------------------------------------------------

def _wrap_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title} — AAM Demo</title>
  {NAV_STYLE}
  <style>
    body {{ margin:0; background: #0b1220; color: #cbd5e1; font-family: 'Inter', system-ui, sans-serif; }}
    .demo-shell {{ max-width: 1100px; margin: 24px auto; padding: 0 24px; }}
    .demo-title {{ color: #fff; font-size: 1.6rem; font-weight: 700; margin: 12px 0 6px; }}
    .demo-sub {{ color: #94a3b8; font-size: 0.95rem; margin-bottom: 22px; }}
    .demo-card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 18px; margin-bottom: 18px; }}
    .demo-card h3 {{ margin: 0 0 12px; color: #f1f5f9; font-size: 1.1rem; }}
    table.demo-tbl {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
    table.demo-tbl th, table.demo-tbl td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid #1e293b; }}
    table.demo-tbl th {{ color: #94a3b8; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .pill {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; }}
    .pill.auto {{ background: rgba(16,185,129,0.15); color: #6ee7b7; }}
    .pill.review {{ background: rgba(245,158,11,0.18); color: #fcd34d; }}
    .pill.low {{ background: rgba(239,68,68,0.18); color: #fca5a5; }}
    .demo-btn {{ background: #38bdf8; color: #0b1220; border: none; padding: 7px 14px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 0.85rem; }}
    .demo-btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    .demo-btn.outline {{ background: transparent; color: #38bdf8; border: 1px solid #38bdf8; }}
    .demo-link {{ color: #38bdf8; text-decoration: none; }}
    .demo-link:hover {{ text-decoration: underline; }}
    .nav-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    code.mono {{ font-family: ui-monospace, monospace; font-size: 0.86rem; color: #fbbf24; }}
    .muted {{ color: #64748b; font-size: 0.82rem; }}
  </style>
</head>
<body>
  {NAV_HTML.replace('class=\"nav-pill\"', 'class=\"nav-pill\"')}
  <div class="demo-shell">
    {body}
  </div>
</body>
</html>
"""


@router.get("/ui/demo", response_class=HTMLResponse)
@router.get("/ui/demo/", response_class=HTMLResponse)
async def demo_landing() -> HTMLResponse:
    body = """
    <div class="demo-title">AAM Demo — Combined Financials</div>
    <div class="demo-sub">Two ERPs, two pipes, one unified context. Workato → NetSuite + Boomi → Sage Intacct.</div>
    <div class="demo-card nav-grid">
      <div>
        <h3><a class="demo-link" href="/ui/demo/pipe-catalog" data-testid="link-pipe-catalog">Pipe Catalog</a></h3>
        <div class="muted">The pipes AAM discovered through MCP. Same code path across both vendors.</div>
      </div>
      <div>
        <h3><a class="demo-link" href="/ui/demo/semantic-mapping" data-testid="link-semantic-mapping">Semantic Mapping</a></h3>
        <div class="muted">Field-to-concept mappings. One field at mid-confidence needs your click.</div>
      </div>
      <div>
        <h3><a class="demo-link" href="/ui/demo/identity-resolution" data-testid="link-identity-resolution">Identity Resolution</a></h3>
        <div class="muted">Customers and vendors matched across both books. One queued for review.</div>
      </div>
      <div>
        <h3><a class="demo-link" href="/ui/demo/consumer-view" data-testid="link-consumer-view">Consumer View</a></h3>
        <div class="muted">Ask a question. See the answer. Drill through to source records.</div>
      </div>
    </div>
    """
    return HTMLResponse(_wrap_page("Demo", body))


# ---------------------------------------------------------------------------
# UI — pipe catalog
# ---------------------------------------------------------------------------

@router.get("/ui/demo/pipe-catalog", response_class=HTMLResponse)
async def ui_pipe_catalog() -> HTMLResponse:
    body = """
    <div class="demo-title">Pipe Catalog</div>
    <div class="demo-sub">DeclaredPipes discovered by AAM via MCP. Same client code path drives every vendor — the rows below come from <code class="mono">workato</code> + <code class="mono">boomi</code> through one factory call.</div>
    <div class="demo-card">
      <table class="demo-tbl" data-testid="pipe-catalog-table">
        <thead><tr>
          <th>Display Name</th><th>Vendor</th><th>Source System</th><th>Plane</th><th>Modality</th><th>Identity Keys</th>
        </tr></thead>
        <tbody id="pipe-rows"></tbody>
      </table>
      <div class="muted" style="margin-top: 10px;" id="pipe-count" data-testid="pipe-count"></div>
    </div>
    <script>
      function esc(s){ var d=document.createElement('div'); d.textContent=String(s==null?'':s); return d.innerHTML; }
      function inferVendor(p){
        var ref = p.endpoint_ref || {};
        if (typeof ref === 'string') { try { ref = JSON.parse(ref); } catch(e) {} }
        var hints = (p.provenance && p.provenance.lineage_hints) || [];
        for (var i=0; i<hints.length; i++) { if (typeof hints[i] === 'string' && hints[i].indexOf('vendor:')===0) return hints[i].split(':')[1]; }
        var name = (p.display_name||'').toLowerCase();
        if (name.indexOf('netsuite') >= 0) return 'Workato';
        if (name.indexOf('sage') >= 0) return 'Boomi';
        return p.source_system || '';
      }
      fetch('/api/aam/demo/pipes').then(function(r){ return r.json(); }).then(function(data){
        var rows = data.pipes || [];
        var html = '';
        rows.forEach(function(p){
          var ik = p.identity_keys;
          if (typeof ik === 'string') { try { ik = JSON.parse(ik); } catch(e){ ik = [ik]; } }
          if (!Array.isArray(ik)) ik = [];
          html += '<tr data-testid="pipe-row">';
          html += '<td>' + esc(p.display_name) + '</td>';
          html += '<td>' + esc(inferVendor(p)) + '</td>';
          html += '<td>' + esc(p.source_system) + '</td>';
          html += '<td>' + esc(p.fabric_plane) + '</td>';
          html += '<td>' + esc(p.modality) + '</td>';
          html += '<td><code class="mono">' + esc(ik.join(', ')) + '</code></td>';
          html += '</tr>';
        });
        document.getElementById('pipe-rows').innerHTML = html;
        document.getElementById('pipe-count').textContent = rows.length + ' pipes discovered.';
      });
    </script>
    """
    return HTMLResponse(_wrap_page("Pipe Catalog", body))


# ---------------------------------------------------------------------------
# UI — semantic mapping
# ---------------------------------------------------------------------------

@router.get("/ui/demo/semantic-mapping", response_class=HTMLResponse)
async def ui_semantic_mapping() -> HTMLResponse:
    body = """
    <div class="demo-title">Semantic Mapping</div>
    <div class="demo-sub">Resolver maps raw vendor field names to AOS business concepts. High-confidence mappings auto-apply; mid-confidence (~0.70–0.90) requires an explicit click.</div>
    <div id="mapping-list"></div>
    <script>
      function esc(s){ var d=document.createElement('div'); d.textContent=String(s==null?'':s); return d.innerHTML; }
      function render(pipes){
        var root = document.getElementById('mapping-list');
        root.innerHTML = '';
        pipes.forEach(function(p){
          var html = '<div class="demo-card" data-testid="mapping-pipe">';
          html += '<h3 data-testid="mapping-pipe-name">' + esc(p.display_name) + '</h3>';
          html += '<table class="demo-tbl" data-testid="mapping-fields"><thead><tr><th>Source Field</th><th>Concept</th><th>Property</th><th>Confidence</th><th>Status</th><th>Action</th></tr></thead><tbody>';
          p.fields.forEach(function(f){
            var pillCls = f.tier;
            var status = f.tier === 'auto' ? 'Auto-applied' : (f.approved ? 'Approved' : 'Needs Review');
            html += '<tr data-testid="mapping-field-' + esc(f.source_field) + '">';
            html += '<td><code class="mono">' + esc(f.source_field) + '</code></td>';
            html += '<td>' + esc(f.concept) + '</td>';
            html += '<td>' + esc(f.property) + '</td>';
            html += '<td><span class="pill ' + pillCls + '" data-testid="confidence-pill">' + (f.confidence*100).toFixed(0) + '%</span></td>';
            html += '<td data-testid="mapping-status">' + esc(status) + '</td>';
            if (f.needs_click){
              html += '<td><button class="demo-btn" data-testid="btn-approve-mapping" data-key="' + esc(p.pipe_key) + '" data-field="' + esc(f.source_field) + '">Confirm mapping</button>';
              html += '<div class="muted" style="margin-top:6px;">' + esc(f.rationale) + '</div></td>';
            } else { html += '<td><span class="muted">' + esc(f.rationale) + '</span></td>'; }
            html += '</tr>';
          });
          html += '</tbody></table></div>';
          root.innerHTML += html;
        });
        document.querySelectorAll('[data-testid="btn-approve-mapping"]').forEach(function(btn){
          btn.addEventListener('click', function(){
            var key = btn.getAttribute('data-key');
            var field = btn.getAttribute('data-field');
            btn.disabled = true; btn.textContent = 'Confirming…';
            fetch('/api/aam/demo/mappings/approve', {method:'POST', headers:{'Content-Type':'application/json'},
              body: JSON.stringify({mapping_key:key, source_field:field, approved:true})})
              .then(function(r){return r.json();})
              .then(function(){ load(); });
          });
        });
      }
      function load(){
        fetch('/api/aam/demo/mappings').then(function(r){ return r.json(); }).then(function(data){ render(data.pipes || []); });
      }
      load();
    </script>
    """
    return HTMLResponse(_wrap_page("Semantic Mapping", body))


# ---------------------------------------------------------------------------
# UI — identity resolution
# ---------------------------------------------------------------------------

@router.get("/ui/demo/identity-resolution", response_class=HTMLResponse)
async def ui_identity_resolution() -> HTMLResponse:
    body = """
    <div class="demo-title">Identity Resolution</div>
    <div class="demo-sub">Customers and vendors matched across NetSuite (Workato) and Sage Intacct (Boomi). Auto-accepted matches power consolidation. Pending-review matches stay in the queue until you decide — the rest of the pipeline keeps working.</div>
    <div class="demo-card">
      <h3>Review Queue <span id="review-count" data-testid="review-count" class="muted"></span></h3>
      <div id="review-rows"></div>
    </div>
    <div class="demo-card">
      <h3>Auto-Accepted Matches <span id="auto-count" data-testid="auto-count" class="muted"></span></h3>
      <table class="demo-tbl" data-testid="auto-matches-table">
        <thead><tr><th>Domain</th><th>Workato → NetSuite</th><th>Boomi → Sage Intacct</th><th>Confidence</th><th>Method</th></tr></thead>
        <tbody id="auto-rows"></tbody>
      </table>
    </div>
    <script>
      function esc(s){ var d=document.createElement('div'); d.textContent=String(s==null?'':s); return d.innerHTML; }
      function load(){
        fetch('/api/aam/demo/identity-matches').then(function(r){ return r.json(); }).then(function(data){
          var matches = data.matches || [];
          var review = matches.filter(function(m){ return m.review_status === 'pending_review'; });
          var auto = matches.filter(function(m){ return m.review_status === 'auto_accepted'; });

          var rev = document.getElementById('review-rows');
          if (review.length === 0){
            rev.innerHTML = '<div class="muted" data-testid="review-empty">No matches pending review.</div>';
          } else {
            var html = '';
            review.forEach(function(m){
              html += '<div data-testid="review-row" data-canonical="' + esc(m.canonical_id) + '" style="border:1px solid #f59e0b22; border-radius:8px; padding:12px; margin-bottom:10px;">';
              html += '<div><span class="pill review" data-testid="review-confidence">' + (m.confidence*100).toFixed(0) + '%</span> ';
              html += '<strong style="color:#fcd34d;" data-testid="review-domain">' + esc(m.domain) + '</strong></div>';
              html += '<div style="margin-top:8px;"><code class="mono" data-testid="review-left">' + esc(m.left_display_name) + '</code> (' + esc(m.left_pipe) + ')';
              html += ' &mdash; possibly the same as ';
              html += '<code class="mono" data-testid="review-right">' + esc(m.right_display_name) + '</code> (' + esc(m.right_pipe) + ')</div>';
              html += '<div class="muted" style="margin-top:6px;" data-testid="review-reason">' + esc(m.reason) + '</div>';
              html += '<div style="margin-top:8px;">';
              html += '<button class="demo-btn" data-testid="btn-approve-match" data-canonical="' + esc(m.canonical_id) + '">Approve</button> ';
              html += '<button class="demo-btn outline" data-testid="btn-reject-match" data-canonical="' + esc(m.canonical_id) + '" style="margin-left:6px;">Reject</button>';
              html += '</div></div>';
            });
            rev.innerHTML = html;
          }
          document.getElementById('review-count').textContent = ' (' + review.length + ')';

          var html2 = '';
          auto.slice(0, 80).forEach(function(m){
            html2 += '<tr data-testid="auto-row">';
            html2 += '<td>' + esc(m.domain) + '</td>';
            html2 += '<td><code class="mono">' + esc(m.left_display_name) + '</code></td>';
            html2 += '<td><code class="mono">' + esc(m.right_display_name) + '</code></td>';
            html2 += '<td><span class="pill auto">' + (m.confidence*100).toFixed(0) + '%</span></td>';
            html2 += '<td>' + esc(m.match_method) + '</td>';
            html2 += '</tr>';
          });
          document.getElementById('auto-rows').innerHTML = html2;
          document.getElementById('auto-count').textContent = ' (' + auto.length + ' shown)';

          document.querySelectorAll('[data-testid="btn-approve-match"], [data-testid="btn-reject-match"]').forEach(function(btn){
            btn.addEventListener('click', function(){
              var decision = btn.getAttribute('data-testid') === 'btn-approve-match' ? 'approved' : 'rejected';
              var cid = btn.getAttribute('data-canonical');
              btn.disabled = true; btn.textContent = decision === 'approved' ? 'Approved' : 'Rejected';
              fetch('/api/aam/demo/identity-matches/resolve', {method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({canonical_id:cid, decision:decision})})
                .then(function(r){ return r.json(); })
                .then(function(){ load(); });
            });
          });
        });
      }
      load();
    </script>
    """
    return HTMLResponse(_wrap_page("Identity Resolution", body))


# ---------------------------------------------------------------------------
# UI — consumer view
# ---------------------------------------------------------------------------

@router.get("/ui/demo/consumer-view", response_class=HTMLResponse)
async def ui_consumer_view(question: str | None = None) -> HTMLResponse:
    default_q = (
        "Show me combined Q3 AR aging across both entities, with vendors that "
        "appear in both books flagged for consolidation"
    )
    qval = (question or default_q).replace('"', '&quot;')
    body = f"""
    <div class="demo-title">Consumer View</div>
    <div class="demo-sub">Ask a question. The answer is computed from triples in DCL. Every value cites the pipe + record it came from.</div>
    <div class="demo-card">
      <div style="display:flex; gap: 10px;">
        <input id="question" data-testid="question-input" value="{qval}" style="flex:1; background:#020617; color:#cbd5e1; border:1px solid #1e293b; border-radius:6px; padding:8px 12px;" />
        <button class="demo-btn" id="ask" data-testid="btn-ask">Ask</button>
      </div>
      <div class="muted" style="margin-top:8px;">Demo question pre-filled. Click Ask to fetch the live answer.</div>
    </div>
    <div id="answer-card"></div>
    <div id="drill-card"></div>
    <script>
      function esc(s){{ var d=document.createElement('div'); d.textContent=String(s==null?'':s); return d.innerHTML; }}
      function money(v){{ if (v==null) return ''; return '$' + (Number(v)).toLocaleString('en-US', {{maximumFractionDigits: 0}}); }}
      function ask(){{
        var q = document.getElementById('question').value;
        var btn = document.getElementById('ask');
        btn.disabled = true; btn.textContent = 'Loading…';
        var url = '/api/aam/demo/answer?question=' + encodeURIComponent(q);
        fetch(url).then(function(r){{ return r.json(); }}).then(function(d){{
          btn.disabled = false; btn.textContent = 'Ask';
          renderAnswer(d);
        }});
      }}
      function renderAnswer(d){{
        var root = document.getElementById('answer-card');
        if (!d.answer_table){{
          root.innerHTML = '<div class="demo-card"><h3>No demo handler</h3><div>' + esc(d.answer || '') + '</div></div>';
          document.getElementById('drill-card').innerHTML = '';
          return;
        }}
        var html = '<div class="demo-card" data-testid="answer-card">';
        html += '<h3 data-testid="answer-text">' + esc(d.answer_text) + '</h3>';
        html += '<table class="demo-tbl" data-testid="answer-table"><thead><tr>';
        d.answer_table.headers.forEach(function(h){{ html += '<th>' + esc(h) + '</th>'; }});
        html += '</tr></thead><tbody>';
        d.answer_table.rows.forEach(function(row){{
          html += '<tr data-testid="answer-row">';
          html += '<td data-testid="answer-bucket">' + esc(row.bucket) + '</td>';
          html += '<td data-testid="answer-workato">' + money(row.workato_netsuite) + '</td>';
          html += '<td data-testid="answer-boomi">' + money(row.boomi_sage_intacct) + '</td>';
          html += '<td data-testid="answer-combined"><strong>' + money(row.combined) + '</strong></td>';
          html += '</tr>';
        }});
        html += '</tbody></table>';
        if ((d.vendor_consolidation_candidates || []).length){{
          html += '<h3 style="margin-top:18px;">Vendors flagged for consolidation</h3>';
          html += '<table class="demo-tbl" data-testid="vendor-consolidation-table"><thead><tr><th>Vendor</th><th>Workato Pipe</th><th>Boomi Pipe</th><th>Confidence</th></tr></thead><tbody>';
          d.vendor_consolidation_candidates.forEach(function(v){{
            html += '<tr data-testid="vendor-consolidation-row">';
            html += '<td><strong>' + esc(v.vendor_name) + '</strong></td>';
            html += '<td><code class="mono">' + esc(v.left_pipe) + '</code></td>';
            html += '<td><code class="mono">' + esc(v.right_pipe) + '</code></td>';
            html += '<td><span class="pill auto">' + (v.confidence*100).toFixed(0) + '%</span></td>';
            html += '</tr>';
          }});
          html += '</tbody></table>';
        }}
        if ((d.pending_review_customer_matches || []).length){{
          html += '<h3 style="margin-top:18px;">Customer matches in review (system continues)</h3>';
          html += '<table class="demo-tbl" data-testid="pending-review-table"><thead><tr><th>Workato → NetSuite</th><th>Boomi → Sage</th><th>Confidence</th><th>Reason</th></tr></thead><tbody>';
          d.pending_review_customer_matches.forEach(function(p){{
            html += '<tr data-testid="pending-review-row">';
            html += '<td>' + esc(p.left_display_name) + '</td>';
            html += '<td>' + esc(p.right_display_name) + '</td>';
            html += '<td><span class="pill review">' + (p.confidence*100).toFixed(0) + '%</span></td>';
            html += '<td class="muted">' + esc(p.reason) + '</td>';
            html += '</tr>';
          }});
          html += '</tbody></table>';
        }}
        html += '</div>';
        root.innerHTML = html;

        var dr = '';
        var w = (d.provenance_drill_through && d.provenance_drill_through.workato_q3_records) || [];
        var b = (d.provenance_drill_through && d.provenance_drill_through.boomi_q3_records) || [];
        dr += '<div class="demo-card" data-testid="drill-card">';
        dr += '<h3>Provenance Drill-Through</h3>';
        dr += '<div class="muted">Every value in the answer above traces to source records below. Click a row to see the underlying triples.</div>';
        dr += '<h3 style="margin-top:14px;">Workato → NetSuite Q3 records (' + w.length + ')</h3>';
        dr += renderDrillTable('drill-workato', w);
        dr += '<h3 style="margin-top:14px;">Boomi → Sage Intacct Q3 records (' + b.length + ')</h3>';
        dr += renderDrillTable('drill-boomi', b);
        dr += '<div id="triple-detail" style="margin-top:18px;"></div>';
        dr += '</div>';
        document.getElementById('drill-card').innerHTML = dr;
        bindDrillClicks();
      }}
      function renderDrillTable(tid, rows){{
        var html = '<table class="demo-tbl" data-testid="' + tid + '"><thead><tr><th>Customer</th><th>Bucket</th><th>Due Date</th><th>Net Outstanding</th><th>Pipe</th></tr></thead><tbody>';
        rows.forEach(function(r){{
          html += '<tr data-testid="drill-row" data-pipe="' + esc(r.pipe_id) + '" data-customer="' + esc(r.customer_id) + '" style="cursor:pointer;">';
          html += '<td>' + esc(r.customer_id) + '</td>';
          html += '<td>' + esc(r.bucket) + '</td>';
          html += '<td>' + esc(r.due_date) + '</td>';
          html += '<td>' + money(r.amount) + '</td>';
          html += '<td><code class="mono">' + esc(r.pipe_id) + '</code></td>';
          html += '</tr>';
        }});
        html += '</tbody></table>';
        return html;
      }}
      function bindDrillClicks(){{
        document.querySelectorAll('[data-testid="drill-row"]').forEach(function(row){{
          row.addEventListener('click', function(){{
            var pipe = row.getAttribute('data-pipe');
            var cust = row.getAttribute('data-customer');
            fetch('/api/aam/demo/provenance?pipe_id=' + encodeURIComponent(pipe) + '&customer_id=' + encodeURIComponent(cust))
              .then(function(r){{return r.json();}}).then(function(p){{
                var html = '<h3 data-testid="triple-detail-title">Source records for ' + esc(cust) + ' on pipe ' + esc(pipe) + '</h3>';
                html += '<table class="demo-tbl" data-testid="triple-detail-table"><thead><tr><th>Property</th><th>Value</th><th>Source Field</th><th>Confidence</th></tr></thead><tbody>';
                (p.triples||[]).forEach(function(t){{
                  html += '<tr data-testid="triple-detail-row">';
                  html += '<td>' + esc(t.concept_property) + '</td>';
                  html += '<td><code class="mono">' + esc(JSON.stringify(t.value)) + '</code></td>';
                  html += '<td>' + esc(t.source_field) + '</td>';
                  html += '<td>' + (Number(t.confidence_score)*100).toFixed(0) + '%</td>';
                  html += '</tr>';
                }});
                html += '</tbody></table>';
                document.getElementById('triple-detail').innerHTML = html;
              }});
          }});
        }});
      }}
      document.getElementById('ask').addEventListener('click', ask);
      ask();
    </script>
    """
    return HTMLResponse(_wrap_page("Consumer View", body))
