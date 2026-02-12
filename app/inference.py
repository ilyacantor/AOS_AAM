"""
AAM Inference Engine

Converts observations from collectors into DeclaredPipes by inferring:
- Entity scope
- Identity keys
- Change semantics
- Provenance
- Ownership signals

The inference engine uses heuristics and patterns to make educated guesses.
Unknown or weak signals become trust_labels, not blockers.
"""
import hashlib
import json
from datetime import datetime
from typing import Optional
import uuid

from .db import (
    get_unprocessed_observations,
    mark_observation_processed,
    create_pipe,
    get_pipe,
    list_pipes
)


def compute_schema_hash(schema: dict) -> str:
    """
    Compute a deterministic hash of a schema.
    Normalizes the schema by sorting keys to ensure consistent hashes.
    """
    if not schema:
        return ""
    
    # Sort keys recursively for deterministic serialization
    normalized = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def infer_pipes_from_observations(observations: list[dict]) -> list[dict]:
    """
    Main inference function.
    Takes a list of observations and produces DeclaredPipes.
    """
    pipes = []
    
    for obs in observations:
        pipe = infer_single_pipe(obs)
        if pipe:
            # Check if a similar pipe already exists
            existing = find_existing_pipe(pipe)
            if existing:
                pipe["pipe_id"] = existing["pipe_id"]
                pipe["_action"] = "update"
            else:
                pipe["_action"] = "create"
            pipes.append(pipe)
    
    return pipes


def infer_single_pipe(observation: dict) -> Optional[dict]:
    """
    Infer a DeclaredPipe from a single observation.
    """
    source_system = observation.get("source_system", "unknown")
    endpoint_info = observation.get("endpoint_info", {})
    entity_hints = observation.get("entity_hints", [])
    schema_sample = observation.get("schema_sample")
    metadata = observation.get("metadata", {})
    
    # Infer fabric plane
    fabric_plane = infer_fabric_plane(endpoint_info, metadata)
    
    # Infer modality
    modality = infer_modality(endpoint_info, metadata)
    
    # Infer transport kind
    transport_kind = infer_transport_kind(endpoint_info)
    
    # Infer entity scope from hints and endpoint
    entity_scope = infer_entity_scope(entity_hints, endpoint_info)
    
    # Infer identity keys from schema
    identity_keys = infer_identity_keys(schema_sample, entity_scope)
    
    # Infer change semantics
    change_semantics = infer_change_semantics(endpoint_info, schema_sample)
    
    # Build provenance
    provenance = {
        "discovered_by": observation.get("collector_id", "unknown"),
        "discovered_at": observation.get("observed_at", datetime.utcnow().isoformat()),
        "lineage_hints": build_lineage_hints(observation)
    }
    
    # Infer ownership signals
    owner_signals = infer_ownership_signals(metadata, source_system)
    
    # Build trust labels from weak signals
    trust_labels = build_trust_labels(observation, modality, change_semantics)
    
    # Build schema info if available
    schema_info = None
    if schema_sample:
        schema_hash = compute_schema_hash(schema_sample)
        schema_info = {
            "schema_hash": schema_hash,
            "schema_ref": None,
            "schema_version": "inferred"
        }
    
    # Build display name
    display_name = build_display_name(source_system, entity_scope, endpoint_info)
    
    return {
        "pipe_id": str(uuid.uuid4()),
        "display_name": display_name,
        "fabric_plane": fabric_plane,
        "modality": modality,
        "source_system": source_system,
        "transport_kind": transport_kind,
        "endpoint_ref": endpoint_info,
        "entity_scope": entity_scope,
        "identity_keys": identity_keys,
        "change_semantics": change_semantics,
        "provenance": provenance,
        "owner_signals": owner_signals,
        "trust_labels": trust_labels,
        "schema_info": schema_info,
        "freshness": None,
        "access": None
    }


def infer_fabric_plane(endpoint_info: dict, metadata: dict) -> str:
    """Infer the integration fabric control plane.

    RULES:
    - If metadata already carries an explicit fabric_plane, trust it.
    - Infrastructure vendor identity is valid evidence (Kafka IS an event bus).
    - URL patterns for infrastructure products are valid evidence.
    - Application categories (CRM, ERP, ITSM …) are NOT valid evidence.
      A CRM could route through any of the four planes depending on how
      the enterprise wired its integrations.
    - When nothing matches, return None (unknown) instead of guessing.
    """
    from .constants import INFRA_VENDOR_PLANE

    url = endpoint_info.get("url", "").lower()
    vendor = metadata.get("vendor", "").lower()
    fabric = metadata.get("fabric_plane", "").upper()

    if fabric in ["IPAAS", "API_GATEWAY", "EVENT_BUS", "DATA_WAREHOUSE"]:
        return fabric

    for infra_vendor, plane in INFRA_VENDOR_PLANE.items():
        if infra_vendor in vendor:
            return plane

    if any(x in url for x in ["kafka", "pubsub", "queue", "stream", "sns", "sqs"]):
        return "EVENT_BUS"
    if any(x in url for x in ["warehouse", "bigquery", "snowflake", "redshift", "databricks", "synapse"]):
        return "DATA_WAREHOUSE"

    return "UNKNOWN"


