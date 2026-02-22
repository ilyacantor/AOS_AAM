"""
Observation operations
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb
from ..logger import get_logger

_log = get_logger("db.observations")


def _safe_json(raw, default):
    """Parse JSON, returning default and logging if the stored value is corrupt."""
    if not raw:
        return default
    try:
        result = json.loads(raw)
        return result if result is not None else default
    except (json.JSONDecodeError, TypeError) as exc:
        _log.error("Corrupt JSON in observation row (returning default): %s — raw=%r", exc, raw[:100])
        return default


def create_observation(observation_data: dict) -> str:
    """Create a new observation"""
    observation_id = observation_data.get("observation_id", str(uuid.uuid4()))
    now = datetime.utcnow().isoformat()

    data = {
        "observation_id": observation_id,
        "collector_id": observation_data["collector_id"],
        "candidate_id": observation_data.get("candidate_id"),
        "observed_at": observation_data.get("observed_at", now),
        "source_system": observation_data["source_system"],
        "endpoint_info": json.dumps(observation_data["endpoint_info"]),
        "entity_hints": json.dumps(observation_data.get("entity_hints", [])),
        "schema_sample": json.dumps(observation_data.get("schema_sample")) if observation_data.get("schema_sample") else None,
        "metadata": json.dumps(observation_data.get("metadata", {})),
    }

    sb.insert("observations", data)

    return observation_id


def get_observations_for_candidate(candidate_id: str) -> list[dict]:
    """Get observations for a candidate"""
    rows = sb.select("observations", filters={"candidate_id": candidate_id}, order="observed_at.desc")
    return [_row_to_observation(row) for row in rows]


def get_unprocessed_observations() -> list[dict]:
    """Get observations that haven't been processed"""
    rows = sb.select("observations", raw_params={"processed": "eq.false"}, order="observed_at.asc")
    return [_row_to_observation(row) for row in rows]


def mark_observation_processed(observation_id: str):
    """Mark an observation as processed"""
    sb.update("observations", {"processed": True}, filters={"observation_id": observation_id})


def get_all_schema_samples() -> list[dict]:
    """Fetch all observations that have a schema_sample, returning only
    the fields needed for field resolution (candidate_id, source_system,
    schema_sample).  Single DB round-trip for the whole table.
    """
    rows = sb.select(
        "observations",
        columns="candidate_id,source_system,schema_sample",
        raw_params={"schema_sample": "not.is.null"},
    )
    results = []
    for row in rows:
        schema_raw = row.get("schema_sample")
        if not schema_raw:
            continue
        schema = _safe_json(schema_raw, None) if isinstance(schema_raw, str) else schema_raw
        if not isinstance(schema, dict) or not schema:
            continue
        results.append({
            "candidate_id": row.get("candidate_id"),
            "source_system": row.get("source_system"),
            "field_names": list(schema.keys()),
        })
    return results


def _row_to_observation(row) -> dict:
    """Convert database row to observation dict"""
    return {
        "observation_id": row.get("observation_id"),
        "collector_id": row.get("collector_id"),
        "candidate_id": row.get("candidate_id"),
        "observed_at": row.get("observed_at"),
        "source_system": row.get("source_system"),
        "endpoint_info": _safe_json(row.get("endpoint_info"), {}),
        "entity_hints": _safe_json(row.get("entity_hints"), []),
        "schema_sample": _safe_json(row.get("schema_sample"), None),
        "metadata": _safe_json(row.get("metadata"), {}),
        "processed": row.get("processed", False),
    }
