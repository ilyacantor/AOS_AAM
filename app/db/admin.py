"""
Preset/seed data admin operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# PRESET / SEED DATA OPERATIONS
# ============================================================================

def reset_aod_state():
    """Full reset of all prior run state. Called before fetching new AOD data."""
    conn = get_connection()
    cursor = conn.cursor()
    
    tables = [
        "drift_events",
        "pipe_versions",
        "declared_pipes",
        "observations",
        "collector_runs",
        "connection_candidates",
        "tee_requests",
        "fabric_planes",
        "aod_handoff_log",
        "aod_policy_manifest",
        "collectors",
    ]
    
    counts = {}
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = cursor.fetchone()[0]
        cursor.execute(f"DELETE FROM {table}")
    
    conn.commit()
    conn.close()
    
    total_deleted = sum(counts.values())
    return {"reset": True, "tables_cleared": counts, "total_rows_deleted": total_deleted}


def clear_all_data():
    """Clear all data from the database (for preset loading)"""
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

    cursor.execute("SELECT fabric_plane, COUNT(*) FROM declared_pipes GROUP BY fabric_plane")
    for row in cursor.fetchall():
        plane = row[0] or "API_GATEWAY"
        stats["by_fabric_plane"][plane] = row[1]

    cursor.execute("SELECT modality, COUNT(*) FROM declared_pipes GROUP BY modality")
    for row in cursor.fetchall():
        stats["by_modality"][row[0]] = row[1]

    cursor.execute("SELECT source_system, COUNT(*) FROM declared_pipes GROUP BY source_system")
    for row in cursor.fetchall():
        stats["by_source_system"][row[0]] = row[1]

    conn.close()
    return stats


