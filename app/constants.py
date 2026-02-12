"""
AAM Shared Constants.

Single source of truth for category sets and mappings used
across handoff, topology, and reconciliation logic.
"""

# SOR (System of Record) categories recognized by AAM
SOR_CATEGORIES: set[str] = {
    "crm", "erp", "hcm", "idp", "itsm",
    "saas", "hr", "finance", "cmdb", "identity",
}

# Mapping from SOR category to default fabric plane type.
# Used in AOD handoff auto-inference and topology classification.
CATEGORY_TO_PLANE_TYPE: dict[str, str] = {
    "erp": "DATA_WAREHOUSE",
    "finance": "DATA_WAREHOUSE",
    "itsm": "IPAAS",
    "cmdb": "IPAAS",
    # Everything else defaults to API_GATEWAY
}


def infer_plane_type_from_category(category: str) -> str:
    """Return the default plane type for a given SOR category."""
    return CATEGORY_TO_PLANE_TYPE.get(category.lower(), "API_GATEWAY")


# Keywords in candidate display_name that signal a fabric-infrastructure vendor.
# Used by resolve_fabric_planes() when AOD omits the fabric_planes array.
DISPLAY_NAME_PLANE_HINTS: dict[str, str] = {
    "ipaas": "IPAAS",
    "api gateway": "API_GATEWAY",
    "event bus": "EVENT_BUS",
    "data warehouse": "DATA_WAREHOUSE",
}
