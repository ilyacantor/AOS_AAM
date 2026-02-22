"""
Candidate Matching Service — governance enforcement and evidence-based inference.

RACI v4: AAM is A/R for Fabric Plane Inference.
Uses a strict cascade: first match wins, no accumulation or averaging.
"""
from datetime import datetime
from typing import Optional

from ..logger import get_logger
from ..constants import INFRA_VENDOR_PLANE, DISPLAY_NAME_PLANE_HINTS
from ..db import (
    get_candidate,
    get_pipe,
    list_pipes,
    create_pipe,
    update_candidate_match,
)
from ..models import FabricPlane

_log = get_logger("services.matching")


def validate_aod_governance(candidate: dict, is_auto_match: bool) -> tuple[bool, str]:
    """
    Check AOD governance constraints for a candidate.
    Returns (allowed, reason).
    """
    execution_allowed = candidate.get("execution_allowed", True)
    action_type = candidate.get("action_type", "provision")
    blocking_findings = candidate.get("blocking_findings", [])

    if is_auto_match:
        if not execution_allowed:
            return False, (
                f"Auto-matching blocked by AOD governance. "
                f"Candidate has execution_allowed=False. "
                f"Blocking findings: {blocking_findings}. "
                f"Manual review and explicit pipe_id required."
            )
        if action_type == "inventory_only":
            return False, (
                f"Auto-matching blocked by AOD governance. "
                f"Candidate action_type is 'inventory_only' (requires human review). "
                f"Provide explicit pipe_id to override."
            )
    return True, ""


def infer_fabric_plane_for_candidate(candidate: dict) -> tuple[Optional[str], float, str]:
    """
    RACI-mandated inference cascade — FIRST MATCH WINS.

    Resolution order (highest to lowest confidence):
      1. AOD explicit connected_via_plane hint        → confidence 0.95
      2. INFRA_VENDOR_PLANE identity match             → confidence 0.90
      3. DISPLAY_NAME_PLANE_HINTS match                → confidence 0.80
      4. Evidence signals (evidence_refs, endpoints)   → confidence 0.70
      5. No match → needs_operator_review              → confidence 0.0

    Returns (plane_type, confidence, routing_source).
    """
    vendor = (candidate.get("vendor_name") or "").lower().strip()
    display = (candidate.get("display_name") or "").lower().strip()

    # Step 1: AOD explicit connected_via_plane hint
    aod_hint = candidate.get("connected_via_plane")
    if aod_hint:
        try:
            plane = FabricPlane(aod_hint).value
            return plane, 0.95, "aod_explicit"
        except ValueError:
            pass  # Invalid hint — fall through to next step

    # Step 2: INFRA_VENDOR_PLANE identity match (Kafka IS event bus)
    for infra_vendor, plane_type in INFRA_VENDOR_PLANE.items():
        if infra_vendor == vendor or infra_vendor in vendor:
            return plane_type, 0.90, "infra_vendor_identity"

    # Step 3: DISPLAY_NAME_PLANE_HINTS match
    for hint_keyword, plane_type in DISPLAY_NAME_PLANE_HINTS.items():
        if hint_keyword in display:
            return plane_type, 0.80, "display_name_hint"

    # Step 4: Evidence signals from AOD
    evidence_refs = candidate.get("evidence_refs") or []
    signals = (candidate.get("signals_summary") or "").lower()
    endpoints = candidate.get("known_endpoints") or []

    # Check evidence_refs for plane clues
    for ref in evidence_refs:
        ref_lower = ref.lower()
        if "ipaas" in ref_lower:
            return "IPAAS", 0.70, "evidence_signal"
        if "gateway" in ref_lower or "api_gateway" in ref_lower:
            return "API_GATEWAY", 0.70, "evidence_signal"
        if "event" in ref_lower or "streaming" in ref_lower:
            return "EVENT_BUS", 0.70, "evidence_signal"
        if "warehouse" in ref_lower or "lake" in ref_lower:
            return "DATA_WAREHOUSE", 0.70, "evidence_signal"

    # Check endpoint URLs for transport clues
    for ep in endpoints:
        ep_lower = ep.lower()
        if "kafka" in ep_lower or "amqp" in ep_lower or ":9092" in ep_lower:
            return "EVENT_BUS", 0.70, "evidence_signal"
        if "bigquery" in ep_lower or "redshift" in ep_lower or "snowflake" in ep_lower:
            return "DATA_WAREHOUSE", 0.70, "evidence_signal"

    # Step 4.5: Category-aware default for known application types.
    # This is a weak signal (0.40) — overridden by any match from steps 1-4.
    # Data/analytics apps route through DATA_WAREHOUSE; SOR-category apps
    # (CRM, ERP, HCM, etc.) typically connect via API_GATEWAY.
    category = (candidate.get("category") or "").lower().strip()
    if category in ("data", "analytics", "warehouse", "lake", "bi"):
        return "DATA_WAREHOUSE", 0.40, "category_default"
    if category in ("crm", "erp", "hcm", "idp", "itsm", "saas", "hr", "finance"):
        return "API_GATEWAY", 0.40, "category_default"

    # Step 5: No stronger signal found — default to API_GATEWAY.
    # Confidence 0.0 flags this as a low-confidence default that needs
    # operator review.  API_GATEWAY is the most common plane for SaaS apps.
    return "API_GATEWAY", 0.0, "needs_operator_review"


