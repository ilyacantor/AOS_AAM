"""
SOR Disposition operations — store and retrieve operator disposition
actions on SOR reconciliation line items.
"""
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def set_sor_disposition(vendor: str, aod_run_id: str, status: str,
                        reason: Optional[str] = None,
                        operator_notes: Optional[str] = None) -> dict:
    now = datetime.utcnow().isoformat()
    vendor_lower = vendor.lower().strip()

    existing = sb.select(
        "sor_dispositions",
        filters={"sor_vendor": vendor_lower, "aod_run_id": aod_run_id},
        single=True,
    )

    if existing:
        sb.update(
            "sor_dispositions",
            {
                "status": status,
                "reason": reason,
                "operator_notes": operator_notes,
                "updated_at": now,
            },
            filters={"sor_vendor": vendor_lower, "aod_run_id": aod_run_id},
        )
        disposition_id = existing.get("disposition_id")
    else:
        disposition_id = str(uuid.uuid4())
        sb.insert("sor_dispositions", {
            "disposition_id": disposition_id,
            "sor_vendor": vendor_lower,
            "aod_run_id": aod_run_id,
            "status": status,
            "reason": reason,
            "operator_notes": operator_notes,
            "created_at": now,
            "updated_at": now,
        })

    return {"disposition_id": disposition_id, "status": status, "updated_at": now}


def get_sor_dispositions(aod_run_id: str) -> dict:
    rows = sb.select(
        "sor_dispositions",
        filters={"aod_run_id": aod_run_id},
    )

    result = {}
    for row in rows:
        result[row["sor_vendor"]] = {
            "status": row.get("status"),
            "reason": row.get("reason"),
            "operator_notes": row.get("operator_notes"),
            "updated_at": row.get("updated_at"),
        }

    return result
