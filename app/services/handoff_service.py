"""
AOD Handoff Service — orchestrates the AOD→AAM candidate intake pipeline.

Hardened with:
  - Idempotency: duplicate run_id submissions return cached result
  - Typed error classification: CandidateRejection distinguishes data errors from system errors
  - Structured logging for every stage
"""
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from ..config import settings
from ..logger import get_logger
from ..constants import SOR_CATEGORIES, infer_plane_type_from_category, DISPLAY_NAME_PLANE_HINTS
from ..db import (
    store_fabric_plane,
    store_sor_declaration,
    create_candidate,
    create_handoff_log,
    get_handoff_log,
    list_handoff_logs,
    reset_aod_state,
)
from ..models import AODHandoffRequest, AODHandoffResponse, SORDeclaration

_log = get_logger("services.handoff")

AOD_PAYLOAD_FILE = settings.AOD_PAYLOAD_FILE


# ---- Typed error classification ----

class RejectionType(str, Enum):
    VALIDATION = "validation"      # Missing/invalid required fields
    DUPLICATE = "duplicate"        # Same run_id already processed
    SYSTEM = "system"              # Unexpected internal error


@dataclass
class CandidateRejection:
    aod_asset_id: str
    asset_key: str
    reason: str
    rejection_type: RejectionType

    def to_dict(self) -> dict:
        return {
            "aod_asset_id": self.aod_asset_id,
            "asset_key": self.asset_key,
            "reason": self.reason,
            "rejection_type": self.rejection_type.value,
        }


def save_aod_payload(request: AODHandoffRequest):
    """Persist raw AOD payload to disk for replay after reset."""
    try:
        with open(AOD_PAYLOAD_FILE, "w") as f:
            json.dump(request.model_dump(mode="json"), f)
    except Exception as e:
        _log.error("Failed to save AOD payload: %s", e)


