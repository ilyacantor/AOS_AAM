"""
SOR Declaration operations — store and retrieve authoritative SOR
declarations from Farm (via AOD handoff).
"""
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def store_sor_declaration(sor_data: dict, aod_run_id: str) -> dict:
    domain = sor_data.get("domain", "").upper()
    vendor = sor_data.get("vendor", "")
    sor_id = f"sor:{domain.lower()}:{vendor.lower()}"
    now = datetime.utcnow().isoformat()

    sb.delete("sor_declarations", filters={"sor_id": sor_id})

    data = {
        "sor_id": sor_id,
        "domain": domain,
        "vendor": vendor,
        "category": sor_data.get("category", ""),
        "confidence": sor_data.get("confidence", "high"),
        "source": sor_data.get("source", "farm"),
        "aod_run_id": aod_run_id,
        "created_at": now,
        "updated_at": now,
    }

    sb.insert("sor_declarations", data)

    return {"sor_id": sor_id, "stored_at": now}


def get_sor_declarations(aod_run_id: Optional[str] = None) -> list[dict]:
    filters = {}
    if aod_run_id:
        filters["aod_run_id"] = aod_run_id

    rows = sb.select(
        "sor_declarations",
        filters=filters if filters else None,
        order="domain.asc",
    )

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


def clear_sor_declarations(aod_run_id: str) -> None:
    """Delete all SOR declarations for a specific AOD run."""
    sb.delete("sor_declarations", filters={"aod_run_id": aod_run_id})
