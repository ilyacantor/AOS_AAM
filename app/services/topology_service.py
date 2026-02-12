"""
Topology Service — builds lightweight topology summaries for the UI.

When Farm provides authoritative SOR declarations (via AOD), those
take precedence over candidate-derived SOR classifications.
"""
from datetime import datetime

from ..logger import get_logger
from ..constants import SOR_CATEGORIES
from ..db import list_pipes, list_candidates, get_canonical_stats
from ..db.fabric_planes import get_fabric_planes
from ..db.sor_declarations import get_sor_declarations

_log = get_logger("services.topology")

PLANE_LABELS = {
    "IPAAS": "iPaaS",
    "API_GATEWAY": "API Gateway",
    "EVENT_BUS": "Event Bus",
    "DATA_WAREHOUSE": "Data Warehouse",
}


def _extract_plane_type(fabric_plane_id: str, connected_via: str) -> str:
    """Extract plane type from composite ID (e.g. 'IPAAS:workato' -> 'IPAAS')."""
    if fabric_plane_id and ":" in fabric_plane_id:
        return fabric_plane_id.split(":", 1)[0].upper()
    if connected_via:
        return connected_via.upper()
    return "UNMAPPED"


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
    all_pipes = list_pipes()

    # Build plane info lookup by plane_id (e.g. "IPAAS:workato")
    plane_info = {p["plane_id"]: p for p in db_planes}

    # Build type-to-first-plane fallback for candidates without fabric_plane_id
    type_to_plane: dict[str, str] = {}
    for p in db_planes:
        if p["plane_type"] not in type_to_plane:
            type_to_plane[p["plane_type"]] = p["plane_id"]

    # Build pipe_id → fabric_plane lookup for matched-pipe resolution
    pipe_planes: dict[str, str] = {}
    for p in all_pipes:
        fp = p.get("fabric_plane", "")
        if fp and fp not in ("UNMAPPED", "UNKNOWN"):
            pipe_planes[p["pipe_id"]] = fp

    def _resolve_plane_id(candidate: dict) -> str:
        """Resolve a candidate to its vendor-specific fabric plane_id.

        Resolution order:
          1. Explicit fabric_plane_id on the candidate
          2. connected_via_plane type hint → type_to_plane lookup
          3. Matched pipe's fabric_plane (backfill for pre-propagation data)
          4. "UNMAPPED" (operator must categorize)
        """
        fpid = candidate.get("fabric_plane_id", "")
        if fpid and fpid in plane_info:
            return fpid
        plane_type = _extract_plane_type(
            candidate.get("fabric_plane_id", ""),
            candidate.get("connected_via_plane", ""),
        )
        resolved = type_to_plane.get(plane_type)
        if resolved:
            return resolved

        # Fallback: check matched pipe's fabric_plane
        matched_pid = candidate.get("matched_pipe_id", "")
        if matched_pid and matched_pid in pipe_planes:
            return type_to_plane.get(pipe_planes[matched_pid], pipe_planes[matched_pid])

        return "UNMAPPED"

    # Count candidates (= pipes) per vendor-plane
    vendor_plane_counts: dict[str, dict] = {}
    for c in candidates:
        pid = _resolve_plane_id(c)
        if pid:
            counts = vendor_plane_counts.setdefault(pid, {"pipe_count": 0, "cand_count": 0})
            counts["pipe_count"] += 1
            counts["cand_count"] += 1

    # Load authoritative SOR declarations from Farm (if any)
    auth_sors = get_sor_declarations()
    auth_sor_vendors: dict[str, dict] = {}
    for s in auth_sors:
        vendor_key = s["vendor"]
        auth_sor_vendors[vendor_key.lower()] = s
        _log.debug("Authoritative SOR: %s (domain=%s, category=%s)", vendor_key, s["domain"], s["category"])

    # Build SOR systems from candidates + authoritative SORs.
    # planes set now stores vendor-specific plane_ids (e.g. "IPAAS:workato")
    sor_systems: dict = {}
    display_names: dict = {}

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
            "confidence": decl.get("confidence", "unknown"),
        }

    for c in candidates:
        vendor = c.get("vendor_name")
        if not vendor:
            continue
        key = vendor.lower()
        if key not in sor_systems:
            sor_systems[key] = {
                "pipe_count": 0, "candidate_count": 0,
                "planes": set(), "is_candidate": True, "is_sor": False, "category": None,
            }
            display_names[key] = vendor
        sor_systems[key]["pipe_count"] += 1
        sor_systems[key]["candidate_count"] = sor_systems[key].get("candidate_count", 0) + 1
        if "is_candidate" not in sor_systems[key]:
            sor_systems[key]["is_candidate"] = True
        category = c.get("category", "").lower()
        if category in SOR_CATEGORIES:
            sor_systems[key]["is_sor"] = True
            if not sor_systems[key].get("category"):
                sor_systems[key]["category"] = category
        pid = _resolve_plane_id(c)
        if pid and pid != "OTHER":
            sor_systems[key]["planes"].add(pid)

    # Create nodes + edges
    nodes = []
    edges = []

    # Vendor-specific fabric plane nodes
    created_plane_ids: set[str] = set()
    for plane_id, info in plane_info.items():
        counts = vendor_plane_counts.get(plane_id, {"pipe_count": 0, "cand_count": 0})
        vendor_display = info["vendor"].title()
        type_label = PLANE_LABELS.get(info["plane_type"], info["plane_type"].replace("_", " ").title())
        nodes.append({
            "id": f"plane:{plane_id}",
            "label": f"{vendor_display}, {type_label}\n({counts['pipe_count']}/{counts['cand_count']})",
            "type": "fabric_plane",
            "metadata": {
                "plane_type": info["plane_type"],
                "vendor": info["vendor"],
                "pipe_count": counts["pipe_count"],
                "candidate_count": counts["cand_count"],
            },
        })
        created_plane_ids.add(plane_id)

    # Fallback: create type-based nodes for any planes referenced but not in DB
    for sor_data in sor_systems.values():
        for pid in sor_data.get("planes", []):
            if pid not in created_plane_ids:
                plane_type = pid.split(":", 1)[0] if ":" in pid else pid
                type_label = PLANE_LABELS.get(plane_type, plane_type.replace("_", " ").title())
                counts = vendor_plane_counts.get(pid, {"pipe_count": 0, "cand_count": 0})
                nodes.append({
                    "id": f"plane:{pid}",
                    "label": f"{type_label}\n({counts['pipe_count']}/{counts['cand_count']})",
                    "type": "fabric_plane",
                    "metadata": {"plane_type": plane_type, "pipe_count": counts["pipe_count"], "candidate_count": counts["cand_count"]},
                })
                created_plane_ids.add(pid)

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
