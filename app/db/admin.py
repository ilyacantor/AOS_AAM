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
    repopulated_tables = [
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
    ]

    with get_db() as conn:
        cursor = conn.cursor()
        counts = {}
        for table in repopulated_tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]
            cursor.execute(f"DELETE FROM {table}")

    total_deleted = sum(counts.values())
    return {"reset": True, "tables_cleared": counts, "total_rows_deleted": total_deleted}


def clear_all_data():
    """Alias for reset_aod_state — clears repopulated tables."""
    return reset_aod_state()


def get_pipe_stats() -> dict:
    """Get statistics about pipes by fabric_plane and modality"""
    conn = get_connection()
    cursor = conn.cursor()

    stats = {
        "total_pipes": 0,
        "by_fabric_plane": {},
        "by_modality": {},
        "by_source_system": {}
    }

    cursor.execute("SELECT COUNT(*) FROM declared_pipes")
    stats["total_pipes"] = cursor.fetchone()[0]

    cursor.execute("SELECT fabric_plane, COUNT(*) as cnt FROM declared_pipes GROUP BY fabric_plane")
    for row in cursor.fetchall():
        plane = row["fabric_plane"] or "UNMAPPED"
        stats["by_fabric_plane"][plane] = row["cnt"]

    cursor.execute("SELECT modality, COUNT(*) as cnt FROM declared_pipes GROUP BY modality")
    for row in cursor.fetchall():
        stats["by_modality"][row["modality"]] = row["cnt"]

    cursor.execute("SELECT source_system, COUNT(*) as cnt FROM declared_pipes GROUP BY source_system")
    for row in cursor.fetchall():
        stats["by_source_system"][row["source_system"]] = row["cnt"]

    conn.close()
    return stats


