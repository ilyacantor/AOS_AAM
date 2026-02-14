"""
Plane Resolution — THE single source of truth for resolving candidates to fabric planes.

Every topology builder, every pipe converter, every UI renderer calls this ONE
function.  There must be no other resolution logic anywhere in the codebase.

Resolution order:
  1. Explicit fabric_plane_id on the candidate (set during handoff)
  2. connected_via_plane type hint → find first plane of that type
  3. "UNMAPPED" sentinel (operator must categorize)
"""
from .constants import PLANE_TYPE_LABELS, PLANE_TYPE_COLORS, INFRA_VENDOR_PLANE
from .logger import get_logger

_log = get_logger("plane_resolution")


def parse_plane_type(plane_id: str) -> str:
    """Extract the type portion from a composite plane ID.

    "API_GATEWAY:Kong" -> "API_GATEWAY"
    "IPAAS"            -> "IPAAS"
    "UNMAPPED"         -> "UNMAPPED"
    """
    return plane_id.split(":", 1)[0] if ":" in plane_id else plane_id


def resolve_candidate_to_plane(
    candidate: dict,
    plane_info: dict,
    type_to_plane: dict,
) -> str:
    """Resolve a candidate to its vendor-specific fabric plane_id.

    Parameters
    ----------
    candidate : dict
        A candidate row (from list_candidates or sqlite3.Row-as-dict).
        Must have keys: fabric_plane_id, connected_via_plane.
    plane_info : dict
        plane_id -> plane record.  Keys are composite IDs like "API_GATEWAY:Kong".
    type_to_plane : dict
        plane_type -> first plane_id of that type.  e.g. {"API_GATEWAY": "API_GATEWAY:Kong"}.

    Returns
    -------
    str
        A plane_id that exists in plane_info, or "UNMAPPED".
    """
    # Step 1: explicit fabric_plane_id
    fpid = candidate.get("fabric_plane_id") or (
        candidate["fabric_plane_id"] if hasattr(candidate, "keys") and "fabric_plane_id" in (candidate.keys() if callable(getattr(candidate, "keys", None)) else []) else ""
    )
    if not fpid:
        fpid = ""
    if fpid and fpid in plane_info:
        return fpid

    # Step 2: connected_via_plane type hint
    connected = candidate.get("connected_via_plane") or ""
    if connected:
        plane_type = connected.upper()
        resolved = type_to_plane.get(plane_type)
        if resolved:
            return resolved

    # Step 3: UNMAPPED
    return "UNMAPPED"


def build_plane_lookups(db_planes: list[dict]) -> tuple[dict, dict]:
    """Build the two lookup dicts from a list of fabric plane records.

    Returns (plane_info, type_to_plane).
    """
    plane_info = {p["plane_id"]: p for p in db_planes}

    type_to_plane: dict[str, str] = {}
    for p in db_planes:
        if p["plane_type"] not in type_to_plane:
            type_to_plane[p["plane_type"]] = p["plane_id"]

    return plane_info, type_to_plane


def build_plane_node(plane_id: str, plane_info: dict, counts: dict | None = None) -> dict:
    """Build a topology node dict for a fabric plane.

    This is the ONE place plane nodes are created.  All topology builders
    call this function — no inline node construction.

    Parameters
    ----------
    plane_id : str
        Composite plane ID (e.g. "API_GATEWAY:Kong") or bare type ("UNMAPPED").
    plane_info : dict
        plane_id -> plane record lookup.
    counts : dict, optional
        {"connected": int, "total": int} for label formatting.

    Returns
    -------
    dict
        A topology node dict with id, type, label, metadata.
    """
    connected = counts.get("connected", 0) if counts else 0
    total = counts.get("total", 0) if counts else 0

    if plane_id in plane_info:
        info = plane_info[plane_id]
        vendor_display = info["vendor"].title()
        plane_type = info["plane_type"]
        type_label = PLANE_TYPE_LABELS.get(plane_type, plane_type.replace("_", " ").title())
        label = f"{vendor_display}, {type_label}"
        if counts:
            label += f"\n({connected} connected / {total} total)"
        return {
            "id": f"plane:{plane_id}",
            "type": "fabric_plane",
            "label": label,
            "metadata": {
                "plane_type": plane_type,
                "vendor": info["vendor"],
                "color": PLANE_TYPE_COLORS.get(plane_type, "#64748b"),
                "connected": connected,
                "total": total,
            },
        }
    else:
        # Bare type fallback (UNMAPPED or type not in DB)
        plane_type = parse_plane_type(plane_id)
        type_label = PLANE_TYPE_LABELS.get(plane_type, plane_type.replace("_", " ").title())
        label = type_label
        if counts:
            label += f"\n({connected} connected / {total} total)"
        return {
            "id": f"plane:{plane_id}",
            "type": "fabric_plane",
            "label": label,
            "metadata": {
                "plane_type": plane_type,
                "vendor": None,
                "color": PLANE_TYPE_COLORS.get(plane_type, "#64748b"),
                "connected": connected,
                "total": total,
            },
        }


def infer_transport_from_plane_and_endpoints(
    plane_type: str | None,
    vendor_name: str | None,
    endpoints: list[str] | None,
) -> str:
    """Infer transport_kind from plane type, vendor, and endpoint URLs.

    NOT hardcoded — actually examines the data.
    """
    vendor_lower = (vendor_name or "").lower()
    plane = (plane_type or "").upper()

    # Infrastructure vendors whose transport kind is definitional
    if plane == "EVENT_BUS" or vendor_lower in ("kafka", "confluent", "rabbitmq", "eventbridge", "pulsar"):
        return "EVENT_STREAM"
    if plane == "DATA_WAREHOUSE" or vendor_lower in ("snowflake", "bigquery", "redshift", "databricks"):
        return "TABLE"

    # URL pattern matching
    for ep in (endpoints or []):
        ep_lower = ep.lower()
        if any(kw in ep_lower for kw in ("kafka", "stream", "queue", "sns", "sqs", "event")):
            return "EVENT_STREAM"
        if any(kw in ep_lower for kw in ("snowflake", "bigquery", "redshift", "table", "sql", "warehouse")):
            return "TABLE"
        if any(kw in ep_lower for kw in ("webhook", "hook", "callback")):
            return "WEBHOOK"

    return "API"


def infer_modality_from_plane_and_category(
    plane_type: str | None,
    category: str | None,
    vendor_name: str | None,
) -> str:
    """Infer modality from plane type and category.

    NOT the old "if ipaas in category" hack — uses actual plane type.
    """
    plane = (plane_type or "").upper()
    vendor_lower = (vendor_name or "").lower()

    # iPaaS uses control plane (read-only visibility into integrations)
    if plane == "IPAAS" or vendor_lower in ("workato", "mulesoft", "boomi", "tray", "zapier", "celigo"):
        return "CONTROL_PLANE"

    # Event buses use passive subscription
    if plane == "EVENT_BUS" or vendor_lower in ("kafka", "confluent", "rabbitmq", "eventbridge", "pulsar"):
        return "PASSIVE_SUBSCRIPTION"

    # API Gateways and Data Warehouses use declared interface
    return "DECLARED_INTERFACE"