def find_matching_pipe(candidate: dict) -> tuple[Optional[str], float, str]:
    """
    Match candidate to an existing pipe or create a new one using the inference cascade.

    Scenario A: Match to existing pipe by vendor + plane.
    Scenario B: Create new pipe with inferred plane.

    Dedup rule: one pipe per (vendor_canonical_name, fabric_plane) pair.

    Returns (pipe_id, score, reason).
    """
    vendor = (candidate.get("vendor_name") or "").strip()
    vendor_lower = vendor.lower()
    candidate_id = candidate.get("candidate_id", "")

    # Run inference cascade to determine the fabric plane
    inferred_plane, confidence, routing_source = infer_fabric_plane_for_candidate(candidate)

    # Scenario A: Check for existing pipe matching this vendor
    existing_pipes = list_pipes(source_system=vendor)
    if existing_pipes:
        if inferred_plane:
            # If we have an inferred plane, match to the pipe on that plane
            for p in existing_pipes:
                if (p.get("fabric_plane") or "").upper() == inferred_plane:
                    return p["pipe_id"], max(confidence, 0.9), f"Matched existing pipe ({routing_source})"
        # No plane-specific match found; use first existing pipe
        return existing_pipes[0]["pipe_id"], 0.9, "Auto-matched by vendor name"

    # Scenario B: Create new pipe
    # Block auto-creation if confidence is 0.0 — no real signal, operator must assign
    if confidence == 0.0:
        return (
            None,
            0.0,
            f"Candidate {candidate_id[:8]} ({vendor}) needs operator review — "
            f"no fabric plane could be inferred with sufficient confidence. "
            f"Provide an explicit pipe_id for manual matching.",
        )

    lineage_hints = [f"candidate:{candidate_id}", f"routed_via:{inferred_plane}"]
    if candidate.get("aod_run_id"):
        lineage_hints.append(f"aod_run:{candidate['aod_run_id']}")
    if candidate.get("aod_asset_id"):
        lineage_hints.append(f"aod_asset:{candidate['aod_asset_id']}")
    lineage_hints.append(f"routing_source:{routing_source}")
    lineage_hints.append(f"confidence:{confidence}")

    # Determine transport_kind from inference
    transport_kind = "API"
    if inferred_plane == "EVENT_BUS":
        transport_kind = "EVENT_STREAM"
    elif inferred_plane == "DATA_WAREHOUSE":
        transport_kind = "TABLE"
    elif inferred_plane == "IPAAS":
        transport_kind = "WEBHOOK"

    # Determine modality
    modality = candidate.get("preferred_modality") or "DECLARED_INTERFACE"
    if inferred_plane == "EVENT_BUS":
        modality = "PASSIVE_SUBSCRIPTION"
    elif inferred_plane == "IPAAS":
        modality = "CONTROL_PLANE"

    # Build trust labels
    trust_labels = []
    if routing_source == "aod_explicit":
        trust_labels.append("inferred:aod_explicit")
    elif routing_source == "infra_vendor_identity":
        trust_labels.append("inferred:vendor_identity")
    elif routing_source == "display_name_hint":
        trust_labels.append("inferred:display_name_hint")
    elif routing_source == "evidence_signal":
        trust_labels.append("inferred:evidence_signal")
    elif routing_source == "needs_operator_review":
        trust_labels.append("needs_operator_review")

    new_pipe_data = {
        "display_name": candidate.get("display_name") or vendor,
        "source_system": vendor,
        "fabric_plane": inferred_plane,
        "modality": modality,
        "transport_kind": transport_kind,
        "trust_labels": trust_labels,
        "provenance": {
            "discovered_by": "auto-match",
            "discovered_at": datetime.utcnow().isoformat(),
            "lineage_hints": lineage_hints,
        },
    }
    result = create_pipe(new_pipe_data)
    return (
        result["pipe_id"],
        confidence,
        f"Created pipe ({vendor}) on {inferred_plane} ({routing_source}, conf={confidence})",
    )


def match_candidate(
    candidate_id: str,
    pipe_id_hint: Optional[str],
) -> dict:
    """
    Full candidate-match orchestration: governance check → find/create pipe → update candidate.
    Raises ValueError or PermissionError on failure.
    """
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Candidate not found")

    is_auto_match = pipe_id_hint is None

    # Governance check
    allowed, reason = validate_aod_governance(candidate, is_auto_match)
    if not allowed:
        raise PermissionError(reason)

    # Manual match with explicit pipe_id
    if pipe_id_hint:
        pipe = get_pipe(pipe_id_hint)
        if not pipe:
            raise ValueError("Pipe not found")

        pipe_id = pipe_id_hint
        score = 1.0
        match_reason = "Manual match"
        fabric_plane = pipe.get("fabric_plane")
    else:
        # Auto-match via inference cascade
        pipe_id, score, match_reason = find_matching_pipe(candidate)
        if not pipe_id:
            raise ValueError(match_reason)

        # Run inference cascade to determine the fabric plane.
        # This is critical because list_pipes() returns candidates-as-pipes,
        # which may have UNMAPPED planes. The inference cascade provides the
        # RACI-mandated plane assignment.
        inferred_plane, inferred_conf, routing_source = infer_fabric_plane_for_candidate(candidate)
        matched_pipe = get_pipe(pipe_id)
        existing_plane = matched_pipe.get("fabric_plane") if matched_pipe else None

        # Use inference result if existing plane is empty/UNMAPPED
        if inferred_plane and (not existing_plane or existing_plane == "UNMAPPED"):
            fabric_plane = inferred_plane
        else:
            fabric_plane = existing_plane

    updated = update_candidate_match(
        candidate_id, pipe_id, score, match_reason,
        fabric_plane=fabric_plane,
    )
    if not updated:
        raise RuntimeError("Failed to update candidate")

    return {
        "candidate_id": candidate_id,
        "matched_pipe_id": pipe_id,
        "match_score": score,
        "match_reason": match_reason,
        "status": "connected",
    }
