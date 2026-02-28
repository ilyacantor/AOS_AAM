"""
AAM Shared Constants.

Single source of truth for category sets and mappings used
across handoff, topology, and reconciliation logic.

DESIGN RULE (RACI v6): AOD identifies fabric planes (A/R for Fabric Plane Identification).
AAM owns Fabric Plane Connection (A/R) — validates and connects to planes detected by AOD.
AOD provides plane type, vendor, and evidence tier. AAM uses these to establish
connectivity (pipe blueprints, work orders). Application categories alone are not
sufficient, but combined with AOD's detection evidence they inform connection strategy.
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
    "warehouse": "DATA_WAREHOUSE",
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
    "azure apim": "API_GATEWAY",
    "kafka": "EVENT_BUS",
    "confluent": "EVENT_BUS",
    "rabbitmq": "EVENT_BUS",
    "eventbridge": "EVENT_BUS",
    "snowflake": "DATA_WAREHOUSE",
    "bigquery": "DATA_WAREHOUSE",
    "redshift": "DATA_WAREHOUSE",
    "databricks": "DATA_WAREHOUSE",
}


# ---------------------------------------------------------------------------
# Standard field definitions per application category.
#
# These represent the typical schema fields exposed by each category of
# enterprise system.  AAM uses these as inferred field definitions when
# live schema discovery (observations) has not yet produced concrete
# field lists.  DCL consumes these to build semantic mappings.
#
# DESIGN: This is metadata inference — AAM's core responsibility.
# The field names are real-world-accurate defaults for each category,
# enabling DCL to perform semantic mapping (field name → business concept)
# even before live adapters have been connected.
# ---------------------------------------------------------------------------
CATEGORY_STANDARD_FIELDS: dict[str, list[str]] = {
    "crm": [
        "account_id", "account_name", "contact_id", "contact_name", "email",
        "phone", "opportunity_id", "deal_stage", "deal_amount", "owner_id",
        "created_date", "modified_date", "industry", "annual_revenue", "status",
    ],
    "erp": [
        "entity_id", "company_code", "fiscal_year", "posting_date", "document_number",
        "gl_account", "cost_center", "amount", "currency", "vendor_id",
        "material_number", "plant", "profit_center", "created_date", "modified_date",
    ],
    "hcm": [
        "employee_id", "first_name", "last_name", "department", "job_title",
        "hire_date", "manager_id", "salary", "location", "employment_status",
        "email", "cost_center", "org_unit", "created_date", "modified_date",
    ],
    "hr": [
        "employee_id", "first_name", "last_name", "department", "job_title",
        "hire_date", "manager_id", "salary", "location", "employment_status",
        "email", "cost_center", "org_unit", "created_date", "modified_date",
    ],
    "itsm": [
        "incident_id", "ticket_number", "priority", "status", "category",
        "assigned_to", "created_date", "resolved_date", "description", "impact",
        "urgency", "sla_breach", "requester_id", "asset_id", "modified_date",
    ],
    "idp": [
        "user_id", "username", "email", "display_name", "status",
        "last_login", "mfa_enabled", "groups", "roles", "created_date",
        "provider", "federation_id", "session_count", "risk_score", "modified_date",
    ],
    "identity": [
        "user_id", "username", "email", "display_name", "status",
        "last_login", "mfa_enabled", "groups", "roles", "created_date",
        "provider", "federation_id", "session_count", "risk_score", "modified_date",
    ],
    "finance": [
        "transaction_id", "account_number", "amount", "currency", "transaction_date",
        "posting_date", "vendor_id", "invoice_number", "payment_status", "cost_center",
        "gl_code", "department", "description", "created_date", "modified_date",
    ],
    "saas": [
        "subscription_id", "account_id", "plan_name", "status", "mrr",
        "seats_licensed", "seats_used", "renewal_date", "owner_id", "created_date",
        "usage_score", "last_active", "integration_count", "modified_date", "domain",
    ],
    "cmdb": [
        "ci_id", "ci_name", "ci_type", "status", "environment",
        "owner", "department", "vendor", "version", "ip_address",
        "location", "criticality", "last_discovered", "created_date", "modified_date",
    ],
    "ipaas": [
        "workflow_id", "workflow_name", "run_id", "status", "trigger_type",
        "duration", "error_count", "source_app", "target_app", "created_at",
        "updated_at",
    ],
    # "other" is AOD's catch-all for infrastructure platforms that don't fit
    # SOR categories.  Generic fields that DCL can still map semantically.
    "other": [
        "resource_id", "resource_name", "region", "status", "resource_type",
        "tags", "created_at", "updated_at",
    ],
}


# ---------------------------------------------------------------------------
# Standard field definitions per fabric plane type.
#
# Infrastructure platforms categorised as "other" by AOD are really fabric
# plane vendors (Kong → API_GATEWAY, Snowflake → DATA_WAREHOUSE, etc.).
# These fields describe what that plane type exposes to downstream consumers.
# Used when a candidate's vendor maps to a known plane via INFRA_VENDOR_PLANE.
#
# Naming: vendor-neutral.  "workflow_id" not "recipe_id" (Workato-specific).
# ---------------------------------------------------------------------------
PLANE_STANDARD_FIELDS: dict[str, list[str]] = {
    "IPAAS": [
        "workflow_id", "workflow_name", "run_id", "status", "trigger_type",
        "duration", "error_count", "source_app", "target_app", "created_at",
        "updated_at",
    ],
    "API_GATEWAY": [
        "api_id", "api_name", "route_path", "method", "consumer_id",
        "rate_limit", "upstream_url", "status", "latency_ms", "request_count",
        "error_rate", "version", "tags", "created_at", "updated_at",
    ],
    "EVENT_BUS": [
        "topic_name", "partition_count", "consumer_group", "message_count", "offset",
        "retention_ms", "schema_id", "producer_id", "consumer_lag", "throughput",
        "replication_factor", "status", "created_at", "updated_at",
    ],
    "DATA_WAREHOUSE": [
        "table_name", "schema_name", "database_name", "row_count", "column_count",
        "size_bytes", "last_modified", "owner", "cluster_id", "storage_type",
        "query_count", "freshness_hours", "tags", "created_at", "updated_at",
    ],
}
