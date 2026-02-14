"""
Drift status operations (v1)
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# DRIFT STATUS OPERATIONS (v1 Practical Interface)
# ============================================================================

def update_drift_status(drift_id: str, status: str, by: Optional[str] = None, notes: Optional[str] = None) -> Optional[dict]:
    """Update drift event status (open, acknowledged, suppressed, resolved)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    if status == "acknowledged":
        cursor.execute("""
            UPDATE drift_events 
            SET status = ?, acknowledged_at = ?, acknowledged_by = ?, notes = COALESCE(?, notes)
            WHERE drift_id = ?
        """, (status, now, by, notes, drift_id))
    elif status == "suppressed":
        cursor.execute("""
            UPDATE drift_events 
            SET status = ?, suppressed_at = ?, suppressed_by = ?, notes = COALESCE(?, notes)
            WHERE drift_id = ?
        """, (status, now, by, notes, drift_id))
    else:
        cursor.execute("""
            UPDATE drift_events 
            SET status = ?, notes = COALESCE(?, notes)
            WHERE drift_id = ?
        """, (status, notes, drift_id))
    
    affected = cursor.rowcount
    conn.commit()
    
    if affected > 0:
        cursor.execute("SELECT * FROM drift_events WHERE drift_id = ?", (drift_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return _row_to_drift_event(row)
    
    conn.close()
    return None


