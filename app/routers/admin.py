"""
Admin Router — clear data, debug, and diagnostic endpoints.
"""
from fastapi import APIRouter

from ..db import clear_all_data, clear_runner_jobs, get_canonical_stats
from ..db import supabase_client as sb
from ..constants import SOR_CATEGORIES

router = APIRouter(tags=["Admin"])


@router.delete("/api/data")
async def clear_data():
    """Clear all data (use with caution)."""
    result = clear_all_data()
    return {"message": "All data cleared", **result}


@router.delete("/api/runner-jobs")
async def clear_jobs():
    """Clear all runner jobs to resolve 'already exist' conflicts.

    Use this before re-dispatching pipes when you see 'Runner jobs already exist' errors.
    Deletes all rows from runner_jobs table regardless of status.
    """
    result = clear_runner_jobs()
    if result.get("cleared"):
        return {
            "message": f"Cleared {result['jobs_deleted']} runner jobs",
            **result
        }
    else:
        return {"message": "Failed to clear runner jobs", **result}


@router.get("/api/debug/handoff-state", tags=["Debug"])
async def debug_handoff_state():
    """Diagnostic endpoint to inspect the current state of AOD handoff data."""
    fabric_planes = sb.select("fabric_planes", order="created_at.desc", limit=10)
    fabric_plane_count = len(sb.select("fabric_planes"))

    candidates = sb.select("connection_candidates")
    total_candidates = len(candidates)

    category_dist = {}
    for c in candidates:
        cat = c.get("category", "unknown")
        category_dist[cat] = category_dist.get(cat, 0) + 1

    assigned = sum(1 for c in candidates if c.get("fabric_plane_id"))
    unassigned = total_candidates - assigned

    assigned_samples = [
        {"candidate_id": c["candidate_id"], "vendor_name": c["vendor_name"],
         "category": c["category"], "fabric_plane_id": c.get("fabric_plane_id"),
         "connected_via_plane": c.get("connected_via_plane")}
        for c in candidates if c.get("fabric_plane_id")
    ][:5]

    unassigned_samples = [
        {"candidate_id": c["candidate_id"], "vendor_name": c["vendor_name"],
         "category": c["category"], "fabric_plane_id": c.get("fabric_plane_id"),
         "connected_via_plane": c.get("connected_via_plane")}
        for c in candidates if not c.get("fabric_plane_id")
    ][:5]

    handoff_logs = sb.select("aod_handoff_log", order="handoff_timestamp.desc", limit=5)

    canonical_stats = get_canonical_stats()

    return {
        "summary": {
            "fabric_planes_stored": fabric_plane_count,
            "total_candidates": total_candidates,
            "candidates_with_plane": assigned,
            "candidates_without_plane": unassigned,
        },
        "canonical_stats": canonical_stats,
        "category_distribution": dict(sorted(category_dist.items(), key=lambda x: -x[1])[:20]),
        "fabric_planes": fabric_planes,
        "assigned_candidate_samples": assigned_samples,
        "unassigned_candidate_samples": unassigned_samples,
        "recent_handoff_logs": handoff_logs,
        "diagnosis": {
            "fabric_planes_missing": fabric_plane_count == 0,
            "all_candidates_unassigned": assigned == 0 and total_candidates > 0,
            "no_sor_categories": not any(
                cat.lower() in SOR_CATEGORIES for cat in category_dist.keys()
            ),
        },
    }
