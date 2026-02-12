"""
Candidate Matching Service — governance enforcement and auto-matching strategies.
"""
from datetime import datetime
from typing import Optional

from ..logger import get_logger
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


def find_matching_pipe(candidate: dict) -> tuple[Optional[str], float, str]:
    """
    Auto-matching strategies:
      1. Exact vendor name match
      2. Create new pipe from candidate (only if AOD sent a plane hint)

    Returns (pipe_id, score, reason).
    """
    vendor = candidate.get("vendor_name", "").lower()
    candidate_id = candidate.get("candidate_id", "")

    # Strategy 1: Exact vendor name match
    pipes = list_pipes(source_system=candidate.get("vendor_name"))
    if pipes:
        return pipes[0]["pipe_id"], 0.9, "Auto-matched by vendor name"

    # Strategy 2: Create new pipe from candidate (requires AOD plane hint)
    all_pipes = list_pipes(limit=1000)
    if all_pipes:
        aod_plane_hint = candidate.get("connected_via_plane")

        if aod_plane_hint:
            try:
                routed_plane = FabricPlane(aod_plane_hint)
                routing_source = "aod_hint"
            except ValueError:
                return None, 0.0, f"Cannot create pipe: AOD plane hint '{aod_plane_hint}' is not a valid FabricPlane"
        else:
            return None, 0.0, "Cannot create pipe: no fabric plane hint from AOD"

        lineage_hints = [f"candidate:{candidate_id}", f"routed_via:{routed_plane.value}"]
        if candidate.get("aod_run_id"):
            lineage_hints.append(f"aod_run:{candidate.get('aod_run_id')}")
        if candidate.get("aod_asset_id"):
            lineage_hints.append(f"aod_asset:{candidate.get('aod_asset_id')}")
        lineage_hints.append(f"routing_source:{routing_source}")

        new_pipe_data = {
            "display_name": candidate.get("display_name") or candidate.get("vendor_name"),
            "source_system": candidate.get("vendor_name"),
            "fabric_plane": routed_plane.value,
            "modality": candidate.get("preferred_modality") or "DECLARED_INTERFACE",
            "transport_kind": "API",
            "provenance": {
                "discovered_by": "auto-match",
                "discovered_at": datetime.utcnow().isoformat(),
                "lineage_hints": lineage_hints,
            },
        }
        result = create_pipe(new_pipe_data)
        return (
            result["pipe_id"],
            0.6,
            f"Created new pipe from candidate ({candidate.get('vendor_name')}) via {routed_plane.value} ({routing_source})",
        )

    return None, 0.0, "Auto-match failed and no pipes exist"


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
    else:
        # Auto-match
        pipe_id, score, match_reason = find_matching_pipe(candidate)
        if not pipe_id:
            raise ValueError(match_reason)

    # Resolve the matched pipe's fabric_plane and propagate to the candidate
    # so the topology view shows the correct plane linkage
    matched_pipe = get_pipe(pipe_id)
    fabric_plane = matched_pipe.get("fabric_plane") if matched_pipe else None

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