def infer_modality(endpoint_info: dict, metadata: dict) -> str:
    """Infer the modality based on endpoint and metadata"""
    url = endpoint_info.get("url", "").lower()
    vendor = metadata.get("vendor", "").lower()
    category = metadata.get("category", "").lower()
    
    # Control plane indicators
    if any(x in url for x in ["admin", "management", "config", "settings"]):
        return "CONTROL_PLANE"
    
    # iPaaS typically uses control plane
    if category == "ipaas" or vendor in ["workato", "mulesoft", "boomi"]:
        return "CONTROL_PLANE"
    
    # API endpoints are declared interfaces
    if any(x in url for x in ["api", "rest", "services", "sobjects"]):
        return "DECLARED_INTERFACE"
    
    # Event/webhook patterns
    if any(x in url for x in ["events", "webhook", "stream", "subscribe"]):
        return "PASSIVE_SUBSCRIPTION"
    
    return "DECLARED_INTERFACE"


def infer_transport_kind(endpoint_info: dict) -> str:
    """Infer transport kind from endpoint info"""
    url = endpoint_info.get("url", "").lower()
    method = endpoint_info.get("method", "GET").upper()
    
    if any(x in url for x in ["webhook", "callback", "hook"]):
        return "WEBHOOK"
    
    if any(x in url for x in ["event", "stream", "subscribe", "queue"]):
        return "EVENT_STREAM"
    
    if any(x in url for x in ["table", "query", "sql", "database"]):
        return "TABLE"
    
    if any(x in url for x in ["file", "download", "export", "csv", "xlsx"]):
        return "FILE"
    
    return "API"


def infer_entity_scope(entity_hints: list[str], endpoint_info: dict) -> list[str]:
    """Infer entity scope from hints and endpoint"""
    scope = list(entity_hints) if entity_hints else []
    
    # Extract entities from URL path
    url = endpoint_info.get("url", "")
    parts = url.split("/")
    
    for part in parts:
        if part and len(part) > 2:
            # Skip common path segments
            if part.lower() not in ["api", "v1", "v2", "v3", "data", "services", "sobjects", "rest"]:
                # Skip numeric IDs
                if not part.isdigit() and not part.startswith("{"):
                    entity = part.replace("_", " ").replace("-", " ").title()
                    if entity not in scope:
                        scope.append(entity)
    
    return scope[:5]  # Limit to 5 entities


def infer_identity_keys(schema: Optional[dict], entity_scope: list[str]) -> list[str]:
    """Infer identity keys from schema fields with deep analysis"""
    if not schema:
        return ["id"]

    keys = []
    key_scores = {}  # Track confidence scores for each potential key

    # Common identity field patterns with priority scores
    primary_id_patterns = ["id", "uuid", "guid", "key", "_id", "identifier", "pk"]
    secondary_id_patterns = ["code", "number", "ref", "reference", "external_id"]

    for field_name in schema.keys():
        lower_name = field_name.lower()
        score = 0

        # Primary ID fields (highest priority)
        if lower_name in primary_id_patterns:
            score = 100
        elif lower_name.endswith("_id") or lower_name.endswith("id"):
            score = 90
        elif lower_name.endswith("_uuid") or lower_name.endswith("_guid"):
            score = 95
        elif lower_name.startswith("pk_") or lower_name == "primary_key":
            score = 95

        # Secondary ID patterns
        elif any(p in lower_name for p in secondary_id_patterns):
            score = 70

        # Entity-specific IDs (e.g., account_id for Account entity)
        for entity in entity_scope:
            entity_lower = entity.lower().replace(" ", "_")
            if entity_lower in lower_name and ("id" in lower_name or "key" in lower_name):
                score = max(score, 85)

        # Composite key detection (multiple fields that together form identity)
        if lower_name in ["tenant_id", "org_id", "organization_id", "company_id"]:
            score = max(score, 80)  # These are often part of composite keys

        # Check field value type hints if available
        field_value = schema.get(field_name)
        if isinstance(field_value, str):
            # UUID pattern detection
            if len(field_value) == 36 and field_value.count("-") == 4:
                score = max(score, 92)
            # Numeric ID detection
            elif field_value.isdigit():
                score = max(score, 75)

        if score > 0:
            key_scores[field_name] = score

    # Sort by score and take top keys
    sorted_keys = sorted(key_scores.items(), key=lambda x: x[1], reverse=True)
    keys = [k for k, _ in sorted_keys[:3]]

    # Ensure we have at least one key
    if not keys:
        # Check common capitalization variants
        for variant in ["Id", "id", "ID", "_id", "uuid", "UUID"]:
            if variant in schema:
                keys.append(variant)
                break
        if not keys:
            keys.append("id")  # Default assumption

    return keys


