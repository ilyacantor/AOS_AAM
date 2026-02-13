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
      1. Exact vendor name match to existing pipe
      2. Create pipe with fabric plane (candidate has AOD plane hint)
      3. Create pipe without fabric plane (candidate has no routing info)

    Returns (pipe_id, score, reason).
    """
    vendor = candidate.get("vendor_name", "").lower()
    candidate_id = candidate.get("candidate_id", "")

    # Strategy 1: Exact vendor name match
    pipes = list_pipes(source_system=candidate.get("vendor_name"))
    if pipes:
        return pipes[0]["pipe_id"], 0.9, "Auto-matched by vendor name"

    # Build lineage for either Strategy 2 or 3
    lineage_hints = [f"candidate:{candidate_id}"]
    if candidate.get("aod_run_id"):
        lineage_hints.append(f"aod_run:{candidate.get('aod_run_id')}")
    if candidate.get("aod_asset_id"):
        lineage_hints.append(f"aod_asset:{candidate.get('aod_asset_id')}")

    # Strategy 2: Create pipe with fabric plane (AOD routing hint)
    aod_plane_hint = candidate.get("connected_via_plane")
    fabric_plane = None
    if aod_plane_hint:
        try:
            routed_plane = FabricPlane(aod_plane_hint)
            fabric_plane = routed_plane.value
            lineage_hints.append(f"routed_via:{fabric_plane}")
            lineage_hints.append("routing_source:aod_hint")
        except ValueError:
            _log.warning("Invalid AOD plane hint '%s' for candidate %s, creating pipe without plane",
                         aod_plane_hint, candidate_id)

    # Strategy 3: Create pipe without plane (no routing info — candidate
    # becomes "connected" but stays UNMAPPED until operator or AOD routes it)
    if not fabric_plane:
        lineage_hints.append("routing_source:unrouted")

    new_pipe_data = {
        "display_name": candidate.get("display_name") or candidate.get("vendor_name"),
        "source_system": candidate.get("vendor_name"),
        "fabric_plane": fabric_plane,
        "modality": candidate.get("preferred_modality") or "DECLARED_INTERFACE",
        "transport_kind": "API",
        "provenance": {
            "discovered_by": "auto-match",
            "discovered_at": datetime.utcnow().isoformat(),
            "lineage_hints": lineage_hints,
        },
    }
    result = create_pipe(new_pipe_data)
    score = 0.6 if fabric_plane else 0.4
    reason = (
        f"Created pipe from candidate ({candidate.get('vendor_name')}) via {fabric_plane}"
        if fabric_plane
        else f"Created pipe from candidate ({candidate.get('vendor_name')}), no plane routing"
    )
    return result["pipe_id"], score, reason


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
