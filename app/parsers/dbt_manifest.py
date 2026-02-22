"""
dbt Manifest Parser — extracts field-level lineage edges from
dbt's manifest.json.

dbt models contain explicit source references:
    SELECT customer_name FROM {{ source('salesforce', 'account') }}

These give us the highest-quality warehouse lineage edges (0.95
confidence) because a human analyst explicitly defined the
source-to-model mapping.

Supports manifest.json v4-v11+ (dbt Core 1.0+).
"""
import logging
import uuid
from datetime import datetime
from typing import Optional

_log = logging.getLogger("aam.parser.dbt_manifest")


def parse_dbt_manifest(
    manifest: dict,
    *,
    warehouse_vendor: str = "snowflake",
) -> list[dict]:
    """
    Parse dbt manifest.json and extract field-level lineage as
    SemanticEdge dicts.

    The manifest contains:
    - 'sources': declared source tables ({{ source('schema', 'table') }})
    - 'nodes': models, seeds, snapshots with 'columns' and 'depends_on'

    For each model that depends on a source, we create edges mapping
    source columns to model columns (where names match or are explicitly
    mapped in the model's column meta).

    Args:
        manifest: Parsed manifest.json dict
        warehouse_vendor: Warehouse vendor for target_system

    Returns:
        List of SemanticEdge dicts
    """
    now = datetime.utcnow().isoformat()
    edges: list[dict] = []

    sources = manifest.get("sources") or {}
    nodes = manifest.get("nodes") or {}

    # Build a lookup: source_unique_id → source metadata
    source_lookup: dict[str, dict] = {}
    for source_id, source_def in sources.items():
        source_lookup[source_id] = {
            "source_name": source_def.get("source_name", ""),
            "table_name": source_def.get("name", ""),
            "schema": source_def.get("schema", ""),
            "database": source_def.get("database", ""),
            "columns": {
                col_name: col_def
                for col_name, col_def in (source_def.get("columns") or {}).items()
            },
        }

    # Process each model node
    for node_id, node_def in nodes.items():
        resource_type = node_def.get("resource_type", "")
        if resource_type not in ("model", "snapshot"):
            continue

        model_name = node_def.get("name", "unknown")
        model_schema = node_def.get("schema", "public")
        extraction_source = f"dbt_model_{model_name}"

        # Find which sources this model depends on
        depends_on = node_def.get("depends_on") or {}
        dep_nodes = depends_on.get("nodes") or []
        source_deps = [d for d in dep_nodes if d.startswith("source.")]

        if not source_deps:
            continue

        model_columns = node_def.get("columns") or {}

        for source_id in source_deps:
            source_info = source_lookup.get(source_id)
            if not source_info:
                _log.warning(
                    "dbt model '%s' depends on source '%s' which is not in the manifest — "
                    "lineage edges for this dependency will be missing.",
                    model_name, source_id,
                )
                continue

            source_system = source_info["source_name"].lower()
            source_table = source_info["table_name"]
            source_columns = source_info["columns"]

            # Strategy 1: Explicit column-level meta mapping
            # dbt columns can have meta.source_field pointing to the source column
            for col_name, col_def in model_columns.items():
                meta = col_def.get("meta") or {}
                source_field = meta.get("source_field") or meta.get("origin_field")

                if source_field:
                    # Explicit mapping via meta — highest confidence
                    edges.append(_make_edge(
                        source_system=source_system,
                        source_object=source_table,
                        source_field=source_field,
                        target_system=warehouse_vendor,
                        target_object=f"{model_schema}.{model_name}",
                        target_field=col_name,
                        edge_type="DIRECT_MAP",
                        confidence=0.95,
                        extraction_source=extraction_source,
                        transformation=meta.get("transformation"),
                        now=now,
                    ))
                elif col_name in source_columns:
                    # Column name exists in both source and model — likely pass-through
                    edges.append(_make_edge(
                        source_system=source_system,
                        source_object=source_table,
                        source_field=col_name,
                        target_system=warehouse_vendor,
                        target_object=f"{model_schema}.{model_name}",
                        target_field=col_name,
                        edge_type="DIRECT_MAP",
                        confidence=0.95,
                        extraction_source=extraction_source,
                        now=now,
                    ))

            # Strategy 2: Name-match fallback for source columns not yet covered
            covered_source_fields = {
                e["source_field"]
                for e in edges
                if e["extraction_source"] == extraction_source
                and e["source_system"] == source_system
                and e["source_object"] == source_table
            }

            for src_col_name in source_columns:
                if src_col_name in covered_source_fields:
                    continue
                # Check if a model column with the same name exists
                if src_col_name in model_columns:
                    edges.append(_make_edge(
                        source_system=source_system,
                        source_object=source_table,
                        source_field=src_col_name,
                        target_system=warehouse_vendor,
                        target_object=f"{model_schema}.{model_name}",
                        target_field=src_col_name,
                        edge_type="DIRECT_MAP",
                        confidence=0.95,
                        extraction_source=extraction_source,
                        now=now,
                    ))

    _log.info("Parsed %d lineage edges from dbt manifest (%d models, %d sources)",
              len(edges), len(nodes), len(sources))
    return edges


def _make_edge(
    *,
    source_system: str,
    source_object: str,
    source_field: str,
    target_system: str,
    target_object: str,
    target_field: str,
    edge_type: str,
    confidence: float,
    extraction_source: str,
    transformation: Optional[str] = None,
    condition: Optional[str] = None,
    now: Optional[str] = None,
) -> dict:
    now = now or datetime.utcnow().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "source_system": source_system,
        "source_object": source_object,
        "source_field": source_field,
        "target_system": target_system,
        "target_object": target_object,
        "target_field": target_field,
        "edge_type": edge_type,
        "confidence": confidence,
        "fabric_plane": "DATA_WAREHOUSE",
        "extraction_source": extraction_source,
        "transformation": transformation,
        "condition": condition,
        "discovered_at": now,
        "last_verified": now,
    }
