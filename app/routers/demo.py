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

from ..db import hitl_store, supabase_client as sb
from ..ui.styles import NAV_HTML, NAV_STYLE, ui_nav
from ..ingest.mappings import MAPPINGS, FieldMapping

router = APIRouter(tags=["demo"])
_log = logging.getLogger("aam.routers.demo")

_DATA_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "harness" / "finops_saas_data"

# In-memory mid-confidence approvals so the demo UI is interactive.
_MAPPING_APPROVALS: dict[str, dict[str, Any]] = {}
_IDENTITY_REVIEW_STATE: dict[str, str] = {}  # canonical_id -> "approved" | "rejected"


@router.post("/api/aam/demo/reset")
async def demo_reset(tenant_id: str | None = Query(default=None)) -> dict[str, Any]:
    """Clear in-memory mapping approvals + (optionally) the HITL queue for a tenant.

    Used by Playwright suites that need a clean per-test starting state.
    Mapping approvals live in-memory only. The HITL queue is persisted in
    SQLite — reset is scoped to a single tenant so it never wipes cross-tenant
    state. If no tenant_id is provided, the SQLite reset is skipped and only
    the in-memory mapping cache is cleared.
    """
    cleared_mappings = len(_MAPPING_APPROVALS)
    _MAPPING_APPROVALS.clear()
    _IDENTITY_REVIEW_STATE.clear()
    cleared_hitl = 0
    if tenant_id:
        cleared_hitl = hitl_store.reset_for_tenant(tenant_id.strip())
    return {
        "cleared_mappings": cleared_mappings,
        "cleared_hitl_rows": cleared_hitl,
    }


def _load_json(name: str) -> Any:
    path = _DATA_DIR / name
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"demo data not loaded: missing {path}")
    return json.loads(path.read_text())


