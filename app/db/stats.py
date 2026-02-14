"""
Canonical stats — single source of truth
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# CANONICAL STATS - SINGLE SOURCE OF TRUTH
# ============================================================================

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
    conn = get_connection()
    cursor = conn.cursor()

    # Build WHERE clause for optional run filtering
    run_filter = ""
    run_params = ()
    if aod_run_id:
        run_filter = "WHERE aod_run_id = ?"
        run_params = (aod_run_id,)

    # FABRICS: Count of distinct fabric planes from database
    if aod_run_id:
        cursor.execute("SELECT COUNT(*) FROM fabric_planes WHERE aod_run_id = ?", (aod_run_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM fabric_planes")
    fabrics_count = cursor.fetchone()[0]

    # SORs: Candidates with System of Record categories
    from ..constants import SOR_CATEGORIES
    sor_categories = list(SOR_CATEGORIES)
    placeholders = ','.join('?' * len(sor_categories))

    if aod_run_id:
        cursor.execute(f"""
            SELECT COUNT(*) FROM connection_candidates
            WHERE aod_run_id = ? AND LOWER(category) IN ({placeholders})
        """, (aod_run_id, *sor_categories))
    else:
        cursor.execute(f"""
            SELECT COUNT(*) FROM connection_candidates
            WHERE LOWER(category) IN ({placeholders})
        """, sor_categories)
    sors_count = cursor.fetchone()[0]

    # TOTAL CANDIDATES (= PIPES by canonical definition)
    if aod_run_id:
        cursor.execute("SELECT COUNT(*) FROM connection_candidates WHERE aod_run_id = ?", (aod_run_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM connection_candidates")
    total_candidates = cursor.fetchone()[0]

    # PIPES WITH DRIFT: Candidates with open drift events
    cursor.execute("""
        SELECT COUNT(DISTINCT d.pipe_id) FROM drift_events d
        WHERE d.status = 'OPEN'
    """)
    pipes_with_drift = cursor.fetchone()[0]

    # FABRIC BREAKDOWN by type (for detailed views)
    if aod_run_id:
        cursor.execute("""
            SELECT plane_type, COUNT(*) as count
            FROM fabric_planes
            WHERE aod_run_id = ?
            GROUP BY plane_type
        """, (aod_run_id,))
    else:
        cursor.execute("""
            SELECT plane_type, COUNT(*) as count
            FROM fabric_planes
            GROUP BY plane_type
        """)
    fabrics_by_type = {row[0]: row[1] for row in cursor.fetchall()}

    conn.close()

    return {
        # Canonical fields - these MUST match UI expectations
        "fabrics": fabrics_count,
        "sors": sors_count,
        "total_candidates": total_candidates,
        "pipes_with_drift": pipes_with_drift,
        # Extended info for detailed views
        "fabrics_by_type": fabrics_by_type,
        # Aliases for backward compatibility
        "total_pipes": total_candidates,  # candidates = pipes
        "pipes": total_candidates
    }
