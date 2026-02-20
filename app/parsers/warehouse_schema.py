"""
Warehouse Schema Parsers — extract field-level inventory and lineage
from Data Warehouse metadata.

Layer A: information_schema column inventory
Layer B: dbt manifest.json field-level lineage (separate module)
Layer C: Query logs (Sprint 4 — not implemented here)
"""
import logging
import uuid
from datetime import datetime
from typing import Optional

_log = logging.getLogger("aam.parser.warehouse_schema")


def parse_information_schema(
    columns: list[dict],
    *,
    warehouse_vendor: str = "snowflake",
    database_name: Optional[str] = None,
) -> list[dict]:
    """
    Parse information_schema column metadata into SemanticEdge dicts.

    Each column becomes an INFERRED edge representing "this field exists
    in this warehouse table, sourced from a replicated system."  The
    confidence is 0.70 because we know the field exists but not the
    exact source-to-target mapping (that requires dbt or iPaaS data).

    If the table name contains a recognizable system prefix
    (e.g., 'salesforce__account', 'netsuite__sales_order'), we infer
    the source system from the prefix.

    Args:
        columns: Rows from information_schema.columns, each with at least:
            - table_schema, table_name, column_name, data_type
            - Optionally: ordinal_position, is_nullable, column_default, comment
        warehouse_vendor: e.g., 'snowflake', 'bigquery', 'redshift'
        database_name: Optional database name for provenance

    Returns:
        List of SemanticEdge dicts (edge_type=INFERRED, confidence=0.70)
    """
    now = datetime.utcnow().isoformat()
    extraction_source = f"warehouse_{warehouse_vendor}"
    if database_name:
        extraction_source += f"_{database_name}"

    edges: list[dict] = []

    for col in columns:
        table_schema = col.get("table_schema", "public")
        table_name = col.get("table_name", "")
        column_name = col.get("column_name", "")
        data_type = col.get("data_type", "")

        if not table_name or not column_name:
            continue

        # Skip internal/system schemas
        if table_schema.lower() in ("information_schema", "pg_catalog", "pg_toast"):
            continue

        # Infer source system from table prefix conventions
        # Common patterns: 'salesforce__account', 'sf_account', 'netsuite_sales_order'
        source_system, source_object = _infer_source_from_table(table_name, table_schema)

        edges.append({
            "id": str(uuid.uuid4()),
            "source_system": source_system,
            "source_object": source_object,
            "source_field": column_name,
            "target_system": warehouse_vendor,
            "target_object": f"{table_schema}.{table_name}",
            "target_field": column_name,
            "edge_type": "INFERRED",
            "confidence": 0.70,
            "fabric_plane": "DATA_WAREHOUSE",
            "extraction_source": extraction_source,
            "transformation": None,
            "condition": None,
            "discovered_at": now,
            "last_verified": now,
        })

    _log.info(
        "Parsed %d column inventory edges from %s (vendor=%s)",
        len(edges), database_name or "unknown", warehouse_vendor,
    )
    return edges


# Known Fivetran/Airbyte replication prefixes
_SYSTEM_PREFIXES = {
    "salesforce": "salesforce",
    "sf": "salesforce",
    "netsuite": "netsuite",
    "ns": "netsuite",
    "hubspot": "hubspot",
    "hs": "hubspot",
    "stripe": "stripe",
    "zendesk": "zendesk",
    "jira": "jira",
    "servicenow": "servicenow",
    "sn": "servicenow",
    "workday": "workday",
    "wd": "workday",
    "sap": "sap",
    "okta": "okta",
    "google_analytics": "google_analytics",
    "ga": "google_analytics",
    "shopify": "shopify",
    "quickbooks": "quickbooks",
    "qb": "quickbooks",
    "xero": "xero",
    "bamboohr": "bamboohr",
    "asana": "asana",
    "github": "github",
    "gitlab": "gitlab",
    "intercom": "intercom",
    "marketo": "marketo",
    "pardot": "pardot",
}


def _infer_source_from_table(table_name: str, schema_name: str) -> tuple[str, str]:
    """
    Attempt to infer the source system and object from a warehouse table name.

    Conventions checked:
    1. Schema-level: schema='salesforce' → source_system='salesforce'
    2. Double-underscore prefix: 'salesforce__account' → ('salesforce', 'account')
    3. Single-underscore prefix: 'sf_account' → ('salesforce', 'account')
    4. Fallback: source_system = schema_name, object = table_name

    Returns (source_system, source_object)
    """
    # Check if schema itself is a known system
    schema_lower = schema_name.lower()
    if schema_lower in _SYSTEM_PREFIXES:
        return _SYSTEM_PREFIXES[schema_lower], table_name

    # Double-underscore convention (Fivetran standard)
    if "__" in table_name:
        prefix, remainder = table_name.split("__", 1)
        prefix_lower = prefix.lower()
        if prefix_lower in _SYSTEM_PREFIXES:
            return _SYSTEM_PREFIXES[prefix_lower], remainder
        return prefix_lower, remainder

    # Single-underscore prefix (check against known short prefixes)
    if "_" in table_name:
        prefix = table_name.split("_", 1)[0].lower()
        if prefix in _SYSTEM_PREFIXES:
            remainder = table_name.split("_", 1)[1]
            return _SYSTEM_PREFIXES[prefix], remainder

    # Fallback: use schema as source system
    return schema_lower, table_name
