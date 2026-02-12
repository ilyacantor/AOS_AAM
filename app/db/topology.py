"""
Topology/graph operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# TOPOLOGY / GRAPH OPERATIONS
# ============================================================================

def get_topology_data() -> dict:
    """
    Get all data needed for topology visualization.
    Returns nodes and edges for the graph.
    """
    conn = get_connection()
    cursor = conn.cursor()

    nodes = []
    edges = []

    # Track unique fabric planes and source systems
    fabric_planes = set()
    source_systems = set()

    # Get all pipes
    cursor.execute("""
        SELECT pipe_id, display_name, fabric_plane, source_system, modality,
               transport_kind, entity_scope, trust_labels, version
        FROM declared_pipes
    """)
    pipes = cursor.fetchall()

    for pipe in pipes:
        pipe_id = pipe["pipe_id"]
        fabric_plane = pipe["fabric_plane"] or "API_GATEWAY"
        source_system = pipe["source_system"]

        fabric_planes.add(fabric_plane)
        source_systems.add(source_system)

        # Add pipe node
        entity_scope = json.loads(pipe["entity_scope"]) if pipe["entity_scope"] else []
        trust_labels = json.loads(pipe["trust_labels"]) if pipe["trust_labels"] else []

        nodes.append({
            "id": f"pipe:{pipe_id}",
            "type": "pipe",
            "label": pipe["display_name"],
            "metadata": {
                "pipe_id": pipe_id,
                "fabric_plane": fabric_plane,
                "source_system": source_system,
                "modality": pipe["modality"],
                "transport_kind": pipe["transport_kind"],
                "entity_scope": entity_scope,
                "trust_labels": trust_labels,
                "version": pipe["version"]
            }
        })

        # Add edge: pipe -> fabric_plane
        edges.append({
            "id": f"edge:pipe_plane:{pipe_id}",
            "source": f"pipe:{pipe_id}",
            "target": f"plane:{fabric_plane}",
            "type": "pipe_in_plane",
            "metadata": {}
        })

        # Add edge: pipe -> source_system
        edges.append({
            "id": f"edge:pipe_source:{pipe_id}",
            "source": f"pipe:{pipe_id}",
            "target": f"source:{source_system}",
            "type": "pipe_from_source",
            "metadata": {}
        })

    # Add fabric plane nodes
    plane_colors = {
        "IPAAS": "#22d3ee",
        "API_GATEWAY": "#a78bfa",
        "EVENT_BUS": "#f97316",
        "DATA_WAREHOUSE": "#10b981"
    }
    for plane in fabric_planes:
        nodes.append({
            "id": f"plane:{plane}",
            "type": "fabric_plane",
            "label": plane.replace("_", " ").title(),
            "metadata": {
                "plane_type": plane,
                "color": plane_colors.get(plane, "#64748b")
            }
        })

    # Add source system nodes
    for source in source_systems:
        nodes.append({
            "id": f"source:{source}",
            "type": "source_system",
            "label": source,
            "metadata": {
                "source_system": source
            }
        })

    # Get all candidates
    cursor.execute("""
        SELECT candidate_id, display_name, vendor_name, category, status,
               matched_pipe_id, match_score
        FROM connection_candidates
    """)
    candidates = cursor.fetchall()

    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        vendor_name = candidate["vendor_name"]

        # Ensure vendor is in source_systems for edge consistency
        if vendor_name not in source_systems:
            source_systems.add(vendor_name)
            nodes.append({
                "id": f"source:{vendor_name}",
                "type": "source_system",
                "label": vendor_name,
                "metadata": {
                    "source_system": vendor_name
                }
            })

        # Add candidate node
        nodes.append({
            "id": f"candidate:{candidate_id}",
            "type": "candidate",
            "label": candidate["display_name"],
            "metadata": {
                "candidate_id": candidate_id,
                "vendor_name": vendor_name,
                "category": candidate["category"],
                "status": candidate["status"],
                "matched_pipe_id": candidate["matched_pipe_id"],
                "match_score": candidate["match_score"]
            }
        })

        # Add edge: candidate -> source_system
        edges.append({
            "id": f"edge:candidate_source:{candidate_id}",
            "source": f"candidate:{candidate_id}",
            "target": f"source:{vendor_name}",
            "type": "candidate_for_source",
            "metadata": {
                "category": candidate["category"]
            }
        })

        # Add edge: candidate -> pipe (if matched)
        if candidate["matched_pipe_id"]:
            edges.append({
                "id": f"edge:candidate_pipe:{candidate_id}",
                "source": f"candidate:{candidate_id}",
                "target": f"pipe:{candidate['matched_pipe_id']}",
                "type": "candidate_to_pipe",
                "metadata": {
                    "match_score": candidate["match_score"]
                }
            })

    # Get drift statistics
    cursor.execute("""
        SELECT DISTINCT pipe_id FROM drift_events WHERE status = 'open'
    """)
    pipes_with_open_drift = set(row[0] for row in cursor.fetchall())

    # Get candidate statistics
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN matched_pipe_id IS NOT NULL THEN 1 ELSE 0 END) as connected
        FROM connection_candidates
    """)
    candidate_stats = cursor.fetchone()
    total_candidates = candidate_stats[0] or 0
    connected_candidates = candidate_stats[1] or 0

    conn.close()

    # Compute stats
    nodes_by_type = {}
    for node in nodes:
        node_type = node["type"]
        nodes_by_type[node_type] = nodes_by_type.get(node_type, 0) + 1

    edges_by_type = {}
    for edge in edges:
        edge_type = edge["type"]
        edges_by_type[edge_type] = edges_by_type.get(edge_type, 0) + 1

    # Get SOR count (candidates with SOR categories)
    from ..constants import SOR_CATEGORIES
    sor_categories = list(SOR_CATEGORIES)
    placeholders = ','.join('?' * len(sor_categories))
    cursor.execute(f"""
        SELECT COUNT(*) FROM connection_candidates
        WHERE LOWER(category) IN ({placeholders})
    """, sor_categories)
    sors_count = cursor.fetchone()[0]
    
    # Canonical labels: SORs, Fabrics, Pipes (not "nodes")
    stats = {
        "total_pipes": len(pipes),  # Canonical: pipes = candidates from declared_pipes (legacy)
        "total_candidates": total_candidates,  # All candidates (which ARE pipes)
        "sors": sors_count,
        "fabrics": len(fabric_planes),
        "pipes": len(pipes),  # For UI display
        "connected_candidates": connected_candidates,
        "unconnected_candidates": total_candidates - connected_candidates,
        "pipes_with_drift": len(pipes_with_open_drift),
        # Legacy fields for backward compatibility
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes_by_type": nodes_by_type,
        "edges_by_type": edges_by_type,
        "fabric_planes": sorted(list(fabric_planes)),
        "source_systems": sorted(list(source_systems))
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": stats
    }


