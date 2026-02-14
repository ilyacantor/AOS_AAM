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
from ..constants import SOR_CATEGORIES, PLANE_TYPE_ALIASES
from ..db import (
    store_fabric_plane,
    store_sor_declaration,
    create_candidate,
    create_handoff_log,
    get_handoff_log,
    list_handoff_logs,
    reset_aod_state,
)
from ..models import AODHandoffRequest, AODHandoffResponse, SORDeclaration, CandidateStatus

_log = get_logger("services.handoff")


# ---- AOD payload normalization ----

def normalize_fabric_planes(raw_planes: list[dict]) -> list[dict]:
    """Normalize AOD fabric plane objects to AAM's expected schema."""
    normalized = []
    for fp in raw_planes:
        pt = fp.get("plane_type") or fp.get("type") or fp.get("planeType") or ""
        vendor = fp.get("vendor") or fp.get("name") or ""
        health_raw = fp.get("is_healthy")
        if health_raw is None:
            is_healthy = None  # AOD didn't declare — preserve uncertainty
        else:
            is_healthy = bool(health_raw)
        source = fp.get("source", "aod")
        pt_upper = PLANE_TYPE_ALIASES.get(pt, pt.upper().replace(" ", "_") if pt else "")
        if pt_upper and vendor:
            normalized.append({
                "plane_type": pt_upper, "vendor": vendor,
                "is_healthy": is_healthy, "source": source,
            })
    return normalized


def normalize_candidates(raw_candidates: list[dict]) -> list[dict]:
    """Normalize AOD candidate objects before pydantic parsing.

    The FabricPlane enum is case-sensitive (e.g. "API_GATEWAY").  AOD may
    send connected_via_plane in lowercase ("api_gateway") which would crash
    pydantic validation for the ENTIRE batch.  Normalize it here, same as
    we normalize plane_type on fabric planes.
    """
    valid_action_types = {"provision", "inventory_only"}
    for c in raw_candidates:
        cvp = c.get("connected_via_plane")
        if cvp and isinstance(cvp, str):
            normalized = PLANE_TYPE_ALIASES.get(cvp, cvp.upper().replace(" ", "_"))
            c["connected_via_plane"] = normalized
        # Also handle preferred_modality if it's lowercase
        pm = c.get("preferred_modality")
        if pm and isinstance(pm, str):
            c["preferred_modality"] = pm.upper().replace(" ", "_")
        # Normalize action_type — AOD may send "Provision", "PROVISION", etc.
        at = c.get("action_type")
        if at and isinstance(at, str):
            at_lower = at.lower().strip()
            if at_lower not in valid_action_types:
                _log.warning("Unknown action_type '%s' for %s, defaulting to inventory_only",
                             at, c.get("asset_key", "?"))
                at_lower = "inventory_only"
            c["action_type"] = at_lower
    return raw_candidates


def normalize_sors(raw_sors: list[dict]) -> list[dict]:
    """Normalize AOD SOR declarations to AAM's expected schema."""
    normalized = []
    for sor in raw_sors:
        domain = sor.get("domain") or sor.get("type") or sor.get("business_domain") or ""
        vendor = sor.get("vendor") or sor.get("app_name") or sor.get("name") or sor.get("application") or ""
        category = sor.get("category") or sor.get("sor_type") or sor.get("asset_category") or ""
        confidence = sor.get("confidence") or sor.get("level") or sor.get("confidence_level") or "unknown"
        source = sor.get("source") or sor.get("declared_by") or "unknown"
        if domain and vendor:
            normalized.append({
                "domain": domain.upper(), "vendor": vendor,
                "category": category.lower() if category else "",
                "confidence": confidence.lower(), "source": source.lower(),
            })
        else:
            _log.warning("Dropped SOR during normalization — missing domain or vendor: %s",
                         json.dumps(sor))
    return normalized


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
    """Cache the raw AOD payload in the database so /fetch can replay it.

    Stored in aod_payload_cache (single-row table) which is NOT cleared
    by reset_aod_state(), so the payload survives across resets.
    """
    from ..db import get_db
    payload_json = json.dumps(request.model_dump(), default=str)
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO aod_payload_cache (id, payload, cached_at) VALUES (1, ?, ?)",
            (payload_json, datetime.utcnow().isoformat()),
        )


def load_aod_payload() -> Optional[dict]:
    """Load the cached AOD payload from the database.

    Reads from aod_payload_cache which survives reset_aod_state().
    """
    from ..db import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT payload FROM aod_payload_cache WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row["payload"])


def resolve_fabric_planes(request: AODHandoffRequest) -> tuple[dict, int]:
    """
    Store explicit fabric planes that AOD sent.

    If AOD didn't send fabric_planes, there are no planes — AAM does NOT
    infer infrastructure from candidate metadata.  AOD owns fabric-plane
    detection; AAM only allocates assets to planes AOD discovered.

    Returns (fabric_plane_map, planes_stored) where fabric_plane_map
    maps vendor-lowercase → plane_id.
    """
    fabric_plane_map: dict[str, str] = {}
    fabric_planes_stored = 0

    for plane in request.fabric_planes or []:
        try:
            plane_dict = plane.model_dump()
            result = store_fabric_plane(plane_dict, request.run_id)
            plane_id = result["plane_id"]
            fabric_plane_map[plane.vendor.lower()] = plane_id
            fabric_planes_stored += 1
        except Exception as e:
            _log.error("Failed to store fabric plane %s: %s", plane.vendor, e)

    return fabric_plane_map, fabric_planes_stored


