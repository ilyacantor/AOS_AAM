"""
AAM Shared Constants.

Single source of truth for category sets and mappings used
across handoff, topology, and reconciliation logic.

DESIGN RULE: AAM never infers infrastructure (fabric planes) from
application categories.  Knowing something is a "CRM" or "ERP" tells
you nothing about which integration infrastructure the enterprise
deployed.  Only AOD-discovered infrastructure evidence or explicit
operator declarations create fabric plane records.
"""

# SOR (System of Record) categories recognized by AAM
SOR_CATEGORIES: set[str] = {
    "crm", "erp", "hcm", "idp", "itsm",
    "saas", "hr", "finance", "cmdb", "identity",
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
