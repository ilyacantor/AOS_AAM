"""
Export Router — DCL export, push tracking, and stats endpoints.

BRIDGE NOTE (dual-post):
  When pushing to DCL, AAM posts the export payload to TWO DCL endpoints:
    1. DCL_INGEST_URL  — feeds DCL's existing dashboard/graph pipeline
    2. DCL_EXPORT_PIPES_URL — populates DCL's PipeDefinitionStore (ingest guard)

  This dual-post is a TEMPORARY BRIDGE.  DCL should consolidate so a single
  ingest populates both stores internally.  Once DCL wires that up, AAM
  drops the second POST and this bridge code is removed.
"""
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional
from datetime import datetime
import logging

import httpx

from ..db import get_pipe_stats, list_candidates, record_dcl_push, list_dcl_pushes, get_dcl_push
from ..dcl_export import build_dcl_export
from ..config import settings

_log = logging.getLogger(__name__)

router = APIRouter(tags=["Export"])

_DCL_TIMEOUT = 15.0


async def _deliver_to_dcl(export_payload: dict) -> dict:
    """POST the export payload to DCL's export-pipes endpoint.

    Returns a delivery_report with the status of the POST.

    This populates DCL's PipeDefinitionStore so the ingest guard
    recognises AAM pipe_ids when Farm pushes extracted data.

    NOTE: DCL_INGEST_URL (/api/dcl/ingest) is NOT used here — that
    endpoint expects Farm data records, not AAM structure exports.
    AAM only POSTs structure to /api/dcl/export-pipes.

    BRIDGE: Once DCL consolidates its stores so the existing AAM
    ingest pathway also populates the PipeDefinitionStore, this
    explicit POST can be removed.
    """
    report: dict = {"export_pipes": None}

    async with httpx.AsyncClient(timeout=_DCL_TIMEOUT) as client:
        if settings.DCL_EXPORT_PIPES_URL:
            try:
                resp = await client.post(
                    settings.DCL_EXPORT_PIPES_URL,
                    json=export_payload,
                    headers={
                        "x-api-key": settings.DCL_API_KEY,
                        "x-source": "aam",
                    },
                )
                report["export_pipes"] = {
                    "url": settings.DCL_EXPORT_PIPES_URL,
                    "status": resp.status_code,
                    "ok": resp.is_success,
                    "body": resp.json() if resp.is_success else resp.text[:500],
                    "bridge": True,
                }
                _log.info("DCL export-pipes POST (bridge) %s → %d",
                          settings.DCL_EXPORT_PIPES_URL, resp.status_code)
            except Exception as exc:
                report["export_pipes"] = {
                    "url": settings.DCL_EXPORT_PIPES_URL,
                    "error": str(exc),
                    "bridge": True,
                }
                _log.warning("DCL export-pipes POST (bridge) failed: %s", exc)
        else:
            report["export_pipes"] = {"skipped": True, "reason": "DCL_URL not configured", "bridge": True}

    return report


async def _dispatch_to_dcl() -> dict:
    """POST to DCL's dispatch endpoint to create the dispatch row.

    Must be called AFTER _deliver_to_dcl (export-pipes) so DCL has an
    export receipt.  Must be called BEFORE dispatching the Runner so
    the dispatch row is visible in DCL's Ingest tab immediately.

    The endpoint is idempotent — calling twice for the same dispatch_id
    is harmless.  Returns the dispatch_id from DCL for AAM to log.
    """
    report: dict = {"dispatch": None}

    async with httpx.AsyncClient(timeout=_DCL_TIMEOUT) as client:
        if settings.DCL_DISPATCH_URL:
            try:
                resp = await client.post(
                    settings.DCL_DISPATCH_URL,
                    headers={
                        "x-api-key": settings.DCL_API_KEY,
                        "x-source": "aam",
                    },
                )
                report["dispatch"] = {
                    "url": settings.DCL_DISPATCH_URL,
                    "status": resp.status_code,
                    "ok": resp.is_success,
                    "body": resp.json() if resp.is_success else resp.text[:500],
                }
                _log.info("DCL dispatch POST %s → %d",
                          settings.DCL_DISPATCH_URL, resp.status_code)
            except Exception as exc:
                report["dispatch"] = {
                    "url": settings.DCL_DISPATCH_URL,
                    "error": str(exc),
                }
                _log.warning("DCL dispatch POST failed: %s", exc)
        else:
            report["dispatch"] = {"skipped": True, "reason": "DCL_URL not configured"}

    return report


