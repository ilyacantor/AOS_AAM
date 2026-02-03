"""
AAM → DCL Export Module

Provides pipe definitions grouped by fabric plane for DCL consumption.
Uses REAL fabric plane data from AOD instead of hardcoded vendors.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from .db import get_candidates_by_aod_run, list_candidates, get_fabric_planes


class DCLConnectionSchema(BaseModel):
    """Schema for a single connection in a fabric plane"""
    source_name: str
    vendor: str
    category: str
    governance_status: Optional[str] = None
    health: str = "healthy"
    fields: List[str] = Field(default_factory=list, description="Field names from schema")
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


def _infer_fields_from_category(category: str) -> List[str]:
    """Infer likely schema fields from asset category"""
    category_lower = category.lower()
    
    if "crm" in category_lower or "salesforce" in category_lower:
        return [
            "account_id", "account_name", "opportunity_id", "amount", 
            "stage", "close_date", "owner_id", "created_at"
        ]
    elif "erp" in category_lower or "sap" in category_lower or "netsuite" in category_lower:
        return [
            "invoice_id", "customer_id", "amount", "currency", 
            "status", "issue_date", "due_date", "gl_account"
        ]
    elif "finance" in category_lower or "accounting" in category_lower:
        return [
            "transaction_id", "account", "debit", "credit", 
            "date", "description", "category"
        ]
    elif "hcm" in category_lower or "hr" in category_lower or "workday" in category_lower:
        return [
            "employee_id", "name", "department", "title", 
            "salary", "hire_date", "manager_id", "status"
        ]
    elif "data" in category_lower or "warehouse" in category_lower:
        return [
            "date", "customer_id", "revenue", "cost", 
            "margin", "segment", "region"
        ]
    else:
        return [
            "id", "name", "created_at", "updated_at", "status"
        ]


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
        all_candidates = list_candidates(limit=10000)
        candidates = [c for c in all_candidates if c.get("status") in ["connected", "triaged", "new"]]
    
    # Group candidates by fabric plane (using vendor matching)
    planes_dict: Dict[str, Dict] = {}
    for plane_db in fabric_planes_db:
        plane_id = plane_db["plane_id"]
        planes_dict[plane_id] = {
            "plane": plane_db,
            "candidates": []
        }
    
    # Assign candidates to their fabric plane
    for candidate in candidates:
        # Try to match by connected_via_plane string
        connected_via = candidate.get("connected_via_plane", "")
        
        # Extract vendor from "Connect via MuleSoft" format
        matched_plane = None
        if connected_via:
            for plane_id, data in planes_dict.items():
                plane = data["plane"]
                if plane["vendor"].lower() in connected_via.lower():
                    matched_plane = plane_id
                    break
        
        # Fallback: infer from category
        if not matched_plane and planes_dict:
            category = candidate.get("category", "").lower()
            # Map category to plane type
            if "data" in category or "warehouse" in category:
                target_type = "warehouse"
            elif "event" in category or "stream" in category:
                target_type = "event_bus"
            elif "gateway" in category or "api" in category:
                target_type = "api_gateway"
            else:
                target_type = "ipaas"
            
            # Find first plane of that type
            for plane_id, data in planes_dict.items():
                if data["plane"]["plane_type"] == target_type:
                    matched_plane = plane_id
                    break
            
            # Ultimate fallback: first available plane
            if not matched_plane:
                matched_plane = next(iter(planes_dict.keys()), None)
        
        if matched_plane:
            planes_dict[matched_plane]["candidates"].append(candidate)
    
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
            category = candidate.get("category", "other")
            fields = _infer_fields_from_category(category)
            
            connection = DCLConnectionSchema(
                source_name=candidate.get("display_name", "Unknown"),
                vendor=candidate.get("vendor_name", "Unknown"),
                category=category,
                governance_status=candidate.get("governance_status"),
                health="healthy" if candidate.get("execution_allowed", True) else "degraded",
                fields=fields,
                last_sync=candidate.get("updated_at"),
                asset_key=candidate.get("asset_key", ""),
                aod_asset_id=candidate.get("aod_asset_id")
            )
            connections.append(connection)
        
        fabric_plane_obj = DCLFabricPlane(
            plane_type=plane["plane_type"],
            vendor=plane["vendor"],
            connection_count=len(connections),
            connections=connections,
            health="healthy" if plane["is_healthy"] else "degraded"
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
