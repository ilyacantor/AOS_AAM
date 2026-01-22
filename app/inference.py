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
    """Infer identity keys from schema fields"""
    if not schema:
        return ["id"]
    
    keys = []
    
    # Common identity field patterns
    id_patterns = ["id", "uuid", "key", "_id", "identifier"]
    
    for field_name in schema.keys():
        lower_name = field_name.lower()
        
        # Direct ID fields
        if lower_name in id_patterns or lower_name.endswith("_id") or lower_name.endswith("id"):
            if lower_name not in keys:
                keys.append(field_name)
        
        # Entity-specific IDs (e.g., account_id for Account entity)
        for entity in entity_scope:
            if entity.lower() in lower_name and "id" in lower_name:
                if field_name not in keys:
                    keys.append(field_name)
    
    # Ensure we have at least one key
    if not keys and "Id" in schema:
        keys.append("Id")
    elif not keys and "id" in schema:
        keys.append("id")
    elif not keys:
        keys.append("id")  # Default assumption
    
    return keys[:3]  # Limit to 3 identity keys


def infer_change_semantics(endpoint_info: dict, schema: Optional[dict]) -> str:
    """Infer how data changes over time"""
    url = endpoint_info.get("url", "").lower()
    method = endpoint_info.get("method", "GET").upper()
    
    # CDC indicators
    if any(x in url for x in ["cdc", "changes", "delta", "incremental"]):
        return "CDC_UPSERT"
    
    # Append-only indicators (events, logs)
    if any(x in url for x in ["events", "log", "audit", "history"]):
        return "APPEND_ONLY"
    
    # Snapshot indicators
    if any(x in url for x in ["snapshot", "full", "dump", "export"]):
        return "SNAPSHOT"
    
    # Check schema for timestamp fields that suggest CDC
    if schema:
        has_modified = any(
            "modified" in k.lower() or "updated" in k.lower()
            for k in schema.keys()
        )
        has_created = any("created" in k.lower() for k in schema.keys())
        
        if has_modified and has_created:
            return "CDC_UPSERT"
        elif has_created:
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
    """
    labels = []
    
    # If we couldn't determine change semantics
    if change_semantics == "UNKNOWN":
        labels.append("inferred:change_semantics_unknown")
    
    # If schema was inferred
    if observation.get("schema_sample"):
        labels.append("inferred:schema_from_sample")
    else:
        labels.append("warning:no_schema_available")
    
    # If modality was inferred from heuristics
    labels.append(f"inferred:modality_{modality.lower()}")
    
    # Mark as mock-generated if from mock collector
    if observation.get("collector_id") == "mock-collector-001":
        labels.append("source:mock_collector")
    
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
