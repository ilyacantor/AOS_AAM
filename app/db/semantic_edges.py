"""
Semantic edge CRUD operations.

SemanticEdges represent field-level mappings between systems, extracted
from integration infrastructure (iPaaS recipes, warehouse lineage,
event schemas, API specs).  DCL consumes these via
GET /api/topology/semantic-edges.
"""
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def store_semantic_edge(edge: dict) -> dict:
    """Insert a single semantic edge.  Returns the stored row."""
    now = datetime.utcnow().isoformat()
    row = {
        "id": edge.get("id") or str(uuid.uuid4()),
        "source_system": edge["source_system"],
        "source_object": edge["source_object"],
        "source_field": edge["source_field"],
        "target_system": edge["target_system"],
        "target_object": edge["target_object"],
        "target_field": edge["target_field"],
        "edge_type": edge["edge_type"],
        "confidence": edge["confidence"],
        "fabric_plane": edge["fabric_plane"],
        "extraction_source": edge["extraction_source"],
        "transformation": edge.get("transformation"),
        "condition": edge.get("condition"),
        "discovered_at": edge.get("discovered_at") or now,
        "last_verified": edge.get("last_verified") or now,
    }
    return sb.insert("semantic_edges", row, on_conflict="id")


def store_semantic_edges_batch(edges: list[dict]) -> list[dict]:
    """Insert many semantic edges in one round-trip.  Returns stored rows."""
    if not edges:
        return []
    now = datetime.utcnow().isoformat()
    rows = []
    for e in edges:
        rows.append({
            "id": e.get("id") or str(uuid.uuid4()),
            "source_system": e["source_system"],
            "source_object": e["source_object"],
            "source_field": e["source_field"],
            "target_system": e["target_system"],
            "target_object": e["target_object"],
            "target_field": e["target_field"],
            "edge_type": e["edge_type"],
            "confidence": e["confidence"],
            "fabric_plane": e["fabric_plane"],
            "extraction_source": e["extraction_source"],
            "transformation": e.get("transformation"),
            "condition": e.get("condition"),
            "discovered_at": e.get("discovered_at") or now,
            "last_verified": e.get("last_verified") or now,
        })
    return sb.insert_many("semantic_edges", rows)


def list_semantic_edges(
    *,
    source_system: Optional[str] = None,
    target_system: Optional[str] = None,
    fabric_plane: Optional[str] = None,
    confidence_min: Optional[float] = None,
    extraction_source: Optional[str] = None,
) -> list[dict]:
    """List semantic edges with optional filters."""
    filters: dict = {}
    if source_system:
        filters["source_system"] = source_system
    if target_system:
        filters["target_system"] = target_system
    if fabric_plane:
        filters["fabric_plane"] = fabric_plane
    if extraction_source:
        filters["extraction_source"] = extraction_source

    rows = sb.select(
        "semantic_edges",
        filters=filters if filters else None,
        order="confidence.desc",
    )

    if confidence_min is not None:
        rows = [r for r in rows if (r.get("confidence") or 0) >= confidence_min]

    return rows


def get_semantic_edge(edge_id: str) -> Optional[dict]:
    """Get a single semantic edge by ID."""
    return sb.select("semantic_edges", filters={"id": edge_id}, single=True)


def delete_semantic_edges_by_source(extraction_source: str) -> list[dict]:
    """Delete all edges from a given extraction source (for re-scan)."""
    return sb.delete("semantic_edges", filters={"extraction_source": extraction_source})


def count_semantic_edges() -> int:
    """Return total count of semantic edges."""
    rows = sb.select("semantic_edges", columns="id")
    return len(rows)
