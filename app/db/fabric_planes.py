"""
Fabric plane operations
"""
from datetime import datetime
from typing import Optional

from . import supabase_client as sb

# ============================================================================
# FABRIC PLANE OPERATIONS
# ============================================================================

def store_fabric_plane(plane_data: dict, aod_run_id: str) -> dict:
    """Store a fabric plane from AOD"""
    plane_data["plane_type"] = (plane_data.get("plane_type") or "").upper()
    plane_id = f"{plane_data['plane_type']}:{plane_data['vendor']}"
    now = datetime.utcnow().isoformat()

    is_healthy = bool(plane_data.get("is_healthy", True))

    sb.delete("fabric_planes", filters={"plane_id": plane_id})

    sb.insert("fabric_planes", {
        "plane_id": plane_id,
        "plane_type": plane_data["plane_type"],
        "vendor": plane_data["vendor"],
        "display_name": plane_data.get("display_name", f"{plane_data['vendor']} {plane_data['plane_type']}"),
        "domain": plane_data.get("domain"),
        "managed_asset_count": plane_data.get("managed_asset_count", 0),
        "is_healthy": is_healthy,
        "aod_run_id": aod_run_id,
        "created_at": now,
        "updated_at": now,
    })

    return {"plane_id": plane_id, "stored_at": now}


def get_fabric_planes(aod_run_id: Optional[str] = None) -> list[dict]:
    """Get fabric planes, optionally filtered by AOD run"""
    filters = {}
    if aod_run_id:
        filters["aod_run_id"] = aod_run_id

    rows = sb.select(
        "fabric_planes",
        filters=filters if filters else None,
        order="updated_at.desc",
    )

    return [{
        "plane_id": row["plane_id"],
        "plane_type": row["plane_type"],
        "vendor": row["vendor"],
        "display_name": row["display_name"],
        "domain": row.get("domain"),
        "managed_asset_count": row.get("managed_asset_count"),
        "is_healthy": row.get("is_healthy"),
        "aod_run_id": row.get("aod_run_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    } for row in rows]


def find_fabric_plane_by_vendor(vendor: str, plane_type: Optional[str] = None) -> Optional[dict]:
    """Find a fabric plane by vendor (and optionally type)"""
    filters = {"vendor": vendor}
    if plane_type:
        filters["plane_type"] = plane_type

    rows = sb.select(
        "fabric_planes",
        filters=filters,
        order="updated_at.desc",
        limit=1,
    )

    if rows:
        row = rows[0]
        return {
            "plane_id": row["plane_id"],
            "plane_type": row["plane_type"],
            "vendor": row["vendor"],
            "display_name": row["display_name"],
            "domain": row.get("domain"),
            "managed_asset_count": row.get("managed_asset_count"),
            "is_healthy": row.get("is_healthy"),
        }
    return None