def infer_change_semantics(endpoint_info: dict, schema: Optional[dict]) -> str:
    """Infer how data changes over time"""
    url = endpoint_info.get("url", "").lower()
    method = endpoint_info.get("method", "GET").upper()

    # CDC indicators in URL
    if any(x in url for x in ["cdc", "changes", "delta", "incremental", "replication"]):
        return "CDC_UPSERT"

    # Append-only indicators (events, logs, activities)
    if any(x in url for x in ["events", "log", "audit", "history", "activities", "feed", "stream"]):
        return "APPEND_ONLY"

    # Snapshot indicators
    if any(x in url for x in ["snapshot", "full", "dump", "export", "bulk", "all"]):
        return "SNAPSHOT"

    # Check schema for timestamp fields that suggest CDC
    if schema:
        schema_keys_lower = [k.lower() for k in schema.keys()]

        # Strong CDC indicators: both created and modified timestamps
        has_modified = any(
            "modified" in k or "updated" in k or "changed" in k or "last_" in k
            for k in schema_keys_lower
        )
        has_created = any(
            "created" in k or "inserted" in k or "added" in k
            for k in schema_keys_lower
        )

        # Check for version/revision fields (strong CDC indicator)
        has_version = any(
            "version" in k or "revision" in k or "etag" in k or "seq" in k
            for k in schema_keys_lower
        )

        # Check for soft delete indicators
        has_deleted = any(
            "deleted" in k or "is_active" in k or "status" in k
            for k in schema_keys_lower
        )

        if has_modified and has_created:
            return "CDC_UPSERT"
        if has_version:
            return "CDC_UPSERT"
        if has_deleted and has_modified:
            return "CDC_UPSERT"
        if has_created and not has_modified:
            return "APPEND_ONLY"

        # Check for immutable record patterns (IDs only, no timestamps)
        id_only = all(
            "id" in k or "_id" in k or "key" in k or "uuid" in k
            for k in schema_keys_lower if k not in ["created", "modified", "updated"]
        )
        if id_only and len(schema_keys_lower) <= 3:
            return "SNAPSHOT"

    # POST methods often indicate append-only patterns
    if method == "POST" and any(x in url for x in ["create", "insert", "add"]):
        return "APPEND_ONLY"

    return "UNKNOWN"


def build_lineage_hints(observation: dict) -> list[str]:
    """Build lineage hints from observation metadata"""
    hints = []
    
    metadata = observation.get("metadata", {})
    endpoint_info = observation.get("endpoint_info", {})
    
    if metadata.get("vendor"):
        hints.append(f"vendor:{metadata['vendor']}")
    
    if metadata.get("category"):
        hints.append(f"category:{metadata['category']}")
    
    if endpoint_info.get("discovered_via"):
        hints.append(f"discovered_via:{endpoint_info['discovered_via']}")
    
    if observation.get("candidate_id"):
        hints.append(f"candidate:{observation['candidate_id'][:8]}")
    
    return hints


def infer_ownership_signals(metadata: dict, source_system: str) -> list[str]:
    """Infer ownership signals from metadata"""
    signals = []
    
    if source_system:
        signals.append(f"system:{source_system}")
    
    if metadata.get("vendor"):
        signals.append(f"vendor:{metadata['vendor']}")
    
    # Add any owner/team hints from metadata
    for key in ["owner", "team", "department", "group"]:
        if key in metadata:
            signals.append(f"{key}:{metadata[key]}")
    
    return signals


