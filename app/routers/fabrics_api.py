"""WS-1 — Fabrics API endpoints.

These endpoints back the AAM Fabrics tab UI (rendered server-side in
app/routers/ui_pages.py at /ui/fabrics). The earlier app/routers/fabrics.py
mixed the UI route with these APIs; that file is deleted and the UI moved
into the AAM /ui nav. The APIs themselves keep their /api/aam/fabrics/*
contracts unchanged so existing callers (Console pipelines, demo
orchestration, manual operator probes) continue to work.

APIs:
  GET  /api/aam/fabrics/list             — implemented vendors + 4-state health
  GET  /api/aam/fabrics/receipts         — recent receipts (filter by vendor)
  GET  /api/aam/fabrics/receipts/{id}    — drill-down (payload + triples + resolver)
  GET  /api/aam/fabrics/aggregate        — counts over a window
  GET  /api/aam/fabrics/manual/pipes     — pipe-key list with fields
  POST /api/aam/fabrics/{vendor}/trigger — proxy to Farm fabric-sims trigger
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from ..adapters import IMPLEMENTED_VENDORS, IPaaSAdapter
from ..db import fabric_webhook_log
from ..ingest import mappings as mappings_mod
from .webhooks import _MANUAL_PIPE_TO_EVENT

_log = logging.getLogger("aam.routers.fabrics_api")
router = APIRouter(tags=["fabrics"])


# What env vars each vendor needs for its adapter to function. Used by the
# status endpoint to tell the operator "missing X" rather than failing silently.
_VENDOR_ENV: dict[str, list[str]] = {
    "workato": ["WORKATO_BASE_URL", "WORKATO_API_TOKEN", "WORKATO_WEBHOOK_SECRET"],
    "boomi": ["BOOMI_BASE_URL", "BOOMI_USERNAME", "BOOMI_API_TOKEN",
              "BOOMI_ACCOUNT_ID", "BOOMI_ATOM_ID", "BOOMI_WEBHOOK_SECRET"],
}


async def _vendor_status(vendor: str) -> dict[str, Any]:
    """Compose vendor card data: env presence + 4-state health + operational status."""
    env_required = _VENDOR_ENV.get(vendor, [])
    env_present = {k: bool(os.environ.get(k)) for k in env_required}
    missing = [k for k, v in env_present.items() if not v]

    health: dict[str, Any] = {
        "health_state": "auth_expired" if missing else "unknown",
        "status": "unknown",
        "latency_ms": None,
        "error": f"missing env: {', '.join(missing)}" if missing else None,
    }
    if not missing:
        try:
            adapter = IPaaSAdapter({"vendor": vendor})
            h = await adapter.check_health()
            health = {
                "health_state": h.health_state,
                "status": h.status.value,
                "latency_ms": h.latency_ms,
                "error": h.error_message,
            }
        except Exception as exc:
            health = {
                "health_state": "unreachable",
                "status": "failed",
                "latency_ms": None,
                "error": str(exc)[:200],
            }
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
    companions: dict[str, Any] = {"ingest_status": None, "triples": []}
    if row.get("dcl_ingest_id"):
        companions = fabric_webhook_log.fetch_drill_companions(
            dcl_ingest_id=row["dcl_ingest_id"],
        )
    hitl_rows: list[dict[str, Any]] = []
    # Best-effort HITL window match. Requires the receipt to carry tenant/entity
    # context; older rows may not, in which case the panel renders empty.
    payload = row.get("payload_jsonb") or {}
    tenant_id = payload.get("tenant_id") or row.get("tenant_id")
    entity_id = payload.get("entity_id") or row.get("entity_id")
    received_utc = row.get("received_utc")
    if tenant_id and entity_id and received_utc:
        hitl_rows = fabric_webhook_log.fetch_hitl_for_receipt(
            tenant_id=tenant_id, entity_id=entity_id, received_utc=received_utc,
        )
    return {"receipt": row, "hitl_decisions": hitl_rows, **companions}


@router.get("/api/aam/fabrics/aggregate")
async def aggregate(
    vendor: str | None = Query(default=None),
    hours: int = Query(default=24, ge=1, le=720),
) -> dict[str, Any]:
    return {
        "window_hours": hours,
        "vendor": vendor,
        "counts": fabric_webhook_log.aggregate_counts(vendor=vendor, window_hours=hours),
    }


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
        raise HTTPException(
            status_code=502,
            detail=f"Farm trigger HTTP {resp.status_code}: {resp.text[:200]}",
        )
    return {"vendor": vendor, "farm_response": resp.json()}
