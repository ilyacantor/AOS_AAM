"""
Topology/graph operations

All three topology views (full, summary, per-plane) use the CANONICAL data
model: candidates ARE pipes.  There is no separate ``declared_pipes`` table
to read from — ``connection_candidates`` is the single source of truth.

Resolution logic is in ``app.plane_resolution`` — the single source of truth
for mapping candidates to fabric planes.  This module MUST NOT duplicate it.
"""
import json
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection
from ..plane_resolution import (
    resolve_candidate_to_plane,
    build_plane_node,
    parse_plane_type,
)


def _load_plane_lookups(cursor) -> tuple[dict, dict]:
    """Return (plane_info_by_id, type_to_first_plane_id) from fabric_planes table."""
    cursor.execute("SELECT * FROM fabric_planes ORDER BY updated_at DESC")
    db_planes = {row["plane_id"]: dict(row) for row in cursor.fetchall()}

    type_to_plane: dict[str, str] = {}
    for pid, info in db_planes.items():
        if info["plane_type"] not in type_to_plane:
            type_to_plane[info["plane_type"]] = pid

    return db_planes, type_to_plane


# ============================================================================
# FULL TOPOLOGY  (/api/topology — "All Assets")
# ============================================================================

def get_topology_data() -> dict:
    """
    Full topology graph: every candidate (= pipe) as an individual node,
    connected to its fabric plane and source system.

    Node types: pipe, fabric_plane, source_system
    Edge types: pipe_in_plane, pipe_from_source
    """
    conn = get_connection()
    cursor = conn.cursor()

    db_planes, type_to_plane = _load_plane_lookups(cursor)

    nodes = []
    edges = []
    fabric_planes_found: set[str] = set()
    source_systems: set[str] = set()

    # Candidates ARE pipes — this is the canonical model
    cursor.execute("""
        SELECT candidate_id, display_name, vendor_name, category, status,
               matched_pipe_id, match_score, fabric_plane_id, connected_via_plane,
               known_endpoints, preferred_modality
        FROM connection_candidates
    """)
    candidates = cursor.fetchall()

    for c in candidates:
        cid = c["candidate_id"]
        vendor = c["vendor_name"]
        plane_id = resolve_candidate_to_plane(dict(c), db_planes, type_to_plane)

        fabric_planes_found.add(plane_id)
        source_systems.add(vendor)

        # Pipe node (candidate = pipe in canonical model)
        plane_type = parse_plane_type(plane_id)
        endpoints = json.loads(c["known_endpoints"]) if c["known_endpoints"] else []
        nodes.append({
            "id": f"pipe:{cid}",
            "type": "pipe",
            "label": c["display_name"],
            "metadata": {
                "pipe_id": cid,
                "fabric_plane": plane_type,
                "source_system": vendor,
                "modality": c["preferred_modality"] or "DECLARED_INTERFACE",
                "category": c["category"],
                "status": c["status"],
                "endpoints": endpoints,
            },
        })

        # Edge: pipe → fabric plane
        edges.append({
            "id": f"edge:pipe_plane:{cid}",
            "source": f"pipe:{cid}",
            "target": f"plane:{plane_id}",
            "type": "pipe_in_plane",
            "metadata": {},
        })

        # Edge: pipe → source system
        edges.append({
            "id": f"edge:pipe_source:{cid}",
            "source": f"pipe:{cid}",
            "target": f"source:{vendor}",
            "type": "pipe_from_source",
            "metadata": {},
        })

    # Fabric plane nodes
    for plane_id in fabric_planes_found:
        nodes.append(build_plane_node(plane_id, db_planes))

    # Source system nodes
    for source in source_systems:
        nodes.append({
            "id": f"source:{source}",
            "type": "source_system",
            "label": source,
            "metadata": {"source_system": source},
        })

    # Stats
    cursor.execute("""
        SELECT DISTINCT pipe_id FROM drift_events WHERE status = 'open'
    """)
    pipes_with_drift = set(row[0] for row in cursor.fetchall())

    from ..constants import SOR_CATEGORIES
    sor_cats = list(SOR_CATEGORIES)
    placeholders = ",".join("?" * len(sor_cats))
    cursor.execute(
        f"SELECT COUNT(*) FROM connection_candidates WHERE LOWER(category) IN ({placeholders})",
        sor_cats,
    )
    sors_count = cursor.fetchone()[0]

    conn.close()

    nodes_by_type: dict[str, int] = {}
    for n in nodes:
        nodes_by_type[n["type"]] = nodes_by_type.get(n["type"], 0) + 1

    stats = {
        "total_pipes": len(candidates),
        "total_candidates": len(candidates),
        "pipes": len(candidates),
        "sors": sors_count,
        "fabrics": len(fabric_planes_found),
        "pipes_with_drift": len(pipes_with_drift),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes_by_type": nodes_by_type,
        "fabric_planes": sorted(list(fabric_planes_found)),
        "source_systems": sorted(list(source_systems)),
    }

    return {"nodes": nodes, "edges": edges, "stats": stats}


# ============================================================================
# PIPE-CENTRIC TOPOLOGY  (/api/topology/pipe/{pipe_id})
# ============================================================================

