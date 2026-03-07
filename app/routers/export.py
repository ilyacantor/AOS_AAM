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
import httpx
import json

from ..db import get_pipe_stats, list_candidates, record_dcl_push, list_dcl_pushes, get_dcl_push
from ..db.dcl_pushes import record_dcl_export_attempt, get_last_export_attempt
from ..dcl_export import build_dcl_export
from ..config import settings
from ..logger import get_logger

_log = get_logger("routers.export")

router = APIRouter(tags=["Export"])

_DCL_TIMEOUT = None  # No timeout — DCL warmup can take minutes with large datasets

_last_dcl_dispatch: dict | None = None


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
            _log.info("DCL export-pipes POST starting — waiting for DCL to respond...")
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
                    "bridge": True,
                    "url": settings.DCL_EXPORT_PIPES_URL,
                    "ok": resp.is_success,
                    "status": resp.status_code,
                    "body": resp.json() if resp.is_success else resp.text[:500],
                    "error": None,
                    "skipped": False,
                }
                _log.info("DCL export-pipes POST (bridge) %s → %d",
                          settings.DCL_EXPORT_PIPES_URL, resp.status_code)
            except httpx.ConnectError as exc:
                error_detail = str(exc) or f"{type(exc).__name__}: {repr(exc)}"
                report["export_pipes"] = {
                    "bridge": True,
                    "url": settings.DCL_EXPORT_PIPES_URL,
                    "ok": False,
                    "status": None,
                    "body": None,
                    "error": error_detail,
                    "skipped": False,
                }
                _log.warning("DCL not reachable at %s — is the backend running? %s",
                             settings.DCL_EXPORT_PIPES_URL, exc)
            except httpx.ReadTimeout as exc:
                error_detail = str(exc) or f"{type(exc).__name__}: {repr(exc)}"
                report["export_pipes"] = {
                    "bridge": True,
                    "url": settings.DCL_EXPORT_PIPES_URL,
                    "ok": False,
                    "status": None,
                    "body": None,
                    "error": error_detail,
                    "skipped": False,
                }
                _log.warning("DCL export-pipes timed out — DCL may still be loading. Check DCL logs.")
            except Exception as exc:
                error_detail = str(exc) or f"{type(exc).__name__}: {repr(exc)}"
                report["export_pipes"] = {
                    "bridge": True,
                    "url": settings.DCL_EXPORT_PIPES_URL,
                    "ok": False,
                    "status": None,
                    "body": None,
                    "error": error_detail,
                    "skipped": False,
                }
                _log.warning("DCL export-pipes POST (bridge) failed: %s: %s", type(exc).__name__, error_detail)
        else:
            report["export_pipes"] = {
                "bridge": True,
                "url": None,
                "ok": False,
                "status": None,
                "body": None,
                "error": None,
                "skipped": True,
            }

    return report


