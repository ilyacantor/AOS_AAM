"""
Canonical stats — single source of truth
"""
from collections import defaultdict
from typing import Optional

from . import supabase_client as sb
from ..constants import SOR_CATEGORIES


def get_canonical_stats(aod_run_id: Optional[str] = None) -> dict:
    """
    Single source of truth for AAM canonical KPIs.

    All endpoints displaying stats MUST use this function to ensure consistency.

    Canonical definitions:
    - fabrics: Count of distinct fabric planes from database
    - sors: Count of candidates with SOR categories (crm, erp, hcm, idp, itsm)
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

    sor_categories = SOR_CATEGORIES
    sors_count = sum(
        1 for c in candidates
        if (c.get("category") or "").lower() in sor_categories
    )

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