def build_trust_labels(observation: dict, modality: str, change_semantics: str) -> list[str]:
    """
    Build trust labels from weak or uncertain signals.
    Unknown or weak signals become labels, not blockers.

    Trust label categories:
    - verified_*: Confirmed through external validation
    - inferred_*: Derived through heuristics
    - warning_*: Potential issues detected
    - quality_*: Data quality indicators
    - source_*: Origin information
    """
    labels = []
    metadata = observation.get("metadata", {})
    schema_sample = observation.get("schema_sample")
    endpoint_info = observation.get("endpoint_info", {})

    # === SCHEMA STABILITY ===
    if schema_sample:
        labels.append("inferred:schema_from_sample")
        # Check schema completeness
        if len(schema_sample.keys()) >= 5:
            labels.append("quality:schema_complete")
        elif len(schema_sample.keys()) >= 2:
            labels.append("quality:schema_partial")

        # Check for well-structured schema (has types, descriptions)
        has_types = any(
            isinstance(v, dict) and "type" in v
            for v in schema_sample.values()
        )
        if has_types:
            labels.append("quality:schema_typed")
            labels.append("schema_stable")  # Typed schemas are more stable
    else:
        labels.append("warning:no_schema_available")

    # === CHANGE SEMANTICS CONFIDENCE ===
    if change_semantics == "UNKNOWN":
        labels.append("inferred:change_semantics_unknown")
        labels.append("warning:semantics_needs_review")
    elif change_semantics == "CDC_UPSERT":
        labels.append("quality:supports_incremental")
    elif change_semantics == "APPEND_ONLY":
        labels.append("quality:event_sourced")

    # === MODALITY CONFIDENCE ===
    labels.append(f"inferred:modality_{modality.lower()}")

    # === OWNERSHIP VERIFICATION ===
    owner_info = metadata.get("owner") or metadata.get("team") or metadata.get("department")
    if owner_info:
        labels.append("verified_owner")
    else:
        labels.append("warning:owner_unknown")

    # === TRAFFIC/USAGE INDICATORS ===
    # Check for high-traffic indicators in metadata
    usage_hints = metadata.get("usage", {})
    if isinstance(usage_hints, dict):
        requests_per_day = usage_hints.get("requests_per_day", 0)
        if requests_per_day > 10000:
            labels.append("high_traffic")
        elif requests_per_day > 1000:
            labels.append("medium_traffic")

    # Check endpoint hints for traffic patterns
    url = endpoint_info.get("url", "").lower()
    if any(x in url for x in ["bulk", "batch", "stream", "firehose"]):
        labels.append("high_traffic")

    # === SOURCE/COLLECTOR INFO ===
    collector_id = observation.get("collector_id", "")
    if collector_id == "mock-collector-001":
        labels.append("source:mock_collector")
    elif "adapter" in collector_id:
        labels.append("source:fabric_adapter")
        labels.append("verified_connection")  # Adapter-discovered means verified connection
    else:
        labels.append(f"source:{collector_id.split('-')[0] if collector_id else 'unknown'}")

    # === GOVERNANCE INDICATORS ===
    if metadata.get("pii_redacted"):
        labels.append("governance:pii_redacted")
    if metadata.get("governance_applied"):
        labels.append("governance:policies_applied")

    # === FRESHNESS INDICATORS ===
    if endpoint_info.get("cache_control") or endpoint_info.get("etag"):
        labels.append("quality:cacheable")
    if any(x in url for x in ["realtime", "live", "stream"]):
        labels.append("quality:realtime")

    return labels


def build_display_name(source_system: str, entity_scope: list[str], endpoint_info: dict) -> str:
    """Build a human-readable display name for the pipe"""
    if entity_scope:
        primary_entity = entity_scope[0]
        return f"{source_system} - {primary_entity}"
    
    url = endpoint_info.get("url", "")
    if url:
        # Extract last meaningful path segment
        parts = [p for p in url.split("/") if p and not p.startswith("{")]
        if parts:
            return f"{source_system} - {parts[-1].title()}"
    
    return f"{source_system} - Data Pipe"


def find_existing_pipe(pipe: dict) -> Optional[dict]:
    """
    Find an existing pipe that matches the new pipe.
    Match by source_system + endpoint_ref combination.
    """
    existing_pipes = list_pipes(source_system=pipe["source_system"])
    
    for existing in existing_pipes:
        # Match by endpoint URL
        if (existing.get("endpoint_ref", {}).get("url") == 
            pipe.get("endpoint_ref", {}).get("url")):
            return existing
    
    return None


def process_pending_observations() -> dict:
    """
    Process all pending observations and create/update pipes.
    Returns summary of processing.
    """
    observations = get_unprocessed_observations()
    
    if not observations:
        return {"processed": 0, "pipes_created": 0, "pipes_updated": 0}
    
    pipes = infer_pipes_from_observations(observations)
    
    created = 0
    updated = 0
    
    for pipe in pipes:
        action = pipe.pop("_action", "create")
        
        if action == "create":
            create_pipe(pipe)
            created += 1
        else:
            # For updates, we'd use update_pipe_with_version
            # For MVP-0, we'll just create new pipes
            create_pipe(pipe)
            created += 1
    
    # Mark observations as processed
    for obs in observations:
        mark_observation_processed(obs["observation_id"])
    
    return {
        "processed": len(observations),
        "pipes_created": created,
        "pipes_updated": updated
    }
