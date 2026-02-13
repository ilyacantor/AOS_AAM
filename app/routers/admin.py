"""
Admin Router — clear data, debug, and diagnostic endpoints.
"""
from fastapi import APIRouter

from ..db import clear_all_data, get_connection, get_canonical_stats
from ..constants import SOR_CATEGORIES

router = APIRouter(tags=["Admin"])


@router.delete("/api/data")
async def clear_data():
    """Clear all data (use with caution)."""
    result = clear_all_data()
    return {"message": "All data cleared", **result}


@router.get("/api/debug/handoff-state", tags=["Debug"])
async def debug_handoff_state():
    """Diagnostic endpoint to inspect the current state of AOD handoff data."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM fabric_planes ORDER BY created_at DESC LIMIT 10")
    fabric_planes = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) FROM fabric_planes")
    fabric_plane_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM connection_candidates")
    total_candidates = cursor.fetchone()[0]

    cursor.execute("""
        SELECT category, COUNT(*) as count
        FROM connection_candidates
        GROUP BY category
        ORDER BY count DESC
        LIMIT 20
    """)
    category_dist = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT
            CASE WHEN fabric_plane_id IS NULL OR fabric_plane_id = '' THEN 'unassigned' ELSE 'assigned' END as status,
            COUNT(*) as count
        FROM connection_candidates
        GROUP BY status
    """)
    assignment_stats = {row[0]: row[1] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT candidate_id, vendor_name, category, fabric_plane_id, connected_via_plane
        FROM connection_candidates
        WHERE fabric_plane_id IS NOT NULL AND fabric_plane_id != ''
        LIMIT 5
    """)
    assigned_samples = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT candidate_id, vendor_name, category, fabric_plane_id, connected_via_plane
        FROM connection_candidates
        WHERE fabric_plane_id IS NULL OR fabric_plane_id = ''
        LIMIT 5
    """)
    unassigned_samples = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT aod_run_id, snapshot_name, candidates_received, candidates_accepted, handoff_timestamp
        FROM aod_handoff_log
        ORDER BY handoff_timestamp DESC
        LIMIT 5
    """)
    handoff_logs = [dict(row) for row in cursor.fetchall()]

    canonical_stats = get_canonical_stats()
    conn.close()

    return {
        "summary": {
            "fabric_planes_stored": fabric_plane_count,
            "total_candidates": total_candidates,
            "candidates_with_plane": assignment_stats.get("assigned", 0),
            "candidates_without_plane": assignment_stats.get("unassigned", 0),
        },
        "canonical_stats": canonical_stats,
        "category_distribution": category_dist,
        "fabric_planes": fabric_planes,
        "assigned_candidate_samples": assigned_samples,
        "unassigned_candidate_samples": unassigned_samples,
        "recent_handoff_logs": handoff_logs,
        "diagnosis": {
            "fabric_planes_missing": fabric_plane_count == 0,
            "all_candidates_unassigned": assignment_stats.get("assigned", 0) == 0 and total_candidates > 0,
            "no_sor_categories": not any(
                cat.lower() in SOR_CATEGORIES for cat in category_dist.keys()
            ),
        },
    }
