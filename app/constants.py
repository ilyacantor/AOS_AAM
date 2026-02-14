"""
AAM Shared Constants.

Single source of truth for category sets and mappings used
across handoff, topology, and reconciliation logic.

DESIGN RULE (RACI v4): AAM owns Fabric Plane Inference (A/R).
AOD provides evidence leads (hints). AAM uses vendor identity,
display name hints, evidence leads, and endpoint signal analysis
to infer fabric plane. Application categories alone are not
sufficient, but combined with evidence they inform inference.
"""

# SOR (System of Record) categories recognized by AAM
SOR_CATEGORIES: set[str] = {
    "crm", "erp", "hcm", "idp", "itsm",
    "saas", "hr", "finance", "cmdb", "identity",
}

# Canonical fabric plane types
ALL_PLANE_TYPES: list[str] = ["IPAAS", "API_GATEWAY", "EVENT_BUS", "DATA_WAREHOUSE"]

# UI display labels for plane types
PLANE_TYPE_LABELS: dict[str, str] = {
    "IPAAS": "iPaaS",
    "API_GATEWAY": "API Gateway",
    "EVENT_BUS": "Event Bus",
    "DATA_WAREHOUSE": "Data Warehouse",
}

# Short abbreviations for plane types (used in compact tables)
PLANE_TYPE_SHORT: dict[str, str] = {
    "IPAAS": "iPaaS",
    "API_GATEWAY": "API GW",
    "EVENT_BUS": "Event Bus",
    "DATA_WAREHOUSE": "DW",
}

# UI accent colors per plane type (CSS color values)
PLANE_TYPE_COLORS: dict[str, str] = {
    "IPAAS": "#22d3ee",
    "API_GATEWAY": "#a78bfa",
    "EVENT_BUS": "#f97316",
    "DATA_WAREHOUSE": "#10b981",
}

# UI accent colors per SOR category (CSS variable references)
SOR_CATEGORY_COLORS: dict[str, str] = {
    "crm": "var(--cyan-400)", "erp": "var(--blue-400)", "hcm": "var(--green-400)",
    "idp": "var(--purple-400)", "itsm": "var(--orange-400)", "finance": "var(--emerald-400)",
    "saas": "var(--pink-400)", "hr": "var(--green-400)", "cmdb": "var(--amber-400)",
    "identity": "var(--purple-400)", "other": "var(--slate-400)", "unknown": "var(--slate-500)",
}

# UI display labels for SOR categories (upper-case presentation)
SOR_CATEGORY_LABELS: dict[str, str] = {
    "crm": "CRM", "erp": "ERP", "hcm": "HCM", "idp": "Identity", "itsm": "ITSM",
    "saas": "SaaS", "hr": "HR", "finance": "Finance", "cmdb": "CMDB", "identity": "Identity",
}

# Keywords in candidate display_name that signal a fabric-infrastructure vendor.
# These are NOT category inferences — they match explicit infrastructure labels
# that AOD attached to candidate records (e.g. "MuleSoft - iPaaS").
DISPLAY_NAME_PLANE_HINTS: dict[str, str] = {
    "ipaas": "IPAAS",
    "api gateway": "API_GATEWAY",
    "event bus": "EVENT_BUS",
    "event hub": "EVENT_BUS",
    "data warehouse": "DATA_WAREHOUSE",
}

# Well-known infrastructure vendors whose identity alone signals a plane type.
# This is vendor identity, NOT category inference — Kafka *is* an event bus,
# Snowflake *is* a data warehouse.  These are infrastructure products, not
# applications that happen to be in a category.
# Aliases for plane_type strings AOD may send (various casings/formats).
# Used during normalization of incoming handoff payloads.
PLANE_TYPE_ALIASES: dict[str, str] = {
    "ipaas": "IPAAS", "iPaaS": "IPAAS",
    "api_gateway": "API_GATEWAY", "api gateway": "API_GATEWAY", "apigateway": "API_GATEWAY",
    "event_bus": "EVENT_BUS", "event bus": "EVENT_BUS", "eventbus": "EVENT_BUS",
    "data_warehouse": "DATA_WAREHOUSE", "data warehouse": "DATA_WAREHOUSE", "datawarehouse": "DATA_WAREHOUSE",
}

# Well-known infrastructure vendors whose identity alone signals a plane type.
# This is vendor identity, NOT category inference — Kafka *is* an event bus,
# Snowflake *is* a data warehouse.  These are infrastructure products, not
# applications that happen to be in a category.
INFRA_VENDOR_PLANE: dict[str, str] = {
    "workato": "IPAAS",
    "mulesoft": "IPAAS",
    "boomi": "IPAAS",
    "zapier": "IPAAS",
    "tray": "IPAAS",
    "celigo": "IPAAS",
    "kong": "API_GATEWAY",
    "apigee": "API_GATEWAY",
    "aws api gateway": "API_GATEWAY",
    "kafka": "EVENT_BUS",
    "confluent": "EVENT_BUS",
    "rabbitmq": "EVENT_BUS",
    "eventbridge": "EVENT_BUS",
    "snowflake": "DATA_WAREHOUSE",
    "bigquery": "DATA_WAREHOUSE",
    "redshift": "DATA_WAREHOUSE",
    "databricks": "DATA_WAREHOUSE",
}