@router.get("/api/export/dcl/declared-pipes")
async def export_for_dcl(aod_run_id: Optional[str] = Query(None)):
    """Export connections grouped by fabric plane for DCL consumption.

    Returns fabric_planes[] with total_connections — the canonical DCL format.
    """
    export_data = build_dcl_export(aod_run_id=aod_run_id)
    return export_data.model_dump()


@router.post("/api/export/dcl/push")
async def push_to_dcl(request: Request):
    """
    Export connections to DCL and record the push for reconciliation.

    Dual-posts to DCL's ingest endpoint (dashboard pipeline) AND
    DCL's export-pipes endpoint (PipeDefinitionStore).  The second
    POST is a temporary bridge — see module docstring.

    Optional body: {"aod_run_id": "...", "notes": "..."}
    """
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    aod_run_id = body.get("aod_run_id")
    notes = body.get("notes")

    export_data = build_dcl_export(aod_run_id=aod_run_id)
    export_payload = export_data.model_dump()

    delivery_report = await _deliver_to_dcl(export_payload)

    dispatch_report = await _dispatch_to_dcl()
    delivery_report.update(dispatch_report)

    push_record = record_dcl_push(
        pipe_count=export_data.total_connections,
        payload=export_payload,
        aod_run_id=aod_run_id or export_data.aod_run_id,
        notes=notes,
    )

    return {
        "push": push_record,
        "delivery": delivery_report,
        "export": export_payload,
    }


@router.get("/api/export/dcl/pushes")
async def get_push_history(limit: int = Query(25)):
    """List recent DCL push records (without full payload)."""
    return list_dcl_pushes(limit=limit)


@router.get("/api/export/dcl/pushes/{push_id}")
async def get_push_detail(push_id: str):
    """Get a specific DCL push including the full payload that was sent."""
    result = get_dcl_push(push_id)
    if not result:
        raise HTTPException(status_code=404, detail="Push not found")
    return result


@router.get("/api/export/dcl/pushes/{push_id}/download")
async def download_push_payload(push_id: str):
    """Download the full payload from a specific DCL push as a JSON file."""
    import json as _json
    from starlette.responses import Response

    result = get_dcl_push(push_id)
    if not result:
        raise HTTPException(status_code=404, detail="Push not found")
    filename = f"dcl_push_{push_id[:8]}.json"
    return Response(
        content=_json.dumps(result["payload"], indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/export/dcl/dispatch")
async def dispatch_dcl():
    """Notify DCL to create the dispatch row from the latest export receipt.

    Call this AFTER /api/export/dcl/push and BEFORE launching the Runner.
    The push endpoint already calls this automatically, but this standalone
    endpoint lets operators trigger dispatch separately if needed.

    Idempotent — calling twice for the same dispatch is harmless.
    """
    report = await _dispatch_to_dcl()
    dispatch = report.get("dispatch", {})
    if dispatch.get("error"):
        raise HTTPException(status_code=502, detail=f"DCL dispatch failed: {dispatch['error']}")
    if dispatch.get("skipped"):
        raise HTTPException(status_code=400, detail="DCL_URL not configured — cannot dispatch")
    return report


@router.get("/api/dcl/export-pipes", tags=["DCL Export"])
async def export_pipes_for_dcl(aod_run_id: Optional[str] = Query(None)):
    """Alias for /api/export/dcl/declared-pipes — same fabric-plane-grouped format."""
    export_data = build_dcl_export(aod_run_id=aod_run_id)
    return export_data.model_dump()


@router.get("/api/stats", tags=["Stats"])
async def get_stats():
    """Get statistics about pipes by fabric_plane and modality."""
    stats = get_pipe_stats()
    candidates = list_candidates()
    stats["total_candidates"] = len(candidates)
    stats["candidates_by_status"] = {}
    for c in candidates:
        status = c.get("status", "new")
        stats["candidates_by_status"][status] = stats["candidates_by_status"].get(status, 0) + 1
    return stats