def _resolve_entity_id(req_entity_id: str | None = None) -> str:
    """Resolve which entity_id the demo UI should pull data for.

    Priority:
      1. Explicit query-string entity_id (test-driven or operator-driven)
      2. AOS_DEMO_ENTITY_ID env var (deployment override)
      3. Most recent AAM ingest's entity_id from semantic_triples
         (source_table LIKE 'aam_via:%') — the live system tells the demo
         which entity it should ground-truth against, so tests stay green
         across handoff churn without setting env vars.
      4. Last-resort literal "harness-entity" — only when no AAM ingest has
         ever run. This keeps the endpoint responsive instead of 500-ing on
         a fresh DB.
    """
    if req_entity_id and req_entity_id.strip():
        return req_entity_id.strip()
    env_val = (os.environ.get("AOS_DEMO_ENTITY_ID") or "").strip()
    if env_val:
        return env_val
    try:
        rows = sb._execute_composed(
            psql.SQL("""
                SELECT entity_id
                  FROM semantic_triples
                 WHERE source_table LIKE 'aam_via:%%'
                   AND entity_id IS NOT NULL
                 ORDER BY created_at DESC
                 LIMIT 1
            """),
            params=(),
            fetch=True,
        )
        if rows and rows[0].get("entity_id"):
            return str(rows[0]["entity_id"])
    except Exception as exc:
        _log.warning("demo: latest-entity lookup failed (%s); falling back", exc)
    return "harness-entity"


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
        "workato::netsuite::vendor",
        "workato::netsuite::ap_invoice",
        "boomi::okta::saas_app",
        "boomi::okta::user",
        "boomi::okta::assignment",
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
    if pipe_key == "workato::netsuite::ap_invoice" and source_field == "amount":
        return (
            "Field name 'amount' on a NetSuite AP invoice is ambiguous — it "
            "could mean gross_billed_usd (what we owed) or net_recognized_usd "
            "(what hit OpEx after accruals). Resolver picked APInvoice.gross_billed_usd "
            "at 0.78 confidence — needs operator confirmation for FinOps spend math."
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
    canonical_id: str | None = None
    hitl_queue_id: str | None = None
    decision: str = Field(..., description="approved | rejected")
    decided_by: str | None = None


@router.get("/api/aam/demo/identity-matches")
async def demo_identity_matches(
    tenant_id: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return identity matches produced by the live resolver.

    Sources:
      - pending HITL rows: from resolver_hitl_queue (status='pending')
      - auto-accepted matches: from semantic_triples where the same
        canonical_id appears across two distinct pipe_ids (NetSuite vendor
        pipe + Okta SaaS-app pipe), with resolution_method in DCL's
        vocabulary ('deterministic','fuzzy','manual'). The resolver's
        richer internal taxonomy is translated at the write boundary.

    tenant_id is required for HITL pulls; if missing we default to the most
    recent ingest's tenant (so the demo UI works without query params).
    """
    eid = _resolve_entity_id(entity_id)
    tenant_id = (tenant_id or "").strip()
    if not tenant_id:
        # Best-effort: use the most recent semantic_triples row for this entity.
        rows = sb._execute_composed(
            psql.SQL("""
                SELECT tenant_id::text AS tenant_id
                  FROM semantic_triples
                 WHERE entity_id = %s
                   AND source_table LIKE 'aam_via:%%'
                 ORDER BY created_at DESC
                 LIMIT 1
            """),
            params=(eid,),
            fetch=True,
        )
        tenant_id = (rows[0]["tenant_id"] if rows else "") or ""
    pending_rows = (
        hitl_store.get_pending(tenant_id=tenant_id, entity_id=eid, domain="saas_subscription", limit=500)
        if tenant_id else []
    )
    pending = [
        {
            "domain": r["domain"],
            "left_pipe": r["left_pipe_id"],
            "left_record_key": r["left_record_key"],
            "left_display_name": r["left_value"],
            "right_pipe": r["right_pipe_id"] or "",
            "right_record_key": r["right_record_key"] or "",
            "right_display_name": r["right_value"],
            "canonical_id": r["proposed_canonical_id"],
            "confidence": r["confidence"],
            "match_method": "fuzzy_name",
            "review_status": "pending_review",
            "hitl_queue_id": r["hitl_queue_id"],
            "reason": (r.get("extra") or {}).get(
                "input_value",
                f"Resolver scored this pair at {r['confidence']:.2f} — operator review required.",
            ),
        }
        for r in pending_rows
    ]
    # Auto-accepted matches: canonical_ids that appear under two distinct
    # pipes for the same tenant/entity. DCL's resolution_method vocabulary is
    # {'deterministic','fuzzy','manual'} (see app/ingest/triples.py
    # _RESOLUTION_METHOD_TO_PG) — those are the values that show up here.
    auto_rows = sb._execute_composed(
        psql.SQL("""
            WITH per_canonical AS (
                SELECT canonical_id::text AS canonical_id,
                       MAX(CASE WHEN source_field IN ('vendor_name','vendor_id') THEN value::text END) AS left_value,
                       MAX(CASE WHEN source_field IN ('label','id') THEN value::text END) AS right_value,
                       MAX(CASE WHEN source_field IN ('vendor_id') THEN value::text END) AS left_key,
                       MAX(CASE WHEN source_field IN ('id') THEN value::text END) AS right_key,
                       MAX(resolution_method) AS resolution_method,
                       MAX(resolution_confidence) AS resolution_confidence,
                       COUNT(DISTINCT pipe_id) AS pipe_count
                  FROM semantic_triples
                 WHERE entity_id = %s
                   AND canonical_id IS NOT NULL
                   AND source_table LIKE 'aam_via:%%'
                   AND resolution_method IN ('deterministic','fuzzy','manual')
                 GROUP BY canonical_id
            )
            SELECT * FROM per_canonical
             WHERE pipe_count >= 2
             ORDER BY resolution_confidence DESC NULLS LAST
             LIMIT 500
        """),
        params=(eid,),
        fetch=True,
    )
    def _unquote(s):
        if s is None:
            return ""
        return str(s).strip('"')
    auto_accepted: list[dict[str, Any]] = []
    for r in auto_rows:
        method = (r.get("resolution_method") or "").strip()
        confidence = float(r.get("resolution_confidence") or 0.0)
        auto_accepted.append({
            "domain": "saas_subscription",
            "left_pipe": "workato_netsuite",
            "left_record_key": _unquote(r.get("left_key")),
            "left_display_name": _unquote(r.get("left_value")),
            "right_pipe": "boomi_okta",
            "right_record_key": _unquote(r.get("right_key")),
            "right_display_name": _unquote(r.get("right_value")),
            "canonical_id": r["canonical_id"],
            "confidence": confidence,
            "match_method": method,
            "review_status": "auto_accepted",
        })
    matches = pending + auto_accepted
    return {
        "matches": matches,
        "count": len(matches),
        "pending_review": len(pending),
        "tenant_id": tenant_id,
        "entity_id": eid,
    }


@router.post("/api/aam/demo/identity-matches/resolve")
async def demo_identity_resolve(req: IdentityResolveRequest) -> dict[str, Any]:
    """Demo passthrough — forward operator decisions to the real resolver
    endpoint so the HITL queue + semantic_triples both reflect the decision.

    The demo UI carries hitl_queue_id on each review row; if absent we look
    up by proposed_canonical_id (defensive — should not happen in normal flow).
    """
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")
    if not req.hitl_queue_id:
        # Resolve by canonical_id — the UI sends it for backwards compat with
        # the old in-memory implementation.
        if not req.canonical_id:
            raise HTTPException(status_code=422, detail="hitl_queue_id or canonical_id required")
        # The hitl_store iterates pending rows; find by proposed canonical_id.
        # For the demo we assume a single tenant pending the same canonical_id.
        rows = sb._execute_composed(
            psql.SQL("""
                SELECT DISTINCT tenant_id::text AS tenant_id
                  FROM semantic_triples
                 WHERE canonical_id::text = %s
                   AND source_table LIKE 'aam_via:%%'
                 LIMIT 1
            """),
            params=(req.canonical_id,),
            fetch=True,
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"canonical_id {req.canonical_id} not found")
        tenant_id = rows[0]["tenant_id"]
        pending = hitl_store.list_all(tenant_id=tenant_id, status="pending")
        match = next((r for r in pending if r["proposed_canonical_id"] == req.canonical_id), None)
        if not match:
            raise HTTPException(status_code=404,
                                detail=f"no pending HITL row for canonical_id {req.canonical_id}")
        hitl_queue_id = match["hitl_queue_id"]
    else:
        hitl_queue_id = req.hitl_queue_id
    decided = hitl_store.decide(
        hitl_queue_id=hitl_queue_id,
        decision=req.decision,
        decided_by=req.decided_by or "demo-operator",
    )
    triples_promoted = 0
    if req.decision == "approved":
        # Reuse the canonical promotion path on the resolver router so the
        # vocab translation (fuzzy -> manual) and audit semantics stay in one
        # place. Avoids drift between demo + production promotion code.
        from .resolver import _promote_triples_to_confirmed
        triples_promoted = _promote_triples_to_confirmed(
            tenant_id=decided["tenant_id"],
            entity_id=decided["entity_id"],
            canonical_id=decided["proposed_canonical_id"],
        )
        hitl_store.append_audit(
            hitl_queue_id=hitl_queue_id,
            event="triples_promoted",
            details={"updated_triples": triples_promoted,
                     "new_method": "manual",
                     "new_confidence": 0.99},
            actor="aam.demo",
        )
    return {
        "canonical_id": decided["proposed_canonical_id"],
        "hitl_queue_id": hitl_queue_id,
        "decision": req.decision,
        "status": decided["status"],
        "triples_promoted": triples_promoted,
    }


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
    if "utilization" in q or "saas" in q or "subscriptions" in q or "licenses" in q:
        return await _answer_saas_utilization(eid, question)
    return JSONResponse(
        status_code=200,
        content={
            "question": question,
            "answer": "Demo handler not implemented for this question. The demo currently answers SaaS-utilization questions only.",
            "supported_questions": [
                "Show me SaaS subscriptions where actual utilization is below 50% of paid licenses, ranked by potential annual savings",
            ],
        },
    )


def _latest_run_for(entity_id: str, concept_prefix: str) -> str | None:
    """Return the latest AAM-sourced run_id whose triples include this concept
    prefix. concept_prefix is the canonical lowercase ontology root (e.g.
    "it_asset.saas_app"). semantic_triples stores `concept_prefix.<property>`,
    so we match by prefix LIKE.
    """
    rows = sb._execute_composed(
        psql.SQL("""
            SELECT run_id, MAX(created_at) AS ts
              FROM semantic_triples
             WHERE entity_id = %s AND concept LIKE %s AND source_table LIKE 'aam_via:%%'
             GROUP BY run_id
             ORDER BY ts DESC
             LIMIT 1
        """),
        params=(entity_id, concept_prefix + ".%"),
        fetch=True,
    )
    return str(rows[0]["run_id"]) if rows else None


def _resolve_pipe_ids_by_domain() -> dict[str, str]:
    """Return {domain: pipe_id} for the active scenario by running discovery
    once. Used to embed concrete pipe IDs in the answer response so the UI
    doesn't have to second-guess which pipe to drill into.
    """
    from ..adapters.factory import get_mcp_pair_for_vendor, supported_vendors
    from ..mcp.translator import ToolOutputTranslator
    out: dict[str, str] = {}
    for vendor in supported_vendors():
        try:
            discovery, _ = get_mcp_pair_for_vendor(vendor)
            tools = discovery.list_tools()
            if not tools:
                continue
            result = discovery.invoke_tool(tools[0].name)
            for pipe in ToolOutputTranslator(vendor=vendor).translate(tools[0].name, result):
                ref = pipe.get("endpoint_ref") or {}
                domain = ref.get("domain") if isinstance(ref, dict) else None
                if domain:
                    out[str(domain)] = pipe["pipe_id"]
        except Exception as exc:  # surface in logs, no silent fallback
            _log.warning("resolve_pipe_ids: vendor=%s failed: %s", vendor, exc)
    return out


async def _answer_saas_utilization(entity_id: str, question: str) -> dict[str, Any]:
    """Answer the FinOps SaaS-utilization demo question.

    Uses SQL aggregation against `semantic_triples` (latest run per concept)
    so the endpoint stays under the demo latency budget. The aggregation
    pivots per-record via source_run_tag, which carries the per-record key
    suffix from the triple builder.
    """
    # Latest runs per concept so we only see the most recent ingestion.
    app_run = _latest_run_for(entity_id, "it_asset.saas_app")
    assign_run = _latest_run_for(entity_id, "it_asset.assignment")
    invoice_run = _latest_run_for(entity_id, "invoice")

    if not (app_run and assign_run and invoice_run):
        return {
            "question": question,
            "entity_id": entity_id,
            "answer_text": "No data ingested yet for this entity. Run /api/aam/ingest/demo first.",
            "answer_table": {"headers": [], "rows": []},
        }

    # Per-app: license_seat_count, annual_cost_per_seat_usd, name (pivoted via source_run_tag).
    app_rows = sb._execute_composed(
        psql.SQL("""
            SELECT source_run_tag,
                   MAX(pipe_id::text) AS pipe_id,
                   MAX(CASE WHEN property = 'id' THEN value::text END) AS app_id,
                   MAX(CASE WHEN property = 'name' THEN value::text END) AS app_name,
                   MAX(CASE WHEN property = 'license_seat_count' THEN value::text END) AS seat_count,
                   MAX(CASE WHEN property = 'annual_cost_per_seat_usd' THEN value::text END) AS per_seat
              FROM semantic_triples
             WHERE entity_id = %s AND concept LIKE 'it_asset.saas_app.%%' AND run_id = %s
             GROUP BY source_run_tag
        """),
        params=(entity_id, app_run),
        fetch=True,
    )

    def _unquote(s: str | None) -> str:
        if s is None:
            return ""
        return s.strip('"')

    app_by_id: dict[str, dict[str, Any]] = {}
    for r in app_rows:
        aid = _unquote(r["app_id"])
        if not aid:
            continue
        try:
            seats = int(float(_unquote(r["seat_count"]) or "0"))
        except ValueError:
            seats = 0
        try:
            per_seat = float(_unquote(r["per_seat"]) or "0")
        except ValueError:
            per_seat = 0.0
        app_by_id[aid] = {
            "pipe_id": r["pipe_id"],
            "id": aid,
            "label": _unquote(r["app_name"]),
            "license_seat_count": seats,
            "annual_cost_per_seat_usd": per_seat,
            "license_tier": "",
        }

    # Active users per app — pull only the two relevant Assignment properties
    # (app_id, active_in_last_30d) and pivot per-record in Python. Avoids an
    # expensive self-join on a multi-hundred-k-row triple store.
    assign_rows = sb._execute_composed(
        psql.SQL("""
            SELECT source_run_tag, property, value::text AS value
              FROM semantic_triples
             WHERE entity_id = %s AND concept LIKE 'it_asset.assignment.%%' AND run_id = %s
               AND property IN ('app_id', 'active_in_last_30d')
        """),
        params=(entity_id, assign_run),
        fetch=True,
    )
    assign_pairs: dict[str, dict[str, str]] = {}
    for r in assign_rows:
        assign_pairs.setdefault(r["source_run_tag"], {})[r["property"]] = r["value"]
    active_by_app: dict[str, int] = {}
    for pair in assign_pairs.values():
        if (pair.get("active_in_last_30d") or "").lower() == "true":
            aid = _unquote(pair.get("app_id"))
            if aid:
                active_by_app[aid] = active_by_app.get(aid, 0) + 1

    # Annual cost per vendor — sum AP invoice gross amounts within last 12 months.
    # Latest due_date determines the rolling window cutoff.
    cutoff_rows = sb._execute_composed(
        psql.SQL("""
            SELECT MAX(value::text) AS latest_due
              FROM semantic_triples
             WHERE entity_id = %s AND concept LIKE 'invoice.%%' AND run_id = %s AND property = 'due_date'
        """),
        params=(entity_id, invoice_run),
        fetch=True,
    )
    latest_due = _unquote(cutoff_rows[0]["latest_due"]) if cutoff_rows else ""
    if latest_due and len(latest_due) >= 10:
        y, mo, d = latest_due.split("-")
        cutoff = f"{int(y) - 1}-{mo}-{d}"
    else:
        cutoff = "1970-01-01"

    # Annual cost per vendor — pull 3 properties (vendor_id, gross, due_date),
    # pivot in Python, filter to the rolling 12-month window.
    invoice_rows = sb._execute_composed(
        psql.SQL("""
            SELECT source_run_tag, property, value::text AS value
              FROM semantic_triples
             WHERE entity_id = %s AND concept LIKE 'invoice.%%' AND run_id = %s
               AND property IN ('vendor_id', 'gross_billed_usd', 'due_date')
        """),
        params=(entity_id, invoice_run),
        fetch=True,
    )
    invoice_recs: dict[str, dict[str, str]] = {}
    for r in invoice_rows:
        invoice_recs.setdefault(r["source_run_tag"], {})[r["property"]] = r["value"]
    annual_cost_by_vendor: dict[str, float] = {}
    for rec in invoice_recs.values():
        due = _unquote(rec.get("due_date"))
        if due < cutoff:
            continue
        vid = _unquote(rec.get("vendor_id"))
        if not vid:
            continue
        try:
            gross = float(rec.get("gross_billed_usd") or 0)
        except ValueError:
            gross = 0.0
        annual_cost_by_vendor[vid] = round(annual_cost_by_vendor.get(vid, 0.0) + gross, 2)

    # Pipe IDs by domain — embed in response so the UI drill-through doesn't
    # have to second-guess which Okta pipe (apps/users/assignments) to query.
    pipe_ids_by_domain = _resolve_pipe_ids_by_domain()
    netsuite_vendor_pipe_id = pipe_ids_by_domain.get("vendor", "")
    okta_app_pipe_id = pipe_ids_by_domain.get("saas_app", "")

    # Identity matches: source of truth is the live resolver output, not a
    # pre-computed JSON. We pull auto-accepted matches by joining triples on
    # canonical_id where the same id appears under two pipes for this entity,
    # and pending review matches from the HITL queue.
    matches_doc = (await demo_identity_matches(tenant_id=None, entity_id=entity_id))["matches"]
    saas_matches = [m for m in matches_doc if m.get("domain") == "saas_subscription"]
    auto_matches = [m for m in saas_matches if m.get("review_status") == "auto_accepted"]
    pending_matches = [m for m in saas_matches if m.get("review_status") == "pending_review"]

    # Build per-app utilization+savings rows.
    rows: list[dict[str, Any]] = []
    for m in auto_matches:
        vendor_id = m["left_record_key"]
        app_id = m["right_record_key"]
        app = app_by_id.get(app_id)
        if not app or app["license_seat_count"] <= 0:
            continue
        active = active_by_app.get(app_id, 0)
        utilization = active / app["license_seat_count"]
        annual_cost = annual_cost_by_vendor.get(vendor_id, 0.0)
        # Right-size to 2x current active users; savings are the wasted seats * per-seat cost.
        ideal_seats = max(active * 2, 1)
        wasted_seats = max(0, app["license_seat_count"] - ideal_seats)
        projected_savings = round(wasted_seats * app["annual_cost_per_seat_usd"], 2)
        rows.append({
            "canonical_id": m["canonical_id"],
            "app_id": app_id,
            "app_name": app["label"],
            "vendor_id": vendor_id,
            "vendor_name": m["left_display_name"],
            "license_seat_count": app["license_seat_count"],
            "active_user_count": active,
            "utilization_pct": round(utilization * 100, 1),
            "annual_cost_usd": annual_cost,
            "projected_annual_savings_usd": projected_savings,
            "license_tier": app["license_tier"],
            "left_pipe": m["left_pipe"],
            "right_pipe": m["right_pipe"],
            "netsuite_pipe_id": netsuite_vendor_pipe_id,
            "okta_pipe_id": okta_app_pipe_id,
        })

    # Filter to under-utilized (< 50%) and rank by savings.
    under_used = [r for r in rows if r["utilization_pct"] < 50.0]
    under_used.sort(key=lambda r: r["projected_annual_savings_usd"], reverse=True)

    total_savings = round(sum(r["projected_annual_savings_usd"] for r in under_used), 2)
    total_spend = round(sum(r["annual_cost_usd"] for r in under_used), 2)

    answer_text = (
        f"{len(under_used)} SaaS subscriptions are under 50% utilization, "
        f"costing ${total_spend:,.0f} per year. "
        f"Right-sizing recovers ~${total_savings:,.0f} annually. "
        f"{len(pending_matches)} vendor↔app match{'es' if len(pending_matches) != 1 else ''} held in review."
    )

    return {
        "question": question,
        "entity_id": entity_id,
        "answer_text": answer_text,
        "answer_table": {
            "headers": ["App", "Paid Licenses", "Active Users", "Utilization", "Annual Cost", "Projected Savings"],
            "rows": [
                {
                    "app_name": r["app_name"],
                    "license_seat_count": r["license_seat_count"],
                    "active_user_count": r["active_user_count"],
                    "utilization_pct": r["utilization_pct"],
                    "annual_cost_usd": r["annual_cost_usd"],
                    "projected_annual_savings_usd": r["projected_annual_savings_usd"],
                }
                for r in under_used[:20]
            ],
        },
        "total_projected_annual_savings_usd": total_savings,
        "total_under_used_spend_usd": total_spend,
        "pending_review_matches": [
            {
                "canonical_id": m["canonical_id"],
                "left_display_name": m["left_display_name"],
                "right_display_name": m["right_display_name"],
                "confidence": m["confidence"],
                "reason": m["reason"],
            }
            for m in pending_matches
        ],
        "provenance_drill_through": {
            "subscriptions": [
                {
                    "canonical_id": r["canonical_id"],
                    "app_name": r["app_name"],
                    "vendor_name": r["vendor_name"],
                    "utilization_pct": r["utilization_pct"],
                    "annual_cost_usd": r["annual_cost_usd"],
                    "projected_annual_savings_usd": r["projected_annual_savings_usd"],
                    "license_seat_count": r["license_seat_count"],
                    "active_user_count": r["active_user_count"],
                    "okta_pipe": r["right_pipe"],
                    "okta_pipe_id": r["okta_pipe_id"],
                    "okta_app_id": r["app_id"],
                    "netsuite_pipe": r["left_pipe"],
                    "netsuite_pipe_id": r["netsuite_pipe_id"],
                    "netsuite_vendor_id": r["vendor_id"],
                }
                for r in under_used[:20]
            ],
        },
    }


@router.get("/api/aam/demo/provenance")
async def demo_provenance(
    pipe_id: str = Query(...),
    record_key: str | None = Query(default=None, description="any natural key — app_id, vendor_id, customer_id, etc."),
    entity_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Provenance drill-through: given a pipe_id (and optional record_key for
    the natural id on that pipe), return the underlying triples plus pipe
    metadata. Each triple shows its source_field — the operator sees the raw
    vendor field that produced each AOS property.
    """
    eid = _resolve_entity_id(entity_id)
    # Normalize the pipe_id to the same UUID form that the triple writer used.
    # Translator pipe IDs are scenario strings ("wk-netsuite-vendors"); PG has
    # uuid5(NAMESPACE_URL, that string).
    import uuid as _u
    try:
        _u.UUID(pipe_id)
    except ValueError:
        pipe_id = str(_u.uuid5(_u.NAMESPACE_URL, pipe_id))
    if record_key:
        # Match by source_run_tag suffix, which carries the record_key from
        # the original transport record.
        rows = sb._execute_composed(
            psql.SQL("""
                SELECT pipe_id, run_id, source_table, source_system,
                       source_field, property, value, confidence_score, source_run_tag
                  FROM semantic_triples
                 WHERE entity_id = %s
                   AND pipe_id   = %s
                   AND source_run_tag LIKE %s
                 ORDER BY source_run_tag, property
                 LIMIT 200
            """),
            params=(eid, pipe_id, f"%::{record_key}"),
            fetch=True,
        )
    else:
        rows = sb._execute_composed(
            psql.SQL("""
                SELECT pipe_id, run_id, source_table, source_system,
                       source_field, property, value, confidence_score, source_run_tag
                  FROM semantic_triples
                 WHERE entity_id = %s AND pipe_id = %s
                 ORDER BY source_run_tag, property
                 LIMIT 50
            """),
            params=(eid, pipe_id),
            fetch=True,
        )
    return {
        "entity_id": eid,
        "pipe_id": pipe_id,
        "record_key": record_key,
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
  {ui_nav('demo')}
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
    <div class="demo-title">AAM Demo — FinOps SaaS Spending</div>
    <div class="demo-sub">Two systems of record, two pipes, one unified context. Workato → NetSuite AP + Boomi → Okta. The FinOps agent answers SaaS-utilization questions with provenance back to both pipes.</div>
    <div class="demo-card nav-grid">
      <div>
        <h3><a class="demo-link" href="/ui/demo/pipe-catalog" data-testid="link-pipe-catalog">Pipe Catalog</a></h3>
        <div class="muted">The pipes AAM discovered through MCP. Same code path across NetSuite (Workato) and Okta (Boomi).</div>
      </div>
      <div>
        <h3><a class="demo-link" href="/ui/demo/semantic-mapping" data-testid="link-semantic-mapping">Semantic Mapping</a></h3>
        <div class="muted">Field-to-concept mappings for NetSuite AP and Okta. One mid-confidence field needs your click.</div>
      </div>
      <div>
        <h3><a class="demo-link" href="/ui/demo/identity-resolution" data-testid="link-identity-resolution">Identity Resolution</a></h3>
        <div class="muted">SaaS vendor (NetSuite AP) matched to SaaS app (Okta). One match held in review.</div>
      </div>
      <div>
        <h3><a class="demo-link" href="/ui/demo/consumer-view" data-testid="link-consumer-view">Consumer View</a></h3>
        <div class="muted">Ask the FinOps question. See the answer. Drill through to source records.</div>
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
        var hints = (p.provenance && p.provenance.lineage_hints) || [];
        for (var i=0; i<hints.length; i++) { if (typeof hints[i] === 'string' && hints[i].indexOf('vendor:')===0) return hints[i].split(':')[1]; }
        var name = (p.display_name||'').toLowerCase();
        if (name.indexOf('netsuite') >= 0) return 'Workato';
        if (name.indexOf('okta') >= 0) return 'Boomi';
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
    <div class="demo-sub">NetSuite vendor master (Workato) matched to Okta SaaS apps (Boomi) — pairs the cost we paid with the app we provisioned. Auto-accepted matches power the FinOps answer. One match is held in review — the rest of the pipeline keeps working.</div>
    <div class="demo-card">
      <h3>Review Queue <span id="review-count" data-testid="review-count" class="muted"></span></h3>
      <div id="review-rows"></div>
    </div>
    <div class="demo-card">
      <h3>Auto-Accepted Matches <span id="auto-count" data-testid="auto-count" class="muted"></span></h3>
      <table class="demo-tbl" data-testid="auto-matches-table">
        <thead><tr><th>Domain</th><th>NetSuite Vendor (Workato)</th><th>Okta App (Boomi)</th><th>Confidence</th><th>Method</th></tr></thead>
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
        "Show me SaaS subscriptions where actual utilization is below 50% "
        "of paid licenses, ranked by potential annual savings"
    )
    qval = (question or default_q).replace('"', '&quot;')
    body = f"""
    <div class="demo-title">Consumer View</div>
    <div class="demo-sub">Ask the FinOps question. The answer is computed live from triples in DCL — Okta tells us who is using which app, NetSuite tells us what we paid. Every value cites the pipe + record it came from.</div>
    <div class="demo-card">
      <div style="display:flex; gap: 10px;">
        <input id="question" data-testid="question-input" value="{qval}" style="flex:1; background:#020617; color:#cbd5e1; border:1px solid #1e293b; border-radius:6px; padding:8px 12px;" />
        <button class="demo-btn" id="ask" data-testid="btn-ask">Ask</button>
      </div>
      <div class="muted" style="margin-top:8px;">FinOps demo question pre-filled. Click Ask to fetch the live answer.</div>
    </div>
    <div id="answer-card"></div>
    <div id="drill-card"></div>
    <script>
      function esc(s){{ var d=document.createElement('div'); d.textContent=String(s==null?'':s); return d.innerHTML; }}
      function money(v){{ if (v==null) return ''; return '$' + (Number(v)).toLocaleString('en-US', {{maximumFractionDigits: 0}}); }}
      function pct(v){{ if (v==null) return ''; return Number(v).toFixed(1) + '%'; }}
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
        html += '<div class="muted" style="margin-bottom:10px;" data-testid="answer-totals">Under-used annual spend: <strong>' + money(d.total_under_used_spend_usd) + '</strong> · Projected savings: <strong data-testid="total-savings">' + money(d.total_projected_annual_savings_usd) + '</strong></div>';
        html += '<table class="demo-tbl" data-testid="answer-table"><thead><tr>';
        d.answer_table.headers.forEach(function(h){{ html += '<th>' + esc(h) + '</th>'; }});
        html += '</tr></thead><tbody>';
        d.answer_table.rows.forEach(function(row){{
          html += '<tr data-testid="answer-row">';
          html += '<td data-testid="answer-app"><strong>' + esc(row.app_name) + '</strong></td>';
          html += '<td data-testid="answer-licenses">' + row.license_seat_count + '</td>';
          html += '<td data-testid="answer-active">' + row.active_user_count + '</td>';
          html += '<td data-testid="answer-utilization">' + pct(row.utilization_pct) + '</td>';
          html += '<td data-testid="answer-cost">' + money(row.annual_cost_usd) + '</td>';
          html += '<td data-testid="answer-savings"><strong>' + money(row.projected_annual_savings_usd) + '</strong></td>';
          html += '</tr>';
        }});
        html += '</tbody></table>';
        if ((d.pending_review_matches || []).length){{
          html += '<h3 style="margin-top:18px;">Matches held in review (system continues)</h3>';
          html += '<table class="demo-tbl" data-testid="pending-review-table"><thead><tr><th>NetSuite Vendor</th><th>Okta App</th><th>Confidence</th><th>Reason</th></tr></thead><tbody>';
          d.pending_review_matches.forEach(function(p){{
            html += '<tr data-testid="pending-review-row">';
            html += '<td>' + esc(p.left_display_name) + '</td>';
            html += '<td>' + esc(p.right_display_name) + '</td>';
            html += '<td><span class="pill review" data-testid="pending-review-confidence">' + (p.confidence*100).toFixed(0) + '%</span></td>';
            html += '<td class="muted">' + esc(p.reason) + '</td>';
            html += '</tr>';
          }});
          html += '</tbody></table>';
        }}
        html += '</div>';
        root.innerHTML = html;

        var subs = (d.provenance_drill_through && d.provenance_drill_through.subscriptions) || [];
        var dr = '<div class="demo-card" data-testid="drill-card">';
        dr += '<h3>Provenance Drill-Through</h3>';
        dr += '<div class="muted">Each subscription cites both pipes. Click NetSuite or Okta to see the underlying triples.</div>';
        dr += '<table class="demo-tbl" data-testid="drill-table"><thead><tr><th>Subscription</th><th>Utilization</th><th>Cost</th><th>NetSuite (Workato)</th><th>Okta (Boomi)</th></tr></thead><tbody>';
        subs.forEach(function(s){{
          dr += '<tr data-testid="drill-row">';
          dr += '<td><strong>' + esc(s.app_name) + '</strong><div class="muted">canonical: <code class="mono">' + esc(s.canonical_id.substring(0,8)) + '</code></div></td>';
          dr += '<td>' + pct(s.utilization_pct) + ' (' + s.active_user_count + '/' + s.license_seat_count + ')</td>';
          dr += '<td>' + money(s.annual_cost_usd) + '</td>';
          dr += '<td><button class="demo-btn outline" data-testid="btn-drill-netsuite" data-pipe-id="' + esc(s.netsuite_pipe_id) + '" data-key="' + esc(s.netsuite_vendor_id) + '">' + esc(s.vendor_name) + '</button></td>';
          dr += '<td><button class="demo-btn outline" data-testid="btn-drill-okta" data-pipe-id="' + esc(s.okta_pipe_id) + '" data-key="' + esc(s.okta_app_id) + '">' + esc(s.app_name) + '</button></td>';
          dr += '</tr>';
        }});
        dr += '</tbody></table>';
        dr += '<div id="triple-detail" style="margin-top:18px;"></div>';
        dr += '</div>';
        document.getElementById('drill-card').innerHTML = dr;
        bindDrillClicks();
      }}
      function bindDrillClicks(){{
        document.querySelectorAll('[data-testid="btn-drill-netsuite"], [data-testid="btn-drill-okta"]').forEach(function(btn){{
          btn.addEventListener('click', function(){{
            var pipeId = btn.getAttribute('data-pipe-id');
            var key = btn.getAttribute('data-key');
            var label = btn.getAttribute('data-testid') === 'btn-drill-netsuite' ? 'NetSuite (Workato)' : 'Okta (Boomi)';
            fetch('/api/aam/demo/provenance?pipe_id=' + encodeURIComponent(pipeId) + '&record_key=' + encodeURIComponent(key))
              .then(function(r){{ return r.json(); }}).then(function(p2){{
                var html = '<h3 data-testid="triple-detail-title">Source triples — ' + esc(label) + ' record <code class="mono">' + esc(key) + '</code></h3>';
                html += '<table class="demo-tbl" data-testid="triple-detail-table"><thead><tr><th>Property</th><th>Value</th><th>Source Field</th><th>Confidence</th></tr></thead><tbody>';
                (p2.triples||[]).forEach(function(t){{
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
