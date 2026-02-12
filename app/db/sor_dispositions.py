"""
SOR Disposition operations — store and retrieve operator disposition
actions on SOR reconciliation line items.
"""
import uuid
from datetime import datetime
from typing import Optional

from .connection import get_connection


def set_sor_disposition(vendor: str, aod_run_id: str, status: str,
                        reason: Optional[str] = None,
                        operator_notes: Optional[str] = None) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.utcnow().isoformat()
    vendor_lower = vendor.lower().strip()

    cursor.execute(
        "SELECT disposition_id FROM sor_dispositions WHERE sor_vendor = ? AND aod_run_id = ?",
        (vendor_lower, aod_run_id),
    )
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE sor_dispositions
            SET status = ?, reason = ?, operator_notes = ?, updated_at = ?
            WHERE sor_vendor = ? AND aod_run_id = ?
        """, (status, reason, operator_notes, now, vendor_lower, aod_run_id))
        disposition_id = existing[0]
    else:
        disposition_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO sor_dispositions (
                disposition_id, sor_vendor, aod_run_id, status, reason,
                operator_notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (disposition_id, vendor_lower, aod_run_id, status, reason,
              operator_notes, now, now))

    conn.commit()
    conn.close()
    return {"disposition_id": disposition_id, "status": status, "updated_at": now}


def get_sor_dispositions(aod_run_id: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sor_vendor, status, reason, operator_notes, updated_at
        FROM sor_dispositions
        WHERE aod_run_id = ?
    """, (aod_run_id,))

    result = {}
    for row in cursor.fetchall():
        result[row[0]] = {
            "status": row[1],
            "reason": row[2],
            "operator_notes": row[3],
            "updated_at": row[4],
        }

    conn.close()
    return result