def get_topology_for_pipe(pipe_id: str) -> dict:
    """Get topology centred on a specific pipe (= candidate)."""
    conn = get_connection()
    cursor = conn.cursor()

    db_planes, type_to_plane = _load_plane_lookups(cursor)

    nodes = []
    edges = []

    cursor.execute(
        "SELECT * FROM connection_candidates WHERE candidate_id = ?",
        (pipe_id,),
    )
    candidate = cursor.fetchone()

    if not candidate:
        conn.close()
        return {"nodes": [], "edges": [], "stats": {}}

    vendor = candidate["vendor_name"]
    plane_id = resolve_candidate_to_plane(dict(candidate), db_planes, type_to_plane)
    plane_type = parse_plane_type(plane_id)

    # Pipe node (central)
    endpoints = json.loads(candidate["known_endpoints"]) if candidate["known_endpoints"] else []
    nodes.append({
        "id": f"pipe:{pipe_id}",
        "type": "pipe",
        "label": candidate["display_name"],
        "metadata": {
            "pipe_id": pipe_id,
            "fabric_plane": plane_type,
            "source_system": vendor,
            "modality": candidate["preferred_modality"] or "DECLARED_INTERFACE",
            "category": candidate["category"],
            "status": candidate["status"],
            "endpoints": endpoints,
            "central": True,
        },
    })

    # Fabric plane node
    nodes.append(build_plane_node(plane_id, db_planes))

    # Source system node
    nodes.append({
        "id": f"source:{vendor}",
        "type": "source_system",
        "label": vendor,
        "metadata": {"source_system": vendor},
    })

    # Edges
    edges.append({
        "id": f"edge:pipe_plane:{pipe_id}",
        "source": f"pipe:{pipe_id}",
        "target": f"plane:{plane_id}",
        "type": "pipe_in_plane",
        "metadata": {},
    })
    edges.append({
        "id": f"edge:pipe_source:{pipe_id}",
        "source": f"pipe:{pipe_id}",
        "target": f"source:{vendor}",
        "type": "pipe_from_source",
        "metadata": {},
    })

    # Drift events
    cursor.execute(
        "SELECT drift_id, drift_type, severity, status, detected_at "
        "FROM drift_events WHERE pipe_id = ? AND status = 'open'",
        (pipe_id,),
    )
    drift_events = [dict(d) for d in cursor.fetchall()]

    conn.close()

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "open_drift_events": len(drift_events),
        },
        "drift_events": drift_events,
    }


# ============================================================================
# PER-PLANE TOPOLOGY  (/api/topology/plane/{type})
# ============================================================================

def get_topology_for_fabric_plane(fabric_plane: str) -> dict:
    """Get topology for a specific fabric plane type — shows all candidates
    that route through that plane."""
    conn = get_connection()
    cursor = conn.cursor()

    db_planes, type_to_plane = _load_plane_lookups(cursor)

    nodes = []
    edges = []
    source_systems: set[str] = set()

    # Vendor-specific planes of this type
    vendor_planes = {
        pid: info for pid, info in db_planes.items() if info["plane_type"] == fabric_plane
    }

    # Add plane nodes
    if vendor_planes:
        for pid in vendor_planes:
            node = build_plane_node(pid, db_planes)
            node["metadata"]["central"] = True
            nodes.append(node)
    else:
        node = build_plane_node(fabric_plane, db_planes)
        node["metadata"]["central"] = True
        nodes.append(node)

    # Find candidates that resolve to this plane type
    cursor.execute("SELECT * FROM connection_candidates")
    all_candidates = cursor.fetchall()

    pipe_count = 0
    for c in all_candidates:
        resolved = resolve_candidate_to_plane(dict(c), db_planes, type_to_plane)
        resolved_type = parse_plane_type(resolved)
        if resolved_type != fabric_plane:
            continue

        cid = c["candidate_id"]
        vendor = c["vendor_name"]
        source_systems.add(vendor)
        pipe_count += 1

        endpoints = json.loads(c["known_endpoints"]) if c["known_endpoints"] else []
        nodes.append({
            "id": f"pipe:{cid}",
            "type": "pipe",
            "label": c["display_name"],
            "metadata": {
                "pipe_id": cid,
                "fabric_plane": fabric_plane,
                "source_system": vendor,
                "modality": c["preferred_modality"] or "DECLARED_INTERFACE",
                "category": c["category"],
                "status": c["status"],
                "endpoints": endpoints,
            },
        })

        edges.append({
            "id": f"edge:pipe_plane:{cid}",
            "source": f"pipe:{cid}",
            "target": f"plane:{resolved}",
            "type": "pipe_in_plane",
            "metadata": {},
        })
        edges.append({
            "id": f"edge:pipe_source:{cid}",
            "source": f"pipe:{cid}",
            "target": f"source:{vendor}",
            "type": "pipe_from_source",
            "metadata": {},
        })

    # Source system nodes
    for source in source_systems:
        nodes.append({
            "id": f"source:{source}",
            "type": "source_system",
            "label": source,
            "metadata": {"source_system": source},
        })

    conn.close()

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "total_pipes": pipe_count,
            "fabrics": len(vendor_planes) or 1,
            "source_systems": sorted(list(source_systems)),
        },
    }
