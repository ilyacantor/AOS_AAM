"""
Topology Service — builds lightweight topology summaries for the UI.

When Farm provides authoritative SOR declarations (via AOD), those
take precedence over candidate-derived SOR classifications.

Resolution logic is in ``app.plane_resolution`` — the single source of truth
for mapping candidates to fabric planes.  This module MUST NOT duplicate it.
"""
from datetime import datetime

from ..logger import get_logger
from ..constants import SOR_CATEGORIES
from ..db import list_declared_pipes, list_candidates, get_canonical_stats
from ..db.fabric_planes import get_fabric_planes
from ..db.sor_declarations import get_sor_declarations
from ..plane_resolution import (
    resolve_candidate_to_plane,
    build_plane_lookups,
    build_plane_node,
    parse_plane_type,
)

_log = get_logger("services.topology")


def build_topology_summary() -> dict:
    """
    Build a lightweight topology showing only Fabric Planes and SORs.

    Optimised for large datasets — shows aggregate counts instead of
    individual assets, suitable for 600+ asset inventories.

    Fabric plane nodes are vendor-specific (e.g. "Workato, iPaaS (5/5)")
    rather than generic type-only nodes.
    """
    candidates = list_candidates()
    db_planes = get_fabric_planes()

    # Single shared resolution lookups (from plane_resolution module)
    plane_info, type_to_plane = build_plane_lookups(db_planes)

    # Count candidates per vendor-plane, split by match status
    vendor_plane_counts: dict[str, dict] = {}
    for c in candidates:
        pid = resolve_candidate_to_plane(c, plane_info, type_to_plane)
        counts = vendor_plane_counts.setdefault(pid, {"connected": 0, "total": 0})
        counts["total"] += 1
        if c.get("matched_pipe_id"):
            counts["connected"] += 1

    # Load authoritative SOR declarations from Farm (if any)
    auth_sors = get_sor_declarations()
    auth_sor_vendors: dict[str, dict] = {}
    for s in auth_sors:
        vendor_key = s["vendor"]
        auth_sor_vendors[vendor_key.lower()] = s
        _log.debug("Authoritative SOR: %s (domain=%s, category=%s)", vendor_key, s["domain"], s["category"])

    # Build SOR systems from candidates + authoritative SORs.
    sor_systems: dict = {}
    display_names: dict = {}

    # Seed with authoritative SOR declarations first
    for vendor_lower, decl in auth_sor_vendors.items():
        display_names[vendor_lower] = decl["vendor"]
        sor_systems[vendor_lower] = {
            "connected": 0,
            "total": 0,
            "planes": set(),
            "is_sor": True,
            "is_authoritative": True,
            "category": decl.get("category") or None,
            "domain": decl.get("domain"),
            "confidence": decl.get("confidence", "unknown"),
        }

    for c in candidates:
        vendor = c.get("vendor_name")
        if not vendor:
            continue
        key = vendor.lower()
        if key not in sor_systems:
            sor_systems[key] = {
                "connected": 0, "total": 0,
                "planes": set(), "is_candidate": True, "is_sor": False, "category": None,
            }
            display_names[key] = vendor
        sor_systems[key]["total"] = sor_systems[key].get("total", 0) + 1
        if c.get("matched_pipe_id"):
            sor_systems[key]["connected"] = sor_systems[key].get("connected", 0) + 1
        if "is_candidate" not in sor_systems[key]:
            sor_systems[key]["is_candidate"] = True
        category = c.get("category", "").lower()
        if category in SOR_CATEGORIES:
            sor_systems[key]["is_sor"] = True
            if not sor_systems[key].get("category"):
                sor_systems[key]["category"] = category
        pid = resolve_candidate_to_plane(c, plane_info, type_to_plane)
        if pid and pid != "OTHER":
            sor_systems[key]["planes"].add(pid)

    # Create nodes + edges
    nodes = []
    edges = []

    # Vendor-specific fabric plane nodes — built by shared build_plane_node()
    created_plane_ids: set[str] = set()
    for plane_id in plane_info:
        counts = vendor_plane_counts.get(plane_id, {"connected": 0, "total": 0})
        node = build_plane_node(plane_id, plane_info, counts)
        nodes.append(node)
        created_plane_ids.add(plane_id)

    # Fallback: create nodes for any planes referenced but not in DB (e.g. UNMAPPED)
    for sor_data in sor_systems.values():
        for pid in sor_data.get("planes", []):
            if pid not in created_plane_ids:
                counts = vendor_plane_counts.get(pid, {"connected": 0, "total": 0})
                node = build_plane_node(pid, plane_info, counts)
                nodes.append(node)
                created_plane_ids.add(pid)

    # Prioritize true SORs, then fill with top others (up to 20)
    true_sors = sorted(
        [(k, d) for k, d in sor_systems.items() if d.get("is_sor")],
        key=lambda x: x[1]["total"],
        reverse=True,
    )
    other_systems = sorted(
        [(k, d) for k, d in sor_systems.items() if not d.get("is_sor")],
        key=lambda x: x[1]["total"],
        reverse=True,
    )
    remaining_slots = max(0, 20 - len(true_sors))
    sorted_sors = true_sors + other_systems[:remaining_slots]

    for sor_key, sor_data in sorted_sors:
        sor_name = display_names.get(sor_key, sor_key)
        connected = sor_data.get("connected", 0)
        total = sor_data.get("total", 0)
        if total > 0:
            label = f"{sor_name}\n({connected}/{total} connected)"
        else:
            label = f"{sor_name}\n(0 candidates)"

        nodes.append({
            "id": f"sor:{sor_name}",
            "label": label,
            "type": "source_system",
            "metadata": {
                "name": sor_name,
                "connected": connected,
                "total": total,
                "is_candidate_source": sor_data.get("is_candidate", False),
                "is_sor": sor_data.get("is_sor", False),
                "is_authoritative": sor_data.get("is_authoritative", False),
                "category": sor_data.get("category"),
                "domain": sor_data.get("domain"),
                "confidence": sor_data.get("confidence"),
            },
        })
        for plane_id in sor_data.get("planes", []):
            if plane_id in created_plane_ids:
                edges.append({
                    "id": f"sor_to_plane:{sor_name}:{plane_id}",
                    "source": f"sor:{sor_name}",
                    "target": f"plane:{plane_id}",
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
