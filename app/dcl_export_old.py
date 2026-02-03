"""
AAM → DCL Export Module

Provides pipe definitions grouped by fabric plane for DCL consumption.
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
    plane_type: str  # ipaas, warehouse, gateway, eventbus
    vendor: str  # MuleSoft, Snowflake, Kong, Kafka
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


# Removed hardcoded vendor mappings - now uses real fabric plane data from AOD


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
    Build DCL export from AAM candidates.
    
    Groups candidates by fabric plane and formats for DCL consumption.
    If aod_run_id is provided, filters to that run. Otherwise, uses all candidates.
    """
    # Fetch candidates
    if aod_run_id:
        candidates = get_candidates_by_aod_run(aod_run_id)
    else:
        # Get all candidates with status 'connected' or 'triaged' - no limit for DCL export
        all_candidates = list_candidates(limit=10000)
        candidates = [c for c in all_candidates if c.get("status") in ["connected", "triaged", "new"]]
    
    # Group by fabric plane
    planes_dict: Dict[FabricPlane, List[Dict]] = {
        FabricPlane.IPAAS: [],
        FabricPlane.DATA_WAREHOUSE: [],
        FabricPlane.API_GATEWAY: [],
        FabricPlane.EVENT_BUS: []
    }
    
    for candidate in candidates:
        # Parse connected_via_plane from candidate
        plane_str = candidate.get("connected_via_plane")
        
        if plane_str:
            try:
                plane = FabricPlane(plane_str)
            except ValueError:
                # Default to IPAAS if unknown
                plane = FabricPlane.IPAAS
        else:
            # Infer from category if not specified
            category = candidate.get("category", "").lower()
            if "data" in category or "warehouse" in category:
                plane = FabricPlane.DATA_WAREHOUSE
            elif "event" in category or "stream" in category:
                plane = FabricPlane.EVENT_BUS
            elif "gateway" in category or "api" in category:
                plane = FabricPlane.API_GATEWAY
            else:
                plane = FabricPlane.IPAAS
        
        planes_dict[plane].append(candidate)
    
    # Build fabric plane objects
    fabric_planes = []
    total_connections = 0
    
    for plane, candidates_list in planes_dict.items():
        if not candidates_list:
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
            plane_type=_map_fabric_plane_to_dcl_type(plane),
            vendor=_map_fabric_plane_to_vendor(plane),
            connection_count=len(connections),
            connections=connections,
            health="healthy"
        )
        fabric_planes.append(fabric_plane_obj)
        total_connections += len(connections)
    
    return DCLExportResponse(
        run_id=aod_run_id,
        timestamp=datetime.utcnow().isoformat() + "Z",
        fabric_planes=fabric_planes,
        total_connections=total_connections,
        source="aam"
    )