def load_aod_payload() -> Optional[dict]:
    """Load last saved AOD payload from file."""
    try:
        with open(AOD_PAYLOAD_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def resolve_fabric_planes(request: AODHandoffRequest) -> tuple[dict, int]:
    """
    Store explicit planes from AOD or auto-create from SOR categories.

    Returns (fabric_plane_map, planes_stored) where fabric_plane_map
    maps vendor-lowercase → plane_id.
    """
    fabric_plane_map: dict[str, str] = {}
    fabric_planes_stored = 0

    if request.fabric_planes:
        for plane in request.fabric_planes:
            try:
                plane_dict = plane.model_dump()
                result = store_fabric_plane(plane_dict, request.run_id)
                plane_id = result["plane_id"]
                fabric_plane_map[plane.vendor.lower()] = plane_id
                fabric_planes_stored += 1
            except Exception as e:
                _log.error("Failed to store fabric plane %s: %s", plane.vendor, e)
    else:
        # Auto-create from candidate metadata (display names + SOR categories)
        seen_vendors: set[str] = set()
        seen_plane_types: set[str] = set()

        # Pass 1: detect fabric-infrastructure vendors from display_name hints
        # e.g. "MuleSoft - Ipaas" → IPAAS, "Kong - Api Gateway" → API_GATEWAY
        for candidate in request.candidates:
            if not candidate.vendor_name:
                continue
            display = (candidate.display_name or "").lower()
            for hint, plane_type in DISPLAY_NAME_PLANE_HINTS.items():
                if hint in display and plane_type not in seen_plane_types:
                    vendor_key = candidate.vendor_name.lower()
                    seen_vendors.add(vendor_key)
                    seen_plane_types.add(plane_type)
                    plane_dict = {
                        "plane_type": plane_type,
                        "vendor": candidate.vendor_name,
                        "display_name": candidate.display_name,
                        "domain": hint.replace(" ", "_"),
                        "managed_asset_count": 1,
                    }
                    try:
                        result = store_fabric_plane(plane_dict, request.run_id)
                        fabric_plane_map[vendor_key] = result["plane_id"]
                        fabric_planes_stored += 1
                        _log.info("Auto-created fabric plane from display hint: %s (%s)", candidate.vendor_name, plane_type)
                    except Exception as e:
                        _log.error("Failed to auto-create fabric plane for %s: %s", candidate.vendor_name, e)
                    break

        # Pass 2: create planes for SOR-category vendors not already covered
        for candidate in request.candidates:
            cat_lower = candidate.category.lower() if candidate.category else ""
            if cat_lower in SOR_CATEGORIES and candidate.vendor_name:
                vendor_key = candidate.vendor_name.lower()
                if vendor_key not in seen_vendors:
                    seen_vendors.add(vendor_key)
                    plane_type = infer_plane_type_from_category(cat_lower)
                    plane_dict = {
                        "plane_type": plane_type,
                        "vendor": candidate.vendor_name,
                        "display_name": f"{candidate.asset_key} ({candidate.category})",
                        "domain": cat_lower,
                        "managed_asset_count": 1,
                    }
                    try:
                        result = store_fabric_plane(plane_dict, request.run_id)
                        fabric_plane_map[vendor_key] = result["plane_id"]
                        fabric_planes_stored += 1
                        _log.info("Auto-created fabric plane for SOR: %s (%s)", candidate.vendor_name, plane_type)
                    except Exception as e:
                        _log.error("Failed to auto-create fabric plane for %s: %s", candidate.vendor_name, e)

    return fabric_plane_map, fabric_planes_stored


def link_candidate_to_plane(
    candidate,
    fabric_plane_map: dict[str, str],
    request_planes,
) -> Optional[str]:
    """
    Try to link a candidate to a fabric plane by vendor match or category fallback.
    Returns the plane_id or None.
    """
    vendor_lower = candidate.vendor_name.lower()

    # Try direct vendor match
    for plane_vendor, plane_id in fabric_plane_map.items():
        if plane_vendor in vendor_lower or vendor_lower in plane_vendor:
            return plane_id

    # Fallback: infer from category using shared constant mapping
    if fabric_plane_map and request_planes:
        target_type = infer_plane_type_from_category(candidate.category or "")

        for plane in request_planes:
            if plane.plane_type.upper() == target_type.upper():
                pid = fabric_plane_map.get(plane.vendor.lower())
                if pid:
                    return pid

    return None


def _build_reconciliation_data(request: AODHandoffRequest) -> tuple[list, list]:
    """Extract fabric-plane and SOR data for reconciliation logging.
    
    IMPORTANT: Only records what AOD *explicitly* sent.
    AAM-inferred fabric planes are NOT recorded as "AOD sent" — that would
    make reconciliation compare AAM to itself (always a false match).
    """
    aod_fabric_planes_data = []
    if request.fabric_planes:
        for plane in request.fabric_planes:
            aod_fabric_planes_data.append({
                "plane_type": plane.plane_type,
                "vendor": plane.vendor,
                "is_healthy": plane.is_healthy,
                "source": "aod_explicit",
            })

    aod_sor_data: dict = {}

    if request.sors:
        for sor in request.sors:
            vendor_key = sor.vendor.lower()
            aod_sor_data[vendor_key] = {
                "vendor": sor.vendor,
                "domain": sor.domain,
                "category": sor.category,
                "confidence": sor.confidence,
                "source": sor.source,
                "count": 0,
                "authoritative": True,
            }

    for candidate in request.candidates:
        cat_lower = candidate.category.lower() if candidate.category else ""
        if cat_lower in SOR_CATEGORIES and candidate.vendor_name:
            vendor_key = candidate.vendor_name.lower()
            if vendor_key not in aod_sor_data:
                aod_sor_data[vendor_key] = {"vendor": candidate.vendor_name, "category": cat_lower, "count": 0}
            aod_sor_data[vendor_key]["count"] += 1

    return aod_fabric_planes_data, list(aod_sor_data.values())


def _check_idempotency(run_id: str) -> Optional[AODHandoffResponse]:
    """
    Check if this run_id was already processed.
    Returns the cached response if so, None otherwise.
    """
    existing_logs = list_handoff_logs(aod_run_id=run_id, limit=1)
    if existing_logs:
        log = existing_logs[0]
        _log.info("Idempotent replay: run_id=%s already processed (handoff_id=%s)", run_id, log["handoff_id"])
        return AODHandoffResponse(
            run_id=run_id,
            candidates_received=log["candidates_received"],
            candidates_accepted=log["candidates_accepted"],
            candidates_rejected=log["candidates_rejected"],
            rejected_reasons=json.loads(log.get("rejected_reasons", "[]")) if isinstance(log.get("rejected_reasons"), str) else log.get("rejected_reasons", []),
            handoff_id=log["handoff_id"],
            processed_at=datetime.fromisoformat(log["processed_at"]) if log.get("processed_at") else datetime.utcnow(),
        )
    return None


def _serialize_candidate(candidate) -> dict:
    """Convert a model candidate to a DB-ready dict, handling enums."""
    candidate_dict = candidate.model_dump()

    if candidate.preferred_modality:
        candidate_dict["preferred_modality"] = candidate.preferred_modality.value
    if candidate.action_type:
        candidate_dict["action_type"] = candidate.action_type.value
    if candidate.connected_via_plane:
        candidate_dict["connected_via_plane"] = candidate.connected_via_plane.value
    if candidate.findings:
        candidate_dict["findings"] = [f.model_dump() for f in candidate.findings]

    return candidate_dict


def process_handoff(request: AODHandoffRequest) -> AODHandoffResponse:
    """
    Full AOD handoff orchestration: planes → candidates → log → response.

    This is the single entry-point for the route handler.

    Hardened with:
      - Idempotency: duplicate run_id submissions return cached result
      - Typed error classification via CandidateRejection
      - Structured logging at every stage
    """
    # 0. Idempotency check
    cached = _check_idempotency(request.run_id)
    if cached:
        return cached

    save_aod_payload(request)

    _log.info(
        "AOD handoff received: run_id=%s, snapshot=%s, candidates=%d",
        request.run_id, request.snapshot_name, len(request.candidates),
    )

    # 0b. Clear stale state from previous runs
    _log.info("Clearing previous run state before processing new handoff")
    reset_aod_state()

    # 1a. Store authoritative SOR declarations from Farm (if provided)
    sors_stored = 0
    if request.sors:
        for sor in request.sors:
            try:
                sor_dict = sor.model_dump()
                store_sor_declaration(sor_dict, request.run_id)
                sors_stored += 1
                _log.info("Stored SOR declaration: %s / %s (confidence=%s, source=%s)",
                          sor.domain, sor.vendor, sor.confidence, sor.source)
            except Exception as e:
                _log.error("Failed to store SOR declaration %s/%s: %s", sor.domain, sor.vendor, e)
        _log.info("SOR declarations stored: %d", sors_stored)

    # 1b. Resolve fabric planes
    fabric_plane_map, fabric_planes_stored = resolve_fabric_planes(request)
    _log.info("Fabric planes resolved: %d stored", fabric_planes_stored)

    # 2. Process candidates with typed error classification
    accepted = []
    rejected: list[CandidateRejection] = []

    for candidate in request.candidates:
        try:
            candidate_dict = _serialize_candidate(candidate)

            # Validate required fields
            if not candidate.asset_key:
                rejected.append(CandidateRejection(
                    aod_asset_id=candidate.aod_asset_id or "",
                    asset_key="",
                    reason="Missing required field: asset_key",
                    rejection_type=RejectionType.VALIDATION,
                ))
                continue

            # Link to fabric plane
            fabric_plane_id = link_candidate_to_plane(
                candidate, fabric_plane_map, request.fabric_planes
            )
            if fabric_plane_id:
                candidate_dict["fabric_plane_id"] = fabric_plane_id

            result = create_candidate(candidate_dict)
            accepted.append({
                "aod_asset_id": candidate.aod_asset_id,
                "candidate_id": result["candidate_id"],
                "execution_allowed": candidate.execution_allowed,
                "action_type": candidate.action_type.value,
            })
        except Exception as e:
            _log.warning("Candidate rejected: asset_key=%s reason=%s", candidate.asset_key, e)
            rejected.append(CandidateRejection(
                aod_asset_id=candidate.aod_asset_id or "",
                asset_key=candidate.asset_key,
                reason=str(e),
                rejection_type=RejectionType.SYSTEM,
            ))

    _log.info("Candidates processed: %d accepted, %d rejected", len(accepted), len(rejected))

    # 3. Build reconciliation data
    aod_fabric_planes_data, aod_sor_vendors = _build_reconciliation_data(request)

    # 4. Create handoff log
    rejected_dicts = [r.to_dict() for r in rejected]
    handoff_log = create_handoff_log({
        "aod_run_id": request.run_id,
        "snapshot_name": request.snapshot_name,
        "candidates_received": len(request.candidates),
        "candidates_accepted": len(accepted),
        "candidates_rejected": len(rejected),
        "rejected_reasons": rejected_dicts,
        "policy_version": request.policy_version,
        "handoff_timestamp": request.handoff_timestamp.isoformat() if request.handoff_timestamp else None,
        "aod_fabric_planes": aod_fabric_planes_data,
        "aod_sor_vendors": aod_sor_vendors,
    })

    return AODHandoffResponse(
        run_id=request.run_id,
        candidates_received=len(request.candidates),
        candidates_accepted=len(accepted),
        candidates_rejected=len(rejected),
        rejected_reasons=rejected_dicts,
        handoff_id=handoff_log["handoff_id"],
        processed_at=datetime.utcnow(),
    )