def link_candidate_to_plane(
    candidate,
    fabric_plane_map: dict[str, str],
    request_planes,
) -> Optional[str]:
    """
    Link a candidate to a fabric plane.

    Resolution order:
      1. connected_via_plane (AOD routing hint) → match by plane TYPE
      2. Direct vendor-name match (plane vendor == candidate vendor)

    If neither matches, returns None — the candidate stays UNMAPPED.
    We do NOT guess a default plane from the preset; that was creating
    the 654-into-API_GATEWAY pile-up.
    """
    # Build type → plane_id lookup from the stored planes
    type_to_plane_id: dict[str, str] = {}
    for _vendor_key, plane_id in fabric_plane_map.items():
        plane_type = plane_id.split(":")[0] if ":" in plane_id else plane_id
        if plane_type not in type_to_plane_id:
            type_to_plane_id[plane_type] = plane_id

    # 1. Use connected_via_plane routing hint from AOD
    if candidate.connected_via_plane:
        plane_type = candidate.connected_via_plane.value  # e.g. "API_GATEWAY"
        if plane_type in type_to_plane_id:
            return type_to_plane_id[plane_type]

    # 2. Direct vendor-name match (normalize underscores/spaces for comparison)
    vendor_lower = candidate.vendor_name.lower()
    vendor_norm = vendor_lower.replace("_", " ")
    for plane_vendor, plane_id in fabric_plane_map.items():
        plane_norm = plane_vendor.replace("_", " ")
        if plane_norm in vendor_norm or vendor_norm in plane_norm:
            return plane_id

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

            # Link to fabric plane (AOD hint or vendor-name match only)
            fabric_plane_id = link_candidate_to_plane(
                candidate, fabric_plane_map, request.fabric_planes
            )
            if fabric_plane_id:
                candidate_dict["fabric_plane_id"] = fabric_plane_id
                # Also set connected_via_plane for topology resolution
                if not candidate_dict.get("connected_via_plane"):
                    plane_type = fabric_plane_id.split(":")[0] if ":" in fabric_plane_id else fabric_plane_id
                    candidate_dict["connected_via_plane"] = plane_type

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

    aod_accepted_count = len(accepted)  # snapshot BEFORE infra candidates
    _log.info("Candidates processed: %d accepted, %d rejected", aod_accepted_count, len(rejected))

    # 2b. Ensure every fabric plane vendor has a representative candidate.
    #     AOD declares fabric planes (infrastructure endpoints) but doesn't
    #     always include them as candidates.  Without a candidate record the
    #     plane is invisible in pipes / candidates views even though it shows
    #     in topology and reconciliation.  This is NOT fabrication — AOD
    #     explicitly told us this infrastructure exists.
    accepted_vendors = {c.vendor_name.lower() for c in request.candidates if c.vendor_name}
    for plane in request.fabric_planes or []:
        vendor_lower = plane.vendor.lower().replace("_", " ")
        # Check if any accepted candidate already covers this vendor
        already_covered = any(
            v and (vendor_lower in v.replace("_", " ") or v.replace("_", " ") in vendor_lower)
            for v in accepted_vendors
        )
        if already_covered:
            continue

        plane_id = fabric_plane_map.get(plane.vendor.lower())
        if not plane_id:
            continue

        infra_candidate = {
            "asset_key": f"infra:{plane.plane_type.lower()}:{plane.vendor.lower()}",
            "vendor_name": plane.vendor,
            "display_name": f"{plane.vendor}, {plane.plane_type.replace('_', ' ').title()}",
            "category": plane.plane_type.lower(),
            "governance_status": None,
            "findings": [],
            "sor_tagging": None,
            "evidence_refs": [],
            "signals_summary": None,
            "known_endpoints": [],
            "preferred_modality": None,
            "priority_score": None,
            "execution_allowed": True,
            "action_type": "provision",
            "blocking_findings": [],
            "connected_via_plane": plane.plane_type.upper(),
            "aod_run_id": request.run_id,
            "aod_asset_id": f"infra-{plane.vendor.lower()}",
            "fabric_plane_id": plane_id,
            "status": CandidateStatus.NEW,
        }
        try:
            result = create_candidate(infra_candidate)
            accepted.append({
                "aod_asset_id": infra_candidate["aod_asset_id"],
                "candidate_id": result["candidate_id"],
                "execution_allowed": True,
                "action_type": "provision",
            })
            _log.info("Created infrastructure candidate for plane %s (%s)",
                       plane.vendor, plane.plane_type)
        except Exception as e:
            _log.warning("Failed to create infra candidate for %s: %s", plane.vendor, e)

    # 3. Build reconciliation data
    aod_fabric_planes_data, aod_sor_vendors = _build_reconciliation_data(request)

    # 4. Create handoff log
    rejected_dicts = [r.to_dict() for r in rejected]
    handoff_log = create_handoff_log({
        "aod_run_id": request.run_id,
        "snapshot_name": request.snapshot_name,
        "candidates_received": len(request.candidates),
        "candidates_accepted": aod_accepted_count,
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
        candidates_accepted=aod_accepted_count,
        candidates_rejected=len(rejected),
        rejected_reasons=rejected_dicts,
        handoff_id=handoff_log["handoff_id"],
        processed_at=datetime.utcnow(),
    )
