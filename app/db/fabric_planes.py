"""
Fabric plane operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# FABRIC PLANE OPERATIONS
# ============================================================================

def store_fabric_plane(plane_data: dict, aod_run_id: str) -> dict:
    """Store a fabric plane from AOD"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Normalize plane_type to uppercase
    plane_data["plane_type"] = (plane_data.get("plane_type") or "").upper()
    plane_id = f"{plane_data['plane_type']}:{plane_data['vendor']}"
    now = datetime.utcnow().isoformat()
    
    # Upsert: delete if exists, then insert
    cursor.execute("DELETE FROM fabric_planes WHERE plane_id = ?", (plane_id,))
    
    cursor.execute("""
        INSERT INTO fabric_planes (
            plane_id, plane_type, vendor, display_name, domain,
            managed_asset_count, is_healthy, aod_run_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        plane_id,
        plane_data["plane_type"],
        plane_data["vendor"],
        plane_data.get("display_name", f"{plane_data['vendor']} {plane_data['plane_type']}"),
        plane_data.get("domain"),
        plane_data.get("managed_asset_count", 0),
        1 if plane_data.get("is_healthy", True) else 0,
        aod_run_id,
        now,
        now
    ))
    
    conn.commit()
    conn.close()
    
    return {"plane_id": plane_id, "stored_at": now}


def get_fabric_planes(aod_run_id: Optional[str] = None) -> list[dict]:
    """Get fabric planes, optionally filtered by AOD run"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if aod_run_id:
        cursor.execute("SELECT * FROM fabric_planes WHERE aod_run_id = ?", (aod_run_id,))
    else:
        cursor.execute("SELECT * FROM fabric_planes ORDER BY updated_at DESC")
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "plane_id": row["plane_id"],
        "plane_type": row["plane_type"],
        "vendor": row["vendor"],
        "display_name": row["display_name"],
        "domain": row["domain"],
        "managed_asset_count": row["managed_asset_count"],
        "is_healthy": bool(row["is_healthy"]),
        "aod_run_id": row["aod_run_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    } for row in rows]


def find_fabric_plane_by_vendor(vendor: str, plane_type: Optional[str] = None) -> Optional[dict]:
    """Find a fabric plane by vendor (and optionally type)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if plane_type:
        cursor.execute("""
            SELECT * FROM fabric_planes 
            WHERE vendor = ? AND plane_type = ?
            ORDER BY updated_at DESC LIMIT 1
        """, (vendor, plane_type))
    else:
        cursor.execute("""
            SELECT * FROM fabric_planes 
            WHERE vendor = ?
            ORDER BY updated_at DESC LIMIT 1
        """, (vendor,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "plane_id": row["plane_id"],
            "plane_type": row["plane_type"],
            "vendor": row["vendor"],
            "display_name": row["display_name"],
            "domain": row["domain"],
            "managed_asset_count": row["managed_asset_count"],
            "is_healthy": bool(row["is_healthy"])
        }
    return None


