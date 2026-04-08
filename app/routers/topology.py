"""
Topology Router — graph/visualization endpoints.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime

from ..db import (
    get_topology_data,
    get_topology_for_pipe,
    get_topology_for_fabric_plane,
    list_pipes,
    list_candidates,
    get_canonical_stats,
)
from ..db.sor_declarations import get_sor_declarations
from ..db.semantic_edges import list_semantic_edges, count_semantic_edges
from ..services.topology_service import build_topology_summary

router = APIRouter(prefix="/api/topology", tags=["Topology"])


@router.get("")
async def get_full_topology():
    """Get the complete topology graph for visualization."""
    topology = get_topology_data()
    return {
        "nodes": topology["nodes"],
        "edges": topology["edges"],
        "stats": topology["stats"],
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/nodes")
async def get_topology_nodes(
    node_type: Optional[str] = Query(None),
):
    """Get just the nodes, optionally filtered by type."""
    topology = get_topology_data()
    nodes = topology["nodes"]
    if node_type:
        nodes = [n for n in nodes if n["type"] == node_type]
    return {"nodes": nodes, "total": len(nodes), "filter": node_type}


@router.get("/edges")
async def get_topology_edges(
    edge_type: Optional[str] = Query(None),
):
    """Get just the edges, optionally filtered by type."""
    topology = get_topology_data()
    edges = topology["edges"]
    if edge_type:
        edges = [e for e in edges if e["type"] == edge_type]
    return {"edges": edges, "total": len(edges), "filter": edge_type}


@router.get("/stats")
async def get_topology_stats():
    """Get statistics about the topology."""
    topology = get_topology_data()
    return topology["stats"]


@router.get("/summary")
async def get_topology_summary():
    """
    Get a lightweight topology showing only Fabric Planes and SORs.
    Optimized for large datasets (600+ assets).
    """
    return build_topology_summary()


@router.get("/semantic-edges")
async def get_semantic_edges(
    source_system: Optional[str] = Query(None),
    target_system: Optional[str] = Query(None),
    fabric_plane: Optional[str] = Query(None),
    confidence_min: Optional[float] = Query(None, ge=0.0, le=1.0),
    extraction_source: Optional[str] = Query(None),
):
    """
    Get field-level semantic edges between systems.

    These are explicit cross-system field mappings extracted from
    integration infrastructure (iPaaS recipes, warehouse lineage,
    event schemas).  DCL consumes these as high-confidence inputs
    that override LLM inference.
    """
    edges = list_semantic_edges(
        source_system=source_system,
        target_system=target_system,
        fabric_plane=fabric_plane,
        confidence_min=confidence_min,
        extraction_source=extraction_source,
    )
    return {
        "edges": edges,
        "total": len(edges),
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/semantic-edges/stats")
async def get_semantic_edge_stats():
    """Summary statistics for semantic edges."""
    edges = list_semantic_edges()
    by_plane: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_source_system: dict[str, int] = {}
    for e in edges:
        plane = e.get("fabric_plane", "unknown")
        by_plane[plane] = by_plane.get(plane, 0) + 1
        etype = e.get("edge_type", "unknown")
        by_type[etype] = by_type.get(etype, 0) + 1
        src = e.get("source_system", "unknown")
        by_source_system[src] = by_source_system.get(src, 0) + 1
    return {
        "total": len(edges),
        "by_fabric_plane": by_plane,
        "by_edge_type": by_type,
        "by_source_system": by_source_system,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/pipe/{pipe_id}")
async def get_pipe_topology(pipe_id: str):
    """Get topology centered on a specific pipe."""
    result = get_topology_for_pipe(pipe_id)
    if not result["nodes"]:
        raise HTTPException(status_code=404, detail=f"Pipe {pipe_id} not found")
    return {**result, "generated_at": datetime.utcnow().isoformat()}


@router.get("/plane/{fabric_plane}")
async def get_plane_topology(fabric_plane: str):
    """Get topology for a specific fabric plane.

    Accepts canonical uppercase (IPAAS, API_GATEWAY, EVENT_BUS,
    DATA_WAREHOUSE) and any alias listed in PLANE_TYPE_ALIASES
    (including the lowercase canonical the topology UI now uses:
    ipaas, api_gateway, event_bus, warehouse).
    """
    from ..constants import ALL_PLANE_TYPES, PLANE_TYPE_ALIASES
    raw = (fabric_plane or "").strip()
    # Normalize: try the alias map first (handles lowercase, "warehouse",
    # "apigateway", etc.), then fall back to raw uppercasing.
    normalized = PLANE_TYPE_ALIASES.get(raw) or PLANE_TYPE_ALIASES.get(raw.lower()) or raw.upper()
    if normalized not in ALL_PLANE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fabric plane '{fabric_plane}'. Must be one of: {', '.join(ALL_PLANE_TYPES)} (aliases accepted).",
        )
    result = get_topology_for_fabric_plane(normalized)
    return {**result, "generated_at": datetime.utcnow().isoformat()}


@router.get("/source/{source_system}")
async def get_source_topology(source_system: str):
    """Get topology for a specific source system."""
    topology = get_topology_data()
    source_node_id = f"source:{source_system}"
    source_exists = any(n["id"] == source_node_id for n in topology["nodes"])
    if not source_exists:
        raise HTTPException(status_code=404, detail=f"Source system '{source_system}' not found")

    connected_ids = {source_node_id}
    for edge in topology["edges"]:
        if edge["target"] == source_node_id:
            connected_ids.add(edge["source"])
        elif edge["source"] == source_node_id:
            connected_ids.add(edge["target"])

    for edge in topology["edges"]:
        if edge["source"] in connected_ids and edge["type"] == "pipe_in_plane":
            connected_ids.add(edge["target"])

    nodes = [n for n in topology["nodes"] if n["id"] in connected_ids]
    edges = [e for e in topology["edges"] if e["source"] in connected_ids and e["target"] in connected_ids]

    for node in nodes:
        if node["id"] == source_node_id:
            node["metadata"]["central"] = True

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "pipes": len([n for n in nodes if n["type"] == "pipe"]),
            "candidates": len([n for n in nodes if n["type"] == "candidate"]),
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/sors")
async def list_sor_declarations(aod_run_id: Optional[str] = Query(None)):
    """List authoritative SOR declarations from Farm (via AOD)."""
    declarations = get_sor_declarations(aod_run_id=aod_run_id)
    return {
        "sors": declarations,
        "total": len(declarations),
        "generated_at": datetime.utcnow().isoformat(),
    }
