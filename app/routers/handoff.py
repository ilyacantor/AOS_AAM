"""
AOD Handoff Router — endpoints for AOD→AAM data intake.
"""
import json

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import Response
from typing import Optional

from ..logger import get_logger
from ..constants import SOR_CATEGORIES
from ..config import settings
from ..db import (
    get_connection,
    save_policy_manifest,
    get_active_policy_manifest,
    list_policy_manifests,
    list_handoff_logs,
    get_handoff_log,
    get_candidates_by_aod_run,
    get_aod_reconciliation,
    store_fabric_plane,
    reset_aod_state,
)
from ..models import AODHandoffRequest, AODHandoffResponse, AODPolicyManifest
from ..services.handoff_service import process_handoff, load_aod_payload
from ..services.export_service import build_reconciliation_csv

_log = get_logger("routers.handoff")

RAW_AOD_BODY_FILE = "aod_raw_body.json"

router = APIRouter(prefix="/api/handoff/aod", tags=["AOD Handoff"])


def _save_raw_aod_body(body: dict):
    """Save the exact raw JSON body AOD sent, before any normalization."""
    try:
        summary = {
            "run_id": body.get("run_id"),
            "snapshot_name": body.get("snapshot_name"),
            "top_level_keys": list(body.keys()),
            "candidates_count": len(body.get("candidates", [])),
            "fabric_planes_raw": body.get("fabric_planes", []),
            "sors_raw": body.get("sors", []),
            "systems_of_record_raw": body.get("systems_of_record", []),
        }
        with open(RAW_AOD_BODY_FILE, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        _log.info("Saved raw AOD body summary to %s", RAW_AOD_BODY_FILE)
    except Exception as e:
        _log.error("Failed to save raw AOD body: %s", e)


def _normalize_fabric_planes(raw_planes: list[dict]) -> list[dict]:
    """
    Normalize AOD fabric plane objects to AAM's expected schema.

    AOD may send planes with various field names:
      { "plane_type": "iPaaS", "vendor": "workato", "is_healthy": true, "source": "farm" }
    Or alternate casing/naming:
      { "type": "ipaas", "name": "workato", "health": "Degraded" }
    """
    PLANE_TYPE_ALIASES = {
        "ipaas": "IPAAS", "iPaaS": "IPAAS",
        "api_gateway": "API_GATEWAY", "api gateway": "API_GATEWAY", "apigateway": "API_GATEWAY",
        "event_bus": "EVENT_BUS", "event bus": "EVENT_BUS", "eventbus": "EVENT_BUS",
        "data_warehouse": "DATA_WAREHOUSE", "data warehouse": "DATA_WAREHOUSE", "datawarehouse": "DATA_WAREHOUSE",
    }
    normalized = []
    for fp in raw_planes:
        pt = fp.get("plane_type") or fp.get("type") or fp.get("planeType") or ""
        vendor = fp.get("vendor") or fp.get("name") or ""
        health_raw = fp.get("is_healthy")
        if health_raw is None:
            health_str = (fp.get("health") or fp.get("status") or "healthy").lower()
            is_healthy = health_str not in ("degraded", "unhealthy", "down", "false")
        else:
            is_healthy = bool(health_raw)
        source = fp.get("source", "aod")
        pt_upper = PLANE_TYPE_ALIASES.get(pt, pt.upper().replace(" ", "_") if pt else "")
        if pt_upper and vendor:
            normalized.append({
                "plane_type": pt_upper,
                "vendor": vendor,
                "is_healthy": is_healthy,
                "source": source,
            })
    return normalized


def _normalize_sors(raw_sors: list[dict]) -> list[dict]:
    """
    Normalize AOD SOR declarations to AAM's expected schema.

    AOD may send SORs with various field names:
      { "domain": "CRM", "vendor": "Microsoft Dynamics", "category": "saas", "confidence": "high", "source": "farm" }
    Or alternate naming:
      { "type": "CRM", "name": "Microsoft Dynamics", "level": "high" }
    """
    normalized = []
    for sor in raw_sors:
        domain = sor.get("domain") or sor.get("type") or sor.get("business_domain") or ""
        vendor = sor.get("vendor") or sor.get("app_name") or sor.get("name") or sor.get("application") or ""
        category = sor.get("category") or sor.get("sor_type") or sor.get("asset_category") or ""
        confidence = sor.get("confidence") or sor.get("level") or sor.get("confidence_level") or "high"
        source = sor.get("source") or sor.get("declared_by") or "farm"

        if domain and vendor:
            normalized.append({
                "domain": domain.upper(),
                "vendor": vendor,
                "category": category.lower() if category else "",
                "confidence": confidence.lower(),
                "source": source.lower(),
            })
        else:
            _log.warning("Dropped SOR during normalization — missing domain or vendor: %s", json.dumps(sor))
    return normalized


@router.post("/receive")
async def receive_aod_handoff(raw_request: Request):
    """
    Primary AOD→AAM intake endpoint.

    Accepts a batch of candidates from AOD and:
    1. Stores/creates fabric planes
    2. Ingests candidates with deduplication
    3. Links candidates to fabric planes
    4. Logs the handoff for reconciliation
    """
    body = await raw_request.json()

    # Save raw body for diagnostics BEFORE any normalization
    _save_raw_aod_body(body)

    raw_planes = body.get("fabric_planes", [])
    _log.info("AOD raw fabric_planes field: count=%d, value=%s",
              len(raw_planes), json.dumps(raw_planes)[:500])

    if raw_planes:
        body["fabric_planes"] = _normalize_fabric_planes(raw_planes)
        _log.info("Normalized fabric_planes (%d):", len(body["fabric_planes"]))
        for np in body["fabric_planes"]:
            _log.info("  norm: %s", json.dumps(np))
    else:
        _log.warning("AOD sent NO fabric_planes. All top-level keys: %s", list(body.keys()))

    raw_sors = body.get("sors", [])
    _log.info("AOD raw sors field: count=%d", len(raw_sors))

    if raw_sors:
        body["sors"] = _normalize_sors(raw_sors)
        _log.info("Normalized sors (%d):", len(body["sors"]))
        for ns in body["sors"]:
            _log.info("  norm sor: %s", json.dumps(ns))
    else:
        _log.warning("AOD sent NO sors. All top-level keys: %s", list(body.keys()))

    request = AODHandoffRequest(**body)
    _log.info(
        "Receive endpoint: run_id=%s, candidates=%d, fabric_planes=%d, sors=%d",
        request.run_id, len(request.candidates), len(request.fabric_planes), len(request.sors),
    )
    return process_handoff(request)


@router.post("/fetch")
async def fetch_aod_data():
    """Re-send the last saved AOD payload (replay after reset).

    If a raw body file exists from the last /receive call, re-normalize
    from that (so normalizer fixes apply retroactively). Otherwise fall
    back to the saved model dump.
    """
    import os
    payload = None

    if os.path.exists(RAW_AOD_BODY_FILE):
        with open(RAW_AOD_BODY_FILE) as f:
            raw = json.load(f)
        raw_planes = raw.get("fabric_planes_raw", [])
        raw_sors = raw.get("sors_raw", [])
        saved = load_aod_payload()
        if saved and (raw_planes or raw_sors):
            _log.info("Fetch: re-normalizing from raw body (planes=%d, sors=%d)", len(raw_planes), len(raw_sors))
            if raw_planes:
                saved["fabric_planes"] = _normalize_fabric_planes(raw_planes)
            if raw_sors:
                saved["sors"] = _normalize_sors(raw_sors)
            payload = saved

    if not payload:
        payload = load_aod_payload()

    if not payload:
        raise HTTPException(status_code=404, detail="No AOD data stored. Run AOD handoff first.")

    request = AODHandoffRequest(**payload)
    reset_aod_state()
    return process_handoff(request)


@router.get("/debug/last-receive")
async def debug_last_receive():
    """Show exactly what AOD sent in the last /receive call (raw, pre-normalization).

    Use this to trace whether AOD is sending fabric_planes and sors,
    and what field names it uses.
    """
    import os
    if not os.path.exists(RAW_AOD_BODY_FILE):
        raise HTTPException(status_code=404, detail="No raw AOD body saved yet. Trigger a /receive first.")
    with open(RAW_AOD_BODY_FILE) as f:
        raw = json.load(f)

    saved = load_aod_payload()
    saved_fp = saved.get("fabric_planes", []) if saved else []
    saved_sors = saved.get("sors", []) if saved else []

    return {
        "what_aod_sent_raw": raw,
        "what_aam_saved_after_normalization": {
            "fabric_planes_count": len(saved_fp),
            "fabric_planes": saved_fp,
            "sors_count": len(saved_sors),
            "sors": saved_sors,
        },
        "diagnosis": {
            "aod_sent_fabric_planes": len(raw.get("fabric_planes_raw", [])) > 0,
            "aod_sent_sors": len(raw.get("sors_raw", [])) > 0,
            "aod_used_alternate_key_systems_of_record": len(raw.get("systems_of_record_raw", [])) > 0,
            "aam_has_fabric_planes_after_parse": len(saved_fp) > 0,
            "aam_has_sors_after_parse": len(saved_sors) > 0,
        },
    }


@router.post("/policy")
async def receive_aod_policy(policy: AODPolicyManifest):
    """Receive governance policy manifest from AOD."""
    policy_dict = policy.model_dump()
    result = save_policy_manifest(policy_dict)
    return {
        "message": "Policy manifest received and activated",
        "policy_id": result["policy_id"],
        "policy_version": result["policy_version"],
        "is_active": True,
    }


@router.get("/policy")
async def get_current_aod_policy():
    """Get the currently active AOD policy manifest."""
    policy = get_active_policy_manifest()
    if not policy:
        return {"message": "No active policy manifest", "policy": None}
    return {"policy": policy}


@router.get("/policy/history")
async def get_aod_policy_history(limit: int = Query(20)):
    """Get history of AOD policy manifests."""
    policies = list_policy_manifests(limit=limit)
    return {"policies": policies, "count": len(policies)}


@router.get("/logs")
async def get_handoff_logs_list(
    aod_run_id: Optional[str] = Query(None),
    limit: int = Query(50),
):
    """Get AOD handoff logs."""
    logs = list_handoff_logs(aod_run_id=aod_run_id, limit=limit)
    return {"logs": logs, "count": len(logs)}


@router.get("/logs/{handoff_id}")
async def get_handoff_log_detail(handoff_id: str):
    """Get details of a specific handoff."""
    log = get_handoff_log(handoff_id)
    if not log:
        raise HTTPException(status_code=404, detail="Handoff log not found")
    return log


@router.get("/run/{aod_run_id}/candidates")
async def get_candidates_from_aod_run(aod_run_id: str):
    """Get all candidates from a specific AOD discovery run."""
    candidates = get_candidates_by_aod_run(aod_run_id)
    return {"aod_run_id": aod_run_id, "candidates": candidates, "count": len(candidates)}


@router.get("/run/{aod_run_id}/reconciliation")
async def get_aod_run_reconciliation(aod_run_id: str):
    """Reconcile AOD handoff data with AAM storage."""
    reconciliation = get_aod_reconciliation(aod_run_id)
    return reconciliation


@router.get("/run/{aod_run_id}/reconciliation/download")
async def download_reconciliation_summary(aod_run_id: str):
    """Download a CSV summary of all reconciliation mismatches."""
    try:
        csv_content, filename = build_reconciliation_csv(aod_run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Fabric-plane backfill endpoint
fabric_router = APIRouter(prefix="/api/fabric-planes", tags=["Fabric Planes"])


@fabric_router.post("/backfill")
async def backfill_fabric_planes_from_candidates():
    """Backfill is disabled — AAM does not infer fabric planes from application categories.

    Fabric planes only come from AOD-discovered infrastructure evidence or
    explicit operator declarations.  Use POST /api/adapters/{plane}/connect
    to register known infrastructure.
    """
    return {
        "message": "Backfill disabled: AAM does not infer infrastructure from application categories. "
                   "Fabric planes come from AOD discovery or operator declarations only.",
        "created": 0
    }
