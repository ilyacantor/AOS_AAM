"""
Topology/graph operations

All three topology views (full, summary, per-plane) use the CANONICAL data
model: candidates ARE pipes.  There is no separate ``declared_pipes`` table
to read from — ``connection_candidates`` is the single source of truth.
"""
import json
from typing import Optional

from . import supabase_client as sb

_PLANE_LABELS = {
    "IPAAS": "iPaaS",
    "API_GATEWAY": "API Gateway",
    "EVENT_BUS": "Event Bus",
    "DATA_WAREHOUSE": "Data Warehouse",
    "UNMAPPED": "Unmapped",
}

_PLANE_COLORS = {
    "IPAAS": "#22d3ee",
    "API_GATEWAY": "#a78bfa",
    "EVENT_BUS": "#f97316",
    "DATA_WAREHOUSE": "#10b981",
    "UNMAPPED": "#ef4444",
}


def _load_plane_lookups() -> tuple[dict, dict]:
    """Return (plane_info_by_id, type_to_first_plane_id) from fabric_planes table."""
    rows = sb.select("fabric_planes", order="updated_at.desc")
    db_planes = {row["plane_id"]: row for row in rows}

    type_to_plane: dict[str, str] = {}
    for pid, info in db_planes.items():
        if info["plane_type"] not in type_to_plane:
            type_to_plane[info["plane_type"]] = pid

    return db_planes, type_to_plane


def _resolve_candidate_plane(candidate, db_planes: dict, type_to_plane: dict) -> str:
    """Resolve a candidate row to its vendor-specific fabric plane_id."""
    fpid = candidate.get("fabric_plane_id")
    if fpid and fpid in db_planes:
        return fpid
    connected = candidate.get("connected_via_plane")
    if connected:
        plane_type = connected.upper()
        if plane_type in type_to_plane:
            return type_to_plane[plane_type]
    return "UNMAPPED"


def _make_plane_node(plane_id: str, db_planes: dict) -> dict:
    """Create a fabric_plane node dict."""
    if plane_id in db_planes:
        info = db_planes[plane_id]
        vendor_display = info["vendor"].title()
        plane_type = info["plane_type"]
        type_label = _PLANE_LABELS.get(plane_type, plane_type.replace("_", " ").title())
        label = f"{vendor_display}, {type_label}"
    else:
        plane_type = plane_id
        label = _PLANE_LABELS.get(plane_id, plane_id.replace("_", " ").title())

    return {
        "id": f"plane:{plane_id}",
        "type": "fabric_plane",
        "label": label,
        "metadata": {
            "plane_type": plane_type if plane_id in db_planes else plane_id,
            "vendor": db_planes[plane_id]["vendor"] if plane_id in db_planes else None,
            "color": _PLANE_COLORS.get(
                db_planes[plane_id]["plane_type"] if plane_id in db_planes else plane_id,
                "#64748b",
            ),
        },
    }


