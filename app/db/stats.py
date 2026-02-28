"""
Canonical stats — single source of truth
"""
from collections import defaultdict
from typing import Optional, Set

from . import supabase_client as sb


# Cache SOR vendor set — refreshed per stats call
_sor_vendor_cache: Optional[Set[str]] = None


def _load_sor_vendors() -> Set[str]:
    """Load SOR vendor names from sor_declarations table (AOD authority).

    AOD sends SOR declarations as a top-level array in the handoff payload.
    These are stored in sor_declarations with domain, vendor, confidence.
    """
    global _sor_vendor_cache
    try:
        rows = sb.select("sor_declarations")
        _sor_vendor_cache = {
            (r.get("vendor") or "").lower()
            for r in rows
            if r.get("vendor")
        }
    except Exception:
        _sor_vendor_cache = set()
    return _sor_vendor_cache


def _is_aod_sor(candidate: dict) -> bool:
    """Determine if a candidate is an SOR using AOD's sor_declarations (RACI-compliant).

    AOD is A/R for SOR scoring (RACI v6 row 167). AAM must use AOD's determination,
    not re-derive SOR status from category membership.

    Checks if the candidate's vendor_name matches any vendor in the sor_declarations
    table (populated by AOD during handoff).
    """
    global _sor_vendor_cache
    if _sor_vendor_cache is None:
        _load_sor_vendors()
    vendor = (candidate.get("vendor_name") or "").lower()
    if not vendor:
        return False
    return vendor in _sor_vendor_cache


def get_canonical_stats(aod_run_id: Optional[str] = None) -> dict:
    """
    Single source of truth for AAM canonical KPIs.

    All endpoints displaying stats MUST use this function to ensure consistency.

    Canonical definitions:
    - fabrics: Count of distinct fabric planes from database
    - sors: Count of AOD's sor_declarations (AOD is A/R for SOR scoring)
      Direct count from sor_declarations table, not candidate-derived
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

    # RACI v6: SOR count = AOD's sor_declarations, not category membership.
    # AOD is A/R for SOR scoring (multi-signal evidence, confidence tiers).
    # Category-based counting (old method) overcounts — 14 vs AOD's 6.
    try:
        sor_declarations = sb.select("sor_declarations")
        sors_count = len(sor_declarations)
    except Exception:
        sors_count = 0

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
