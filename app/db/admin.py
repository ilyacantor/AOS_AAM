"""
Preset/seed data admin operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection, get_db

# ============================================================================
# PRESET / SEED DATA OPERATIONS
# ============================================================================

def reset_aod_state():
    """
    Clear candidate/fabric/SOR data so a fresh handoff can repopulate it.

    Preserves collectors (infrastructure config) only.
    The handoff log must be cleared because process_handoff() uses it for
    idempotency checks — a stale log entry would short-circuit re-ingestion.
    """
    # Tables whose rows are repopulated on each handoff
    ALLOWED_TABLES = frozenset({
        "drift_events",
        "pipe_versions",
        "declared_pipes",
        "observations",
        "collector_runs",
        "connection_candidates",
        "tee_requests",
        "fabric_planes",
        "sor_declarations",
        "sor_dispositions",
        "aod_policy_manifest",
        "aod_handoff_log",
    })

    with get_db() as conn:
        cursor = conn.cursor()
        counts = {}
        for table in ALLOWED_TABLES:
            assert table in ALLOWED_TABLES, f"Disallowed table: {table}"
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]
            cursor.execute(f"DELETE FROM {table}")

    total_deleted = sum(counts.values())
    return {"reset": True, "tables_cleared": counts, "total_rows_deleted": total_deleted}


def clear_all_data():
    """Alias for reset_aod_state — clears repopulated tables."""
    return reset_aod_state()


def get_pipe_stats() -> dict:
    """Get statistics about pipes by fabric_plane and modality.

    Queries connection_candidates (the single source of truth) instead of
    declared_pipes.
    """
    conn = get_connection()
    cursor = conn.cursor()

    stats = {
        "total_pipes": 0,
        "by_fabric_plane": {},
        "by_modality": {},
        "by_source_system": {}
    }

    cursor.execute("SELECT COUNT(*) FROM connection_candidates")
    stats["total_pipes"] = cursor.fetchone()[0]

    # Fabric plane comes from connected_via_plane or fabric_planes JOIN
    cursor.execute("""
        SELECT COALESCE(UPPER(fp.plane_type), UPPER(c.connected_via_plane), 'UNMAPPED') as plane,
               COUNT(*) as cnt
        FROM connection_candidates c
        LEFT JOIN fabric_planes fp ON c.fabric_plane_id = fp.plane_id
        GROUP BY plane
    """)
    for row in cursor.fetchall():
        stats["by_fabric_plane"][row[0] or "UNMAPPED"] = row[1]

    cursor.execute("""
        SELECT COALESCE(c.category, 'unknown') as cat, COUNT(*) as cnt
        FROM connection_candidates c
        GROUP BY cat
    """)
    for row in cursor.fetchall():
        stats["by_modality"][row[0]] = row[1]

    cursor.execute("""
        SELECT vendor_name, COUNT(*) as cnt
        FROM connection_candidates
        GROUP BY vendor_name
    """)
    for row in cursor.fetchall():
        stats["by_source_system"][row[0]] = row[1]

    conn.close()
    return stats


