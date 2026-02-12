"""
Observation operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# OBSERVATION OPERATIONS
# ============================================================================

def create_observation(observation_data: dict) -> str:
    """Create a new observation"""
    conn = get_connection()
    cursor = conn.cursor()
    
    observation_id = observation_data.get("observation_id", str(uuid.uuid4()))
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO observations (
            observation_id, collector_id, candidate_id, observed_at,
            source_system, endpoint_info, entity_hints, schema_sample, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        observation_id,
        observation_data["collector_id"],
        observation_data.get("candidate_id"),
        observation_data.get("observed_at", now),
        observation_data["source_system"],
        json.dumps(observation_data["endpoint_info"]),
        json.dumps(observation_data.get("entity_hints", [])),
        json.dumps(observation_data.get("schema_sample")) if observation_data.get("schema_sample") else None,
        json.dumps(observation_data.get("metadata", {}))
    ))
    
    conn.commit()
    conn.close()
    
    return observation_id


def get_observations_for_candidate(candidate_id: str) -> list[dict]:
    """Get observations for a candidate"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM observations WHERE candidate_id = ? ORDER BY observed_at DESC",
        (candidate_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_observation(row) for row in rows]


def get_unprocessed_observations() -> list[dict]:
    """Get observations that haven't been processed"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM observations WHERE processed = 0 ORDER BY observed_at")
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_observation(row) for row in rows]


def mark_observation_processed(observation_id: str):
    """Mark an observation as processed"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE observations SET processed = 1 WHERE observation_id = ?", (observation_id,))
    conn.commit()
    conn.close()


def _row_to_observation(row) -> dict:
    """Convert database row to observation dict"""
    return {
        "observation_id": row["observation_id"],
        "collector_id": row["collector_id"],
        "candidate_id": row["candidate_id"],
        "observed_at": row["observed_at"],
        "source_system": row["source_system"],
        "endpoint_info": json.loads(row["endpoint_info"]),
        "entity_hints": json.loads(row["entity_hints"]) if row["entity_hints"] else [],
        "schema_sample": json.loads(row["schema_sample"]) if row["schema_sample"] else None,
        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        "processed": bool(row["processed"])
    }


