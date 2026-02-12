"""
SOR Declaration operations — store and retrieve authoritative SOR
declarations from Farm (via AOD handoff).
"""
from datetime import datetime
from typing import Optional

from .connection import get_connection


def store_sor_declaration(sor_data: dict, aod_run_id: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    domain = sor_data.get("domain", "").upper()
    vendor = sor_data.get("vendor", "")
    sor_id = f"sor:{domain.lower()}:{vendor.lower()}"
    now = datetime.utcnow().isoformat()

    cursor.execute("DELETE FROM sor_declarations WHERE sor_id = ?", (sor_id,))
    cursor.execute("""
        INSERT INTO sor_declarations (
            sor_id, domain, vendor, category, confidence, source,
            aod_run_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sor_id,
        domain,
        vendor,
        sor_data.get("category", ""),
        sor_data.get("confidence", "high"),
        sor_data.get("source", "farm"),
        aod_run_id,
        now,
        now,
    ))

    conn.commit()
    conn.close()
    return {"sor_id": sor_id, "stored_at": now}


def get_sor_declarations(aod_run_id: Optional[str] = None) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()

    if aod_run_id:
        cursor.execute("SELECT * FROM sor_declarations WHERE aod_run_id = ?", (aod_run_id,))
    else:
        cursor.execute("SELECT * FROM sor_declarations ORDER BY domain")

    rows = cursor.fetchall()
    conn.close()

    return [{
        "sor_id": row["sor_id"],
        "domain": row["domain"],
        "vendor": row["vendor"],
        "category": row["category"],
        "confidence": row["confidence"],
        "source": row["source"],
        "aod_run_id": row["aod_run_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    } for row in rows]


def clear_sor_declarations(aod_run_id: Optional[str] = None):
    conn = get_connection()
    cursor = conn.cursor()
    if aod_run_id:
        cursor.execute("DELETE FROM sor_declarations WHERE aod_run_id = ?", (aod_run_id,))
    else:
        cursor.execute("DELETE FROM sor_declarations")
    conn.commit()
    conn.close()
