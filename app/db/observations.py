"""
Observation operations
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


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


def _row_to_observation(row) -> dict:
    """Convert database row to observation dict"""
    return {
        "observation_id": row.get("observation_id"),
        "collector_id": row.get("collector_id"),
        "candidate_id": row.get("candidate_id"),
        "observed_at": row.get("observed_at"),
        "source_system": row.get("source_system"),
        "endpoint_info": json.loads(row["endpoint_info"]) if row.get("endpoint_info") else {},
        "entity_hints": json.loads(row["entity_hints"]) if row.get("entity_hints") else [],
        "schema_sample": json.loads(row["schema_sample"]) if row.get("schema_sample") else None,
        "metadata": json.loads(row["metadata"]) if row.get("metadata") else {},
        "processed": row.get("processed", False),
    }
