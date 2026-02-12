"""
Topology Service — builds lightweight topology summaries for the UI.

When Farm provides authoritative SOR declarations (via AOD), those
take precedence over candidate-derived SOR classifications.
"""
from datetime import datetime

from ..logger import get_logger
from ..constants import SOR_CATEGORIES, infer_plane_type_from_category
from ..db import list_pipes, list_candidates, get_canonical_stats
from ..db.sor_declarations import get_sor_declarations

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

    # Load authoritative SOR declarations from Farm (if any)
    auth_sors = get_sor_declarations()
    auth_sor_vendors: dict[str, dict] = {}
    for s in auth_sors:
        vendor_key = s["vendor"]
        auth_sor_vendors[vendor_key.lower()] = s
        _log.debug("Authoritative SOR: %s (domain=%s, category=%s)", vendor_key, s["domain"], s["category"])

    # Build SOR systems from pipes + candidates + authoritative SORs.
    # Use case-insensitive keys internally to merge entries, but
    # prefer the authoritative vendor name for display.
    sor_systems: dict = {}        # lowercase key -> data
    display_names: dict = {}      # lowercase key -> display name

    # Seed with authoritative SOR declarations first
    for vendor_lower, decl in auth_sor_vendors.items():
        display_names[vendor_lower] = decl["vendor"]
        sor_systems[vendor_lower] = {
            "pipe_count": 0,
            "candidate_count": 0,
            "planes": set(),
            "is_sor": True,
            "is_authoritative": True,
            "category": decl.get("category") or None,
            "domain": decl.get("domain"),
            "confidence": decl.get("confidence", "high"),
        }

    for p in pipes:
        source = p.get("source_system")
        if source:
            key = source.lower()
            if key not in sor_systems:
                sor_systems[key] = {"pipe_count": 0, "candidate_count": 0, "planes": set(), "is_sor": False, "category": None}
                display_names[key] = source
            sor_systems[key]["pipe_count"] += 1
            sor_systems[key]["planes"].add(p.get("fabric_plane", "API_GATEWAY"))

    for c in candidates:
        vendor = c.get("vendor_name")
        if vendor:
            key = vendor.lower()
            if key not in sor_systems:
                sor_systems[key] = {"pipe_count": 0, "candidate_count": 0, "planes": set(), "is_candidate": True, "is_sor": False, "category": None}
                display_names[key] = vendor
            sor_systems[key]["candidate_count"] = sor_systems[key].get("candidate_count", 0) + 1
            if "is_candidate" not in sor_systems[key]:
                sor_systems[key]["is_candidate"] = True
            category = c.get("category", "").lower()
            if category in SOR_CATEGORIES:
                sor_systems[key]["is_sor"] = True
                if not sor_systems[key].get("category"):
                    sor_systems[key]["category"] = category
            fabric_plane_id = c.get("fabric_plane_id", "")
            connected_via = c.get("connected_via_plane", "")
            if fabric_plane_id and ":" in fabric_plane_id:
                sor_systems[key]["planes"].add(fabric_plane_id.split(":")[0].upper())
            elif connected_via:
                sor_systems[key]["planes"].add(connected_via.upper())

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
        [(k, d) for k, d in sor_systems.items() if d.get("is_sor")],
        key=lambda x: x[1]["pipe_count"] + x[1].get("candidate_count", 0),
        reverse=True,
    )
    other_systems = sorted(
        [(k, d) for k, d in sor_systems.items() if not d.get("is_sor")],
        key=lambda x: x[1]["pipe_count"] + x[1].get("candidate_count", 0),
        reverse=True,
    )
    remaining_slots = max(0, 20 - len(true_sors))
    sorted_sors = true_sors + other_systems[:remaining_slots]

    for sor_key, sor_data in sorted_sors:
        sor_name = display_names.get(sor_key, sor_key)
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
                "is_authoritative": sor_data.get("is_authoritative", False),
                "category": sor_data.get("category"),
                "domain": sor_data.get("domain"),
                "confidence": sor_data.get("confidence"),
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
