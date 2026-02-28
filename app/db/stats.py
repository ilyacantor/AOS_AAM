"""
Canonical stats — single source of truth
"""
import json
from collections import defaultdict
from typing import Optional

from . import supabase_client as sb
from ..constants import SOR_CATEGORIES


def _is_aod_sor(candidate: dict) -> bool:
    """Determine if a candidate is an SOR using AOD's sor_tagging (RACI-compliant).

    AOD is A/R for SOR scoring (RACI v6 row 167). AAM must use AOD's determination,
    not re-derive SOR status from category membership.

    The sor_tagging field may contain:
    - A JSON object with 'confidence' or 'domain' fields (from AOD's CandidateSORTagging)
    - A simple string like 'customer_master' (legacy format, indicates SOR)
    - None (not an SOR or infrastructure candidate)
    """
    raw = candidate.get("sor_tagging")
    if not raw:
        return False

    # Try JSON parse (AOD sends CandidateSORTagging as structured object)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                # CandidateSORTagging has 'confidence' field: "high", "medium", "low", "none"
                conf = (parsed.get("confidence") or "").lower()
                if conf in ("high", "medium"):
                    return True
                # Also check 'domain' — presence of a domain indicates SOR identification
                if parsed.get("domain"):
                    return True
                return False
        except (json.JSONDecodeError, ValueError):
            pass
        # Legacy string format — any non-empty sor_tagging string means AOD identified it as SOR
        return True

    # Dict (if somehow stored as dict rather than string)
    if isinstance(raw, dict):
        conf = (raw.get("confidence") or "").lower()
        if conf in ("high", "medium"):
            return True
        if raw.get("domain"):
            return True
        return False

    return False


def get_canonical_stats(aod_run_id: Optional[str] = None) -> dict:
    """
    Single source of truth for AAM canonical KPIs.

    All endpoints displaying stats MUST use this function to ensure consistency.

    Canonical definitions:
    - fabrics: Count of distinct fabric planes from database
    - sors: Count of candidates identified as SORs by AOD's sor_tagging
      (RACI v6: AOD is A/R for SOR scoring, not AAM)
    - total_candidates: All candidates (candidates = pipes by canonical definition)
    - pipes_with_drift: Count of declared pipes with drift_status = 'OPEN'

    Args:
        aod_run_id: Optional filter by AOD run. If None, returns stats for all data.

    Returns:
        dict with canonical stat fields that match UI expectations
    """
    if aod_run_id:
        fabric_planes = sb.select("fabric_planes", filters={"aod_run_id": aod_run_id})
        candidates = sb.select("connection_candidates", filters={"aod_run_id": aod_run_id})
    else:
        fabric_planes = sb.select("fabric_planes")
        candidates = sb.select("connection_candidates")

    fabrics_count = len(fabric_planes)

    # RACI v6: Use AOD's sor_tagging to count SORs, not category membership.
    # AOD performs multi-signal SOR scoring with evidence-backed confidence.
    # Category-based counting (old method) overcounts because it treats every
    # CRM/ERP/HCM candidate as an SOR regardless of AOD's assessment.
    sors_count = sum(1 for c in candidates if _is_aod_sor(c))

    total_candidates = len(candidates)

    drift_events = sb.select("drift_events")
    drift_pipe_ids = set()
    for d in drift_events:
        s = (d.get("status") or "").lower()
        if s == "open":
            drift_pipe_ids.add(d.get("pipe_id"))
    pipes_with_drift = len(drift_pipe_ids)

    fabrics_by_type: dict[str, int] = defaultdict(int)
    for fp in fabric_planes:
        pt = fp.get("plane_type") or "unknown"
        fabrics_by_type[pt] += 1

    return {
        "fabrics": fabrics_count,
        "sors": sors_count,
        "total_candidates": total_candidates,
        "pipes_with_drift": pipes_with_drift,
        "fabrics_by_type": dict(fabrics_by_type),
    }