async def _dispatch_to_dcl(aod_run_id: Optional[str] = None,
                           snapshot_name: Optional[str] = None,
                           pipe_count: Optional[int] = None) -> dict:
    """POST to DCL's dispatch endpoint to create the dispatch row.

    Must be called AFTER _deliver_to_dcl (export-pipes) so DCL has an
    export receipt.  Must be called BEFORE dispatching the Runner so
    the dispatch row is visible in DCL's Ingest tab immediately.

    Sends aod_run_id, snapshot_name, and pipe_count so DCL can create
    the dispatch row with full context.

    The endpoint is idempotent — calling twice for the same dispatch_id
    is harmless.  Returns the dispatch_id from DCL for AAM to log.
    """
    report: dict = {"dispatch": None}

    if not aod_run_id:
        from ..db.handoff import list_handoff_logs
        handoffs = list_handoff_logs(limit=1)
        if handoffs:
            aod_run_id = handoffs[0].get("aod_run_id")
            snapshot_name = snapshot_name or handoffs[0].get("snapshot_name")

    dispatch_body = {
        "aod_run_id": aod_run_id,
        "snapshot_name": snapshot_name,
        "source": "aam",
    }
    if pipe_count is not None:
        dispatch_body["pipe_count"] = pipe_count

    async with httpx.AsyncClient(timeout=_DCL_TIMEOUT) as client:
        if settings.DCL_DISPATCH_URL:
            try:
                _log.info("DCL dispatch POST starting %s — waiting for DCL to respond... body=%s",
                          settings.DCL_DISPATCH_URL, dispatch_body)
                resp = await client.post(
                    settings.DCL_DISPATCH_URL,
                    json=dispatch_body,
                    headers={
                        "x-api-key": settings.DCL_API_KEY,
                        "x-source": "aam",
                        "Content-Type": "application/json",
                    },
                )
                report["dispatch"] = {
                    "url": settings.DCL_DISPATCH_URL,
                    "status": resp.status_code,
                    "ok": resp.is_success,
                    "body": resp.json() if resp.is_success else resp.text[:500],
                }
                _log.info("DCL dispatch POST %s → %d  body=%s",
                          settings.DCL_DISPATCH_URL, resp.status_code,
                          resp.text[:300])
                global _last_dcl_dispatch
                _last_dcl_dispatch = {
                    "aod_run_id": aod_run_id,
                    "snapshot_name": snapshot_name,
                    "pipe_count": pipe_count,
                    "dcl_status": report["dispatch"]["body"].get("status") if isinstance(report["dispatch"].get("body"), dict) else None,
                    "dispatch_id": report["dispatch"]["body"].get("dispatch_id") if isinstance(report["dispatch"].get("body"), dict) else None,
                    "http_status": resp.status_code,
                    "ok": resp.is_success,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
            except httpx.ConnectError as exc:
                report["dispatch"] = {
                    "url": settings.DCL_DISPATCH_URL,
                    "error": str(exc),
                }
                _log.warning("DCL not reachable at %s — is the backend running? %s",
                             settings.DCL_DISPATCH_URL, exc)
            except httpx.ReadTimeout as exc:
                report["dispatch"] = {
                    "url": settings.DCL_DISPATCH_URL,
                    "error": str(exc),
                }
                _log.warning("DCL dispatch timed out — DCL may still be loading. Check DCL logs.")
            except Exception as exc:
                report["dispatch"] = {
                    "url": settings.DCL_DISPATCH_URL,
                    "error": str(exc),
                }
                _log.warning("DCL dispatch POST failed: %s: %s", type(exc).__name__, exc)
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
    raw = await request.body()
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Request body is not valid JSON: {exc}")

    aod_run_id = body.get("aod_run_id")
    notes = body.get("notes")

    export_data = build_dcl_export(aod_run_id=aod_run_id)
    export_payload = export_data.model_dump()

    delivery_report = await _deliver_to_dcl(export_payload)

    # Only record the push if DCL actually accepted the blueprints.
    # If DCL rejected (422, 500, etc.), the dispatch guard must block —
    # recording a push for a failed delivery causes NO_MATCHING_PIPE.
    ep_delivery = delivery_report.get("export_pipes") or {}
    dcl_accepted = ep_delivery.get("ok", False)

    # Persist every attempt (success + failure) for diagnostics.
    # Unlike dcl_pushes (successes only), this lets operators query
    # "why did the last export fail?" without searching logs.
    try:
        record_dcl_export_attempt(
            aod_run_id=aod_run_id or export_data.aod_run_id,
            pipe_count=export_data.total_connections,
            dcl_ok=dcl_accepted,
            dcl_status=ep_delivery.get("status"),
            dcl_body=str(ep_delivery.get("body", ""))[:2000] if ep_delivery.get("body") else None,
            dcl_error=ep_delivery.get("error"),
        )
    except Exception as exc:
        _log.warning("Failed to record export attempt: %s", exc)

    push_record = None
    if dcl_accepted:
        push_record = record_dcl_push(
            pipe_count=export_data.total_connections,
            payload=export_payload,
            aod_run_id=aod_run_id or export_data.aod_run_id,
            notes=notes,
        )
    else:
        dcl_status = ep_delivery.get("status")
        dcl_error = ep_delivery.get("error") or ep_delivery.get("body", "")
        _log.warning(
            "DCL rejected export (status=%s) — push NOT recorded. "
            "Dispatch guard will block until a successful export. Detail: %s",
            dcl_status, str(dcl_error)[:300],
        )

    return {
        "push": push_record,
        "delivery": delivery_report,
        "dcl_accepted": dcl_accepted,
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
async def dispatch_dcl(request: Request):
    """Notify DCL to create the dispatch row from the latest export receipt.

    Call this AFTER /api/export/dcl/push and BEFORE launching the Runner.

    Optional body: {"aod_run_id": "...", "snapshot_name": "...", "pipe_count": N}
    If omitted, resolves from the latest handoff log.

    Idempotent — calling twice for the same dispatch is harmless.
    """
    body = {}
    raw = await request.body()
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Request body is not valid JSON: {exc}")

    report = await _dispatch_to_dcl(
        aod_run_id=body.get("aod_run_id"),
        snapshot_name=body.get("snapshot_name"),
        pipe_count=body.get("pipe_count"),
    )
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


@router.get("/api/export/dcl/last-attempt", tags=["Export"])
async def last_export_attempt(aod_run_id: Optional[str] = Query(None)):
    """Return the most recent DCL export attempt with full error detail.

    Unlike /pushes (which only lists successes), this returns the last
    attempt regardless of outcome — including the DCL HTTP status code,
    response body, and error string.  Use this to diagnose export failures.
    """
    attempt = get_last_export_attempt(aod_run_id=aod_run_id)
    return {"attempt": attempt}


@router.get("/api/export/dcl/dispatch-status", tags=["Export"])
async def get_dispatch_status():
    """Return the last DCL dispatch result (in-memory).

    Returns null if no dispatch has been sent since server start.
    """
    return {"dcl_dispatch": _last_dcl_dispatch}


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
