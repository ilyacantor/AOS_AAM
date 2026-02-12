"""
Topology Service — builds lightweight topology summaries for the UI.
"""
from datetime import datetime

from ..logger import get_logger
from ..constants import SOR_CATEGORIES, infer_plane_type_from_category
from ..db import list_pipes, list_candidates, get_canonical_stats

_log = get_logger("services.topology")

PLANE_LABELS = {
    "IPAAS": "iPaaS",
    "API_GATEWAY": "API Gateway",
    "EVENT_BUS": "Event Bus",
    "DATA_WAREHOUSE": "Data Warehouse",
}


def build_topology_summary() -> dict:
    """
    Build a lightweight topology showing only Fabric Planes and SORs.

    Optimised for large datasets — shows aggregate counts instead of
    individual assets, suitable for 600+ asset inventories.
    """
    pipes = list_pipes()
    candidates = list_candidates()

    # Fabric-plane pipe counts
    fabric_counts = {"IPAAS": 0, "API_GATEWAY": 0, "EVENT_BUS": 0, "DATA_WAREHOUSE": 0}
    for p in pipes:
        plane = p.get("fabric_plane", "API_GATEWAY")
        if plane in fabric_counts:
            fabric_counts[plane] += 1

    # Candidate counts by plane
    candidate_counts = {"IPAAS": 0, "API_GATEWAY": 0, "EVENT_BUS": 0, "DATA_WAREHOUSE": 0, "OTHER": 0}
    for c in candidates:
        fabric_plane_id = c.get("fabric_plane_id", "")
        connected_via = c.get("connected_via_plane", "")
        if fabric_plane_id and ":" in fabric_plane_id:
            plane = fabric_plane_id.split(":")[0].upper()
        elif connected_via:
            plane = connected_via.upper()
        else:
            plane = "OTHER"
        if plane in candidate_counts:
            candidate_counts[plane] += 1
        else:
            candidate_counts["OTHER"] += 1

    # Build SOR systems from pipes + candidates
    sor_systems: dict = {}
    for p in pipes:
        source = p.get("source_system")
        if source:
            if source not in sor_systems:
                sor_systems[source] = {"pipe_count": 0, "candidate_count": 0, "planes": set(), "is_sor": False, "category": None}
            sor_systems[source]["pipe_count"] += 1
            sor_systems[source]["planes"].add(p.get("fabric_plane", "API_GATEWAY"))

    for c in candidates:
        vendor = c.get("vendor_name")
        if vendor:
            if vendor not in sor_systems:
                sor_systems[vendor] = {"pipe_count": 0, "candidate_count": 0, "planes": set(), "is_candidate": True, "is_sor": False, "category": None}
            sor_systems[vendor]["candidate_count"] = sor_systems[vendor].get("candidate_count", 0) + 1
            if "is_candidate" not in sor_systems[vendor]:
                sor_systems[vendor]["is_candidate"] = True
            category = c.get("category", "").lower()
            if category in SOR_CATEGORIES:
                sor_systems[vendor]["is_sor"] = True
                sor_systems[vendor]["category"] = category
            fabric_plane_id = c.get("fabric_plane_id", "")
            connected_via = c.get("connected_via_plane", "")
            if fabric_plane_id and ":" in fabric_plane_id:
                sor_systems[vendor]["planes"].add(fabric_plane_id.split(":")[0].upper())
            elif connected_via:
                sor_systems[vendor]["planes"].add(connected_via.upper())

    # Create nodes + edges
    nodes = []
    edges = []

    for plane, label in PLANE_LABELS.items():
        pipe_count = fabric_counts.get(plane, 0)
        cand_count = candidate_counts.get(plane, 0)
        nodes.append({
            "id": f"plane:{plane}",
            "label": f"{label}\n({pipe_count} pipes, {cand_count} candidates)",
            "type": "fabric_plane",
            "metadata": {"plane_type": plane, "pipe_count": pipe_count, "candidate_count": cand_count},
        })

    # Prioritize true SORs, then fill with top others (up to 20)
    true_sors = sorted(
        [(n, d) for n, d in sor_systems.items() if d.get("is_sor")],
        key=lambda x: x[1]["pipe_count"] + x[1].get("candidate_count", 0),
        reverse=True,
    )
    other_systems = sorted(
        [(n, d) for n, d in sor_systems.items() if not d.get("is_sor")],
        key=lambda x: x[1]["pipe_count"] + x[1].get("candidate_count", 0),
        reverse=True,
    )
    remaining_slots = max(0, 20 - len(true_sors))
    sorted_sors = true_sors + other_systems[:remaining_slots]

    for sor_name, sor_data in sorted_sors:
        pc = sor_data["pipe_count"]
        cc = sor_data.get("candidate_count", 0)
        if pc > 0 and cc > 0:
            label = f"{sor_name}\n({pc} pipes, {cc} candidates)"
        elif cc > 0:
            label = f"{sor_name}\n({cc} candidates)"
        else:
            label = f"{sor_name}\n({pc} pipes)"

        nodes.append({
            "id": f"sor:{sor_name}",
            "label": label,
            "type": "source_system",
            "metadata": {
                "name": sor_name,
                "pipe_count": pc,
                "candidate_count": cc,
                "is_candidate_source": sor_data.get("is_candidate", False),
                "is_sor": sor_data.get("is_sor", False),
                "category": sor_data.get("category"),
            },
        })
        for plane in sor_data.get("planes", []):
            edges.append({
                "id": f"sor_to_plane:{sor_name}:{plane}",
                "source": f"sor:{sor_name}",
                "target": f"plane:{plane}",
                "type": "sor_in_plane",
            })

    canonical_stats = get_canonical_stats()

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            **canonical_stats,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "source_systems": len(sorted_sors),
        },
        "generated_at": datetime.utcnow().isoformat(),
    }