def get_topology_for_pipe(pipe_id: str) -> dict:
    """Get topology centered on a specific pipe"""
    conn = get_connection()
    cursor = conn.cursor()

    nodes = []
    edges = []

    # Get the pipe
    cursor.execute("""
        SELECT pipe_id, display_name, fabric_plane, source_system, modality,
               transport_kind, entity_scope, trust_labels, version
        FROM declared_pipes WHERE pipe_id = ?
    """, (pipe_id,))
    pipe = cursor.fetchone()

    if not pipe:
        conn.close()
        return {"nodes": [], "edges": [], "stats": {}}

    fabric_plane = pipe["fabric_plane"] or "API_GATEWAY"
    source_system = pipe["source_system"]
    entity_scope = json.loads(pipe["entity_scope"]) if pipe["entity_scope"] else []
    trust_labels = json.loads(pipe["trust_labels"]) if pipe["trust_labels"] else []

    # Add pipe node (central)
    nodes.append({
        "id": f"pipe:{pipe_id}",
        "type": "pipe",
        "label": pipe["display_name"],
        "metadata": {
            "pipe_id": pipe_id,
            "fabric_plane": fabric_plane,
            "source_system": source_system,
            "modality": pipe["modality"],
            "transport_kind": pipe["transport_kind"],
            "entity_scope": entity_scope,
            "trust_labels": trust_labels,
            "version": pipe["version"],
            "central": True
        }
    })

    # Add fabric plane node
    plane_colors = {
        "IPAAS": "#22d3ee",
        "API_GATEWAY": "#a78bfa",
        "EVENT_BUS": "#f97316",
        "DATA_WAREHOUSE": "#10b981"
    }
    nodes.append({
        "id": f"plane:{fabric_plane}",
        "type": "fabric_plane",
        "label": fabric_plane.replace("_", " ").title(),
        "metadata": {
            "plane_type": fabric_plane,
            "color": plane_colors.get(fabric_plane, "#64748b")
        }
    })

    # Add source system node
    nodes.append({
        "id": f"source:{source_system}",
        "type": "source_system",
        "label": source_system,
        "metadata": {"source_system": source_system}
    })

    # Add edges
    edges.append({
        "id": f"edge:pipe_plane:{pipe_id}",
        "source": f"pipe:{pipe_id}",
        "target": f"plane:{fabric_plane}",
        "type": "pipe_in_plane",
        "metadata": {}
    })
    edges.append({
        "id": f"edge:pipe_source:{pipe_id}",
        "source": f"pipe:{pipe_id}",
        "target": f"source:{source_system}",
        "type": "pipe_from_source",
        "metadata": {}
    })

    # Get related candidates
    cursor.execute("""
        SELECT candidate_id, display_name, vendor_name, category, status, match_score
        FROM connection_candidates WHERE matched_pipe_id = ?
    """, (pipe_id,))
    candidates = cursor.fetchall()

    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        nodes.append({
            "id": f"candidate:{candidate_id}",
            "type": "candidate",
            "label": candidate["display_name"],
            "metadata": {
                "candidate_id": candidate_id,
                "vendor_name": candidate["vendor_name"],
                "category": candidate["category"],
                "status": candidate["status"],
                "match_score": candidate["match_score"]
            }
        })
        edges.append({
            "id": f"edge:candidate_pipe:{candidate_id}",
            "source": f"candidate:{candidate_id}",
            "target": f"pipe:{pipe_id}",
            "type": "candidate_to_pipe",
            "metadata": {"match_score": candidate["match_score"]}
        })

    # Get drift events
    cursor.execute("""
        SELECT drift_id, drift_type, severity, status, detected_at
        FROM drift_events WHERE pipe_id = ? AND status = 'open'
    """, (pipe_id,))
    drift_events = cursor.fetchall()

    conn.close()

    stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "connected_candidates": len(candidates),
        "open_drift_events": len(drift_events)
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": stats,
        "drift_events": [{
            "drift_id": d["drift_id"],
            "drift_type": d["drift_type"],
            "severity": d["severity"],
            "status": d["status"],
            "detected_at": d["detected_at"]
        } for d in drift_events]
    }