def get_topology_data() -> dict:
    """
    Full topology graph: every candidate (= pipe) as an individual node,
    connected to its fabric plane and source system.

    Node types: pipe, fabric_plane, source_system
    Edge types: pipe_in_plane, pipe_from_source
    """
    db_planes, type_to_plane = _load_plane_lookups()

    nodes = []
    edges = []
    fabric_planes_found: set[str] = set()
    source_systems: set[str] = set()

    candidates = sb.select("connection_candidates")

    for c in candidates:
        cid = c["candidate_id"]
        vendor = c["vendor_name"]
        plane_id = _resolve_candidate_plane(c, db_planes, type_to_plane)

        fabric_planes_found.add(plane_id)
        source_systems.add(vendor)

        plane_type = plane_id.split(":")[0] if ":" in plane_id else plane_id
        endpoints = json.loads(c["known_endpoints"]) if c.get("known_endpoints") else []
        nodes.append({
            "id": f"pipe:{cid}",
            "type": "pipe",
            "label": c["display_name"],
            "metadata": {
                "pipe_id": cid,
                "fabric_plane": plane_type,
                "source_system": vendor,
                "modality": c.get("preferred_modality") or "DECLARED_INTERFACE",
                "category": c["category"],
                "status": c["status"],
                "endpoints": endpoints,
            },
        })

        edges.append({
            "id": f"edge:pipe_plane:{cid}",
            "source": f"pipe:{cid}",
            "target": f"plane:{plane_id}",
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

    for plane_id in fabric_planes_found:
        nodes.append(_make_plane_node(plane_id, db_planes))

    for source in source_systems:
        nodes.append({
            "id": f"source:{source}",
            "type": "source_system",
            "label": source,
            "metadata": {"source_system": source},
        })

    drift_rows = sb.select("drift_events", raw_params={"status": "eq.open"})
    pipes_with_drift = set(row["pipe_id"] for row in drift_rows)

    from ..constants import SOR_CATEGORIES
    sors_count = sum(
        1 for c in candidates
        if (c.get("category") or "").lower() in SOR_CATEGORIES
    )

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


def get_topology_for_pipe(pipe_id: str) -> dict:
    """Get topology centred on a specific pipe (= candidate)."""
    db_planes, type_to_plane = _load_plane_lookups()

    nodes = []
    edges = []

    candidate = sb.select(
        "connection_candidates",
        filters={"candidate_id": pipe_id},
        single=True,
    )

    if not candidate:
        return {"nodes": [], "edges": [], "stats": {}}

    vendor = candidate["vendor_name"]
    plane_id = _resolve_candidate_plane(candidate, db_planes, type_to_plane)
    plane_type = plane_id.split(":")[0] if ":" in plane_id else plane_id

    endpoints = json.loads(candidate["known_endpoints"]) if candidate.get("known_endpoints") else []
    nodes.append({
        "id": f"pipe:{pipe_id}",
        "type": "pipe",
        "label": candidate["display_name"],
        "metadata": {
            "pipe_id": pipe_id,
            "fabric_plane": plane_type,
            "source_system": vendor,
            "modality": candidate.get("preferred_modality") or "DECLARED_INTERFACE",
            "category": candidate["category"],
            "status": candidate["status"],
            "endpoints": endpoints,
            "central": True,
        },
    })

    nodes.append(_make_plane_node(plane_id, db_planes))

    nodes.append({
        "id": f"source:{vendor}",
        "type": "source_system",
        "label": vendor,
        "metadata": {"source_system": vendor},
    })

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

    drift_rows = sb.select(
        "drift_events",
        filters={"pipe_id": pipe_id},
        raw_params={"status": "eq.open"},
    )
    drift_events = [dict(d) for d in drift_rows]

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


def get_topology_for_fabric_plane(fabric_plane: str) -> dict:
    """Get topology for a specific fabric plane type — shows all candidates
    that route through that plane."""
    db_planes, type_to_plane = _load_plane_lookups()

    nodes = []
    edges = []
    source_systems: set[str] = set()

    vendor_planes = {
        pid: info for pid, info in db_planes.items() if info["plane_type"] == fabric_plane
    }

    if vendor_planes:
        for pid in vendor_planes:
            node = _make_plane_node(pid, db_planes)
            node["metadata"]["central"] = True
            nodes.append(node)
    else:
        nodes.append({
            "id": f"plane:{fabric_plane}",
            "type": "fabric_plane",
            "label": _PLANE_LABELS.get(fabric_plane, fabric_plane.replace("_", " ").title()),
            "metadata": {
                "plane_type": fabric_plane,
                "color": _PLANE_COLORS.get(fabric_plane, "#64748b"),
                "central": True,
            },
        })

    all_candidates = sb.select("connection_candidates")

    pipe_count = 0
    for c in all_candidates:
        resolved = _resolve_candidate_plane(c, db_planes, type_to_plane)
        resolved_type = resolved.split(":")[0] if ":" in resolved else resolved
        if resolved_type != fabric_plane:
            continue

        cid = c["candidate_id"]
        vendor = c["vendor_name"]
        source_systems.add(vendor)
        pipe_count += 1

        endpoints = json.loads(c["known_endpoints"]) if c.get("known_endpoints") else []
        nodes.append({
            "id": f"pipe:{cid}",
            "type": "pipe",
            "label": c["display_name"],
            "metadata": {
                "pipe_id": cid,
                "fabric_plane": fabric_plane,
                "source_system": vendor,
                "modality": c.get("preferred_modality") or "DECLARED_INTERFACE",
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

    for source in source_systems:
        nodes.append({
            "id": f"source:{source}",
            "type": "source_system",
            "label": source,
            "metadata": {"source_system": source},
        })

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
