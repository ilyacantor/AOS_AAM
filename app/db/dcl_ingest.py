"""
DCL Ingested — stores payloads pushed by Runners into the DCL ingestion endpoint.

Mirrors dcl_pushes (outbound) but for inbound data from the Runner pipeline.
"""
import json
import hashlib
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def compute_schema_hash(data: list[dict]) -> str:
    """Compute SHA-256 hash of the data structure (sorted field names + types).

    This is the x-schema-hash used for schema drift detection.
    """
    if not data:
        return hashlib.sha256(b"empty").hexdigest()[:16]
    # Use first record as representative structure
    sample = data[0]
    structure = sorted(f"{k}:{type(v).__name__}" for k, v in sample.items())
    raw = "|".join(structure)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def store_ingest(
    run_id: str,
    pipe_id: str,
    source_system: str,
    data: list[dict],
    schema_version: Optional[str] = None,
    schema_hash: Optional[str] = None,
) -> dict:
    """Store an ingested payload. Returns the ingest record (without full payload)."""
    ingest_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    payload_json = json.dumps(data, default=str, sort_keys=True)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()[:16]

    if schema_hash is None:
        schema_hash = compute_schema_hash(data)

    sb.insert("dcl_ingested", {
        "ingest_id": ingest_id,
        "run_id": run_id,
        "pipe_id": pipe_id,
        "source_system": source_system,
        "row_count": len(data),
        "payload_hash": payload_hash,
        "schema_hash": schema_hash,
        "payload": payload_json,
        "ingested_at": now,
        "schema_version": schema_version,
    })

    return {
        "ingest_id": ingest_id,
        "run_id": run_id,
        "pipe_id": pipe_id,
        "row_count": len(data),
        "payload_hash": payload_hash,
        "schema_hash": schema_hash,
        "ingested_at": now,
    }


def get_previous_schema_hash(pipe_id: str) -> Optional[str]:
    """Get the schema_hash from the most recent ingest for this pipe.

    Used to detect schema drift between consecutive runs.
    """
    rows = sb.select(
        "dcl_ingested",
        columns="schema_hash",
        filters={"pipe_id": pipe_id},
        order="ingested_at.desc",
        limit=1,
    )
    if rows:
        return rows[0].get("schema_hash")
    return None


def list_ingests(
    pipe_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List ingested payloads (without full payload body)."""
    filters = {}
    if pipe_id:
        filters["pipe_id"] = pipe_id
    if run_id:
        filters["run_id"] = run_id

    kwargs: dict = {"order": "ingested_at.desc", "limit": limit}
    if filters:
        kwargs["filters"] = filters

    return sb.select(
        "dcl_ingested",
        columns="ingest_id,run_id,pipe_id,source_system,row_count,payload_hash,schema_hash,ingested_at,schema_version",
        **kwargs,
    )


def get_ingest(ingest_id: str) -> Optional[dict]:
    """Get a specific ingest including full payload."""
    row = sb.select("dcl_ingested", filters={"ingest_id": ingest_id}, single=True)
    if not row:
        return None
    if row.get("payload") and isinstance(row["payload"], str):
        row["payload"] = json.loads(row["payload"])
    return row