def get_topology_for_fabric_plane(fabric_plane: str) -> dict:
    """Get topology for a specific fabric plane"""
    conn = get_connection()
    cursor = conn.cursor()

    nodes = []
    edges = []

    # Add fabric plane node
    plane_colors = {
        "IPAAS": "#22d3ee",
        "API_GATEWAY": "#a78bfa",
        "EVENT_BUS": "#f97316",
        "DATA_WAREHOUSE": "#10b981"
    }
    nodes.append({
        "id": f"plane:{fabric_plane}",
        "type": "fabric_plane",
        "label": fabric_plane.replace("_", " ").title(),
        "metadata": {
            "plane_type": fabric_plane,
            "color": plane_colors.get(fabric_plane, "#64748b"),
            "central": True
        }
    })

    # Get all pipes in this plane
    cursor.execute("""
        SELECT pipe_id, display_name, source_system, modality,
               transport_kind, entity_scope, trust_labels, version
        FROM declared_pipes WHERE fabric_plane = ?
    """, (fabric_plane,))
    pipes = cursor.fetchall()

    source_systems = set()

    for pipe in pipes:
        pipe_id = pipe["pipe_id"]
        source_system = pipe["source_system"]
        source_systems.add(source_system)

        entity_scope = json.loads(pipe["entity_scope"]) if pipe["entity_scope"] else []
        trust_labels = json.loads(pipe["trust_labels"]) if pipe["trust_labels"] else []

        nodes.append({
            "id": f"pipe:{pipe_id}",
            "type": "pipe",
            "label": pipe["display_name"],
            "metadata": {
                "pipe_id": pipe_id,
                "fabric_plane": fabric_plane,
                "source_system": source_system,
                "modality": pipe["modality"],
                "transport_kind": pipe["transport_kind"],
                "entity_scope": entity_scope,
                "trust_labels": trust_labels,
                "version": pipe["version"]
            }
        })

        edges.append({
            "id": f"edge:pipe_plane:{pipe_id}",
            "source": f"pipe:{pipe_id}",
            "target": f"plane:{fabric_plane}",
            "type": "pipe_in_plane",
            "metadata": {}
        })

        edges.append({
            "id": f"edge:pipe_source:{pipe_id}",
            "source": f"pipe:{pipe_id}",
            "target": f"source:{source_system}",
            "type": "pipe_from_source",
            "metadata": {}
        })

    # Add source system nodes
    for source in source_systems:
        nodes.append({
            "id": f"source:{source}",
            "type": "source_system",
            "label": source,
            "metadata": {"source_system": source}
        })

    conn.close()

    stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "total_pipes": len(pipes),
        "source_systems": sorted(list(source_systems))
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": stats
    }


