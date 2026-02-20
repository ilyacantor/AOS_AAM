"""
Event Bus Schema Registry Parser — extracts field definitions from
Kafka/Confluent Schema Registry subjects.

Schema registries contain Avro, JSON Schema, or Protobuf definitions
for event topics. We parse these for field names, types, and nested
structures, then map producer → topic → consumer to establish data
flow direction.

Edge confidence: 0.80 for schema registry fields (we know the structure
but cross-system mapping requires producer/consumer context).
"""
import logging
import uuid
from datetime import datetime
from typing import Optional

_log = logging.getLogger("aam.parser.eventbus_schema")


def parse_schema_registry_subjects(
    subjects: list[dict],
    *,
    bus_vendor: str = "kafka",
) -> list[dict]:
    """
    Parse schema registry subject definitions into SemanticEdge dicts.

    Each subject represents a topic schema. Fields in the schema become
    edges where:
    - source = the producing system (inferred from topic name or
      explicit producer metadata)
    - target = the event bus topic

    Args:
        subjects: List of subject dicts, each with:
            - subject: topic/subject name (e.g., 'salesforce.opportunity.created')
            - schema_type: 'AVRO' | 'JSON' | 'PROTOBUF'
            - schema: the parsed schema (dict for Avro/JSON, string for Protobuf)
            - producer: optional producing system name
            - consumer: optional consuming system name
        bus_vendor: 'kafka', 'confluent', 'eventbridge', etc.

    Returns:
        List of SemanticEdge dicts
    """
    now = datetime.utcnow().isoformat()
    edges: list[dict] = []

    for subject in subjects:
        subject_name = subject.get("subject", "unknown")
        schema_type = (subject.get("schema_type") or "AVRO").upper()
        schema = subject.get("schema") or {}
        producer = subject.get("producer")
        consumer = subject.get("consumer")

        extraction_source = f"schema_registry_{bus_vendor}_{subject_name}"

        # Infer producer system from topic name if not explicit
        source_system = producer or _infer_system_from_topic(subject_name)
        target_system = consumer or bus_vendor

        if schema_type in ("AVRO", "JSON"):
            fields = _extract_fields_from_avro_or_json(schema)
        elif schema_type == "PROTOBUF":
            fields = _extract_fields_from_protobuf(schema)
        else:
            _log.warning("Unknown schema type %s for subject %s", schema_type, subject_name)
            continue

        # Determine the object name from schema or topic
        object_name = schema.get("name") or subject_name

        for field_name, field_type in fields:
            edges.append({
                "id": str(uuid.uuid4()),
                "source_system": source_system,
                "source_object": object_name,
                "source_field": field_name,
                "target_system": target_system,
                "target_object": subject_name,
                "target_field": field_name,
                "edge_type": "INFERRED",
                "confidence": 0.80,
                "fabric_plane": "EVENT_BUS",
                "extraction_source": extraction_source,
                "transformation": None,
                "condition": None,
                "discovered_at": now,
                "last_verified": now,
            })

    _log.info(
        "Parsed %d field edges from %d schema registry subjects (vendor=%s)",
        len(edges), len(subjects), bus_vendor,
    )
    return edges


def _extract_fields_from_avro_or_json(schema: dict) -> list[tuple[str, str]]:
    """
    Extract (field_name, field_type) pairs from an Avro or JSON schema.

    Avro record schema:
        {"type": "record", "name": "Opportunity", "fields": [
            {"name": "id", "type": "string"},
            {"name": "amount", "type": ["null", "double"]},
        ]}

    JSON Schema:
        {"type": "object", "properties": {
            "id": {"type": "string"},
            "amount": {"type": "number"},
        }}
    """
    fields: list[tuple[str, str]] = []

    # Avro record format
    if schema.get("type") == "record" and "fields" in schema:
        for field in schema["fields"]:
            name = field.get("name", "")
            ftype = field.get("type", "unknown")
            if isinstance(ftype, list):
                # Union type — pick first non-null
                ftype = next((t for t in ftype if t != "null"), ftype[0])
            if isinstance(ftype, dict):
                ftype = ftype.get("type", "complex")
            if name:
                fields.append((name, str(ftype)))

    # JSON Schema format
    elif schema.get("type") == "object" and "properties" in schema:
        for name, prop in schema["properties"].items():
            ftype = prop.get("type", "unknown")
            if isinstance(ftype, list):
                ftype = next((t for t in ftype if t != "null"), ftype[0])
            fields.append((name, str(ftype)))

    return fields


def _extract_fields_from_protobuf(schema) -> list[tuple[str, str]]:
    """
    Best-effort field extraction from Protobuf schema definition.

    If schema is a string (raw .proto), do basic regex parsing.
    If schema is a dict (parsed descriptor), extract from 'fields'.
    """
    fields: list[tuple[str, str]] = []

    if isinstance(schema, dict) and "fields" in schema:
        for field in schema["fields"]:
            name = field.get("name", "")
            ftype = field.get("type", "unknown")
            if name:
                fields.append((name, str(ftype)))
    elif isinstance(schema, str):
        # Basic regex: capture "type name = N;"
        import re
        for match in re.finditer(r'(\w+)\s+(\w+)\s*=\s*\d+\s*;', schema):
            ftype, name = match.group(1), match.group(2)
            fields.append((name, ftype))

    return fields


# Known system name patterns in Kafka topic names
_TOPIC_SYSTEM_PATTERNS = {
    "salesforce": "salesforce",
    "sf": "salesforce",
    "netsuite": "netsuite",
    "ns": "netsuite",
    "hubspot": "hubspot",
    "stripe": "stripe",
    "zendesk": "zendesk",
    "jira": "jira",
    "servicenow": "servicenow",
    "sap": "sap",
    "okta": "okta",
    "shopify": "shopify",
    "workday": "workday",
}


def _infer_system_from_topic(topic_name: str) -> str:
    """
    Infer the producing system from a topic name.

    Common patterns:
    - 'salesforce.opportunity.created'
    - 'sf-opportunity-events'
    - 'cdc.netsuite.sales_order'
    """
    topic_lower = topic_name.lower()

    # Check for exact prefix match before any separator
    for sep in (".", "-", "_"):
        if sep in topic_lower:
            prefix = topic_lower.split(sep)[0]
            # Handle 'cdc' or 'events' prefixes
            if prefix in ("cdc", "events", "raw", "staging"):
                parts = topic_lower.split(sep)
                if len(parts) > 1:
                    prefix = parts[1]
            if prefix in _TOPIC_SYSTEM_PATTERNS:
                return _TOPIC_SYSTEM_PATTERNS[prefix]

    # Substring match as fallback
    for pattern, system in _TOPIC_SYSTEM_PATTERNS.items():
        if pattern in topic_lower:
            return system

    return "unknown"
