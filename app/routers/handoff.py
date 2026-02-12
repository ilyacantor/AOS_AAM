"""
AOD Handoff Router — endpoints for AOD→AAM data intake.
"""
import json

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import Response
from typing import Optional

from ..logger import get_logger
from ..constants import SOR_CATEGORIES, infer_plane_type_from_category
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

router = APIRouter(prefix="/api/handoff/aod", tags=["AOD Handoff"])


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

    raw_planes = body.get("fabric_planes", [])
    if raw_planes:
        _log.info("Raw fabric_planes from AOD (%d):", len(raw_planes))
        for rp in raw_planes:
            _log.info("  raw: %s", json.dumps(rp))
        body["fabric_planes"] = _normalize_fabric_planes(raw_planes)
        _log.info("Normalized fabric_planes (%d):", len(body["fabric_planes"]))
        for np in body["fabric_planes"]:
            _log.info("  norm: %s", json.dumps(np))

    request = AODHandoffRequest(**body)
    _log.info(
        "Receive endpoint: run_id=%s, candidates=%d, fabric_planes=%d",
        request.run_id, len(request.candidates), len(request.fabric_planes),
    )
    return process_handoff(request)


@router.post("/fetch")
async def fetch_aod_data():
    """Re-send the last saved AOD payload (replay after reset)."""
    payload = load_aod_payload()
    if not payload:
        raise HTTPException(status_code=404, detail="No AOD data stored. Run AOD handoff first.")

    request = AODHandoffRequest(**payload)
    reset_aod_state()
    return process_handoff(request)


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
    """Backfill fabric planes from existing SOR candidates."""
    conn = get_connection()
    cursor = conn.cursor()

    sor_categories = tuple(SOR_CATEGORIES)
    placeholders = ",".join("?" * len(sor_categories))
    cursor.execute(
        f"""
        SELECT DISTINCT vendor_name, category, asset_key, aod_run_id
        FROM connection_candidates
        WHERE LOWER(category) IN ({placeholders})
        AND vendor_name IS NOT NULL AND vendor_name != ''
    """,
        sor_categories,
    )
    candidates = cursor.fetchall()
    conn.close()

    created = 0
    for row in candidates:
        vendor_name, category, asset_key, aod_run_id = row
        cat_lower = category.lower() if category else ""
        plane_type = infer_plane_type_from_category(cat_lower)
        plane_dict = {
            "plane_type": plane_type,
            "vendor": vendor_name,
            "display_name": f"{asset_key} ({category})",
            "domain": cat_lower,
            "managed_asset_count": 1,
        }
        try:
            store_fabric_plane(plane_dict, aod_run_id)
            created += 1
            _log.info("Backfilled fabric plane: %s (%s)", vendor_name, plane_type)
        except Exception as e:
            _log.warning("Skip duplicate fabric plane %s: %s", vendor_name, e)

    return {"message": f"Backfilled {created} fabric planes from SOR candidates", "created": created}
