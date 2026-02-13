"""
AAM → DCL Export Module

Provides pipe definitions grouped by fabric plane for DCL consumption.
Uses REAL fabric plane data from AOD instead of hardcoded vendors.
"""
import logging
from typing import List, Dict, Any, Optional

from .models import CandidateStatus
from pydantic import BaseModel
from datetime import datetime

from .db import get_candidates_by_aod_run, list_candidates, get_fabric_planes

_log = logging.getLogger(__name__)


class DCLConnectionSchema(BaseModel):
    """Schema for a single connection in a fabric plane"""
    source_name: str
    vendor: str
    category: str
    governance_status: Optional[str] = None
    health: str = "healthy"
    last_sync: Optional[str] = None
    asset_key: str
    aod_asset_id: Optional[str] = None


class DCLFabricPlane(BaseModel):
    """A fabric plane with its connections"""
    plane_type: str  # ipaas, warehouse, api_gateway, event_bus
    vendor: str  # Actual vendor from AOD: mulesoft, kong, snowflake, kafka, etc.
    connection_count: int
    connections: List[DCLConnectionSchema]
    health: str = "healthy"


class DCLExportResponse(BaseModel):
    """Response for DCL export endpoint"""
    run_id: Optional[str] = None
    timestamp: str
    fabric_planes: List[DCLFabricPlane]
    total_connections: int
    source: str = "aam"


def build_dcl_export(aod_run_id: Optional[str] = None) -> DCLExportResponse:
    """
    Build DCL export from AAM candidates using REAL fabric planes from AOD.
    
    Groups candidates by fabric plane and formats for DCL consumption.
    If aod_run_id is provided, filters to that run. Otherwise, uses all candidates.
    """
    # Fetch real fabric planes from database
    fabric_planes_db = get_fabric_planes(aod_run_id)
    
    # Fetch candidates
    if aod_run_id:
        candidates = get_candidates_by_aod_run(aod_run_id)
    else:
        # Get all candidates with status 'connected' or 'triaged'
        all_candidates = list_candidates()
        candidates = [c for c in all_candidates if c.get("status") in [CandidateStatus.CONNECTED, CandidateStatus.TRIAGED, CandidateStatus.NEW]]
    
    # Group candidates by fabric plane (using fabric_plane_id linkage)
    planes_dict: Dict[str, Dict] = {}
    for plane_db in fabric_planes_db:
        plane_id = plane_db["plane_id"]
        planes_dict[plane_id] = {
            "plane": plane_db,
            "candidates": []
        }
    
    # Assign candidates to their fabric plane using fabric_plane_id
    unlinked_candidates = []
    for candidate in candidates:
        fabric_plane_id = candidate.get("fabric_plane_id")
        
        if fabric_plane_id and fabric_plane_id in planes_dict:
            # Direct linkage exists
            planes_dict[fabric_plane_id]["candidates"].append(candidate)
        else:
            unlinked_candidates.append(candidate)
    
    # Unlinked candidates are grouped under a synthetic "UNMAPPED" plane
    # so DCL can see they exist (instead of silently dropping them).
    if unlinked_candidates:
        _log.warning(
            "%d candidate(s) have no fabric_plane_id — grouped under UNMAPPED in DCL export",
            len(unlinked_candidates),
        )
        planes_dict["UNMAPPED"] = {
            "plane": {
                "plane_type": "UNMAPPED",
                "vendor": "unlinked",
                "is_healthy": None,
            },
            "candidates": unlinked_candidates,
        }
    
    # Build fabric plane objects for DCL
    fabric_planes_output = []
    total_connections = 0
    
    for plane_id, data in planes_dict.items():
        plane = data["plane"]
        candidates_list = data["candidates"]
        
        if not candidates_list:
            # Skip empty fabric planes
            continue
        
        connections = []
        for candidate in candidates_list:
            connection = DCLConnectionSchema(
                source_name=candidate.get("display_name", "Unknown"),
                vendor=candidate.get("vendor_name", "Unknown"),
                category=candidate.get("category", "other"),
                governance_status=candidate.get("governance_status"),
                health="unknown",
                last_sync=candidate.get("updated_at"),
                asset_key=candidate.get("asset_key", ""),
                aod_asset_id=candidate.get("aod_asset_id"),
            )
            connections.append(connection)
        
        fabric_plane_obj = DCLFabricPlane(
            plane_type=plane["plane_type"],
            vendor=plane["vendor"],
            connection_count=len(connections),
            connections=connections,
            health="healthy" if plane["is_healthy"] is True else (
                "unknown" if plane["is_healthy"] is None else "degraded"
            )
        )
        fabric_planes_output.append(fabric_plane_obj)
        total_connections += len(connections)
    
    return DCLExportResponse(
        run_id=aod_run_id,
        timestamp=datetime.utcnow().isoformat() + "Z",
        fabric_planes=fabric_planes_output,
        total_connections=total_connections,
        source="aam"
    )
