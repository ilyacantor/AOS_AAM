"""
Inline v1 Runner Execution — executes a job manifest in-process.

In production (v2+), this becomes a Docker container / serverless function.
For v1, we simulate the Runner lifecycle in an async task:
  1. Accept manifest
  2. Mark job "running"
  3. (Simulated) Connect to source, extract data
  4. Push to POST /api/dcl/ingest
  5. Mark job "completed" via callback

Data bytes flow: Source → Runner → DCL.  AAM never sees the payload.
"""
import asyncio
import json
import hashlib
from datetime import datetime
from typing import Optional

from ..logger import get_logger
from ..db.runner_jobs import update_runner_status, get_runner_job
from ..db.dcl_ingest import store_ingest, compute_schema_hash, get_previous_schema_hash
from ..db import create_drift_event

_log = get_logger("services.runner_execute")


async def execute_job_inline(job_id: str) -> dict:
    """Execute a runner job inline (v1 in-process worker).

    This simulates the full Runner lifecycle:
    - Reads the manifest from the job record
    - Marks status transitions (running → pushing → completed)
    - Generates simulated data (in v2, this fetches from the real source)
    - Stores in DCL via the same store_ingest path
    - Detects schema drift

    Returns a result dict with execution summary.
    """
    job = get_runner_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    manifest = job.get("manifest", {})
    source = manifest.get("source", {})
    target = manifest.get("target", {})
    pipe_id = source.get("pipe_id", "unknown")
    system = source.get("system", "unknown")

    # --- Step 1: Mark running ---
    update_runner_status(job_id, "running")
    _log.info("Runner started job %s (pipe=%s, system=%s)", job_id, pipe_id, system)

    try:
        # --- Step 2: Extract data (v1 = simulated) ---
        # In production, the Runner would:
        #   - Resolve credentials from vault
        #   - Connect to source using adapter type
        #   - Execute query from manifest
        #   - Stream results
        simulated_data = _generate_simulated_data(source)

        # --- Step 3: Apply transform (schema normalization) ---
        transform = manifest.get("transform")
        if transform and transform.get("schema_map"):
            simulated_data = _apply_schema_map(simulated_data, transform["schema_map"])

        # --- Step 4: Compute schema hash (Refinement C) ---
        schema_hash = compute_schema_hash(simulated_data)

        # Schema drift detection
        drift_detected = False
        previous_hash = get_previous_schema_hash(pipe_id)
        if previous_hash and previous_hash != schema_hash:
            drift_detected = True
            _log.warning("Schema drift: pipe %s hash %s → %s", pipe_id, previous_hash, schema_hash)
            try:
                create_drift_event({
                    "pipe_id": pipe_id,
                    "drift_type": "schema",
                    "old_value": previous_hash,
                    "new_value": schema_hash,
                })
            except Exception:
                pass

        # --- Step 5: Push to DCL (store_ingest) ---
        update_runner_status(job_id, "pushing")

        record = store_ingest(
            run_id=job_id,
            pipe_id=pipe_id,
            source_system=system,
            data=simulated_data,
            schema_hash=schema_hash,
        )

        # --- Step 6: Mark completed ---
        update_runner_status(
            job_id,
            "completed",
            rows_transferred=record["row_count"],
            dcl_response=record,
        )

        _log.info(
            "Runner completed job %s: %d rows, hash=%s, drift=%s",
            job_id, record["row_count"], schema_hash, drift_detected,
        )

        return {
            "job_id": job_id,
            "status": "completed",
            "rows_transferred": record["row_count"],
            "ingest_id": record["ingest_id"],
            "schema_hash": schema_hash,
            "schema_drift_detected": drift_detected,
        }

    except Exception as exc:
        _log.error("Runner failed job %s: %s", job_id, exc)
        update_runner_status(job_id, "failed", error_message=str(exc))
        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(exc),
        }


def _generate_simulated_data(source: dict) -> list[dict]:
    """Generate simulated extraction data for v1 testing.

    In production, this is replaced by actual source connection + query.
    """
    system = source.get("system", "unknown").lower()
    now = datetime.utcnow().isoformat()

    # Generate 5 representative rows based on source system type
    return [
        {
            "entity_id": f"{system}_entity_{i:03d}",
            "metric_value": (i + 1) * 10000,
            "dimension_source": system,
            "dimension_category": "simulated",
            "extracted_at": now,
        }
        for i in range(5)
    ]


def _apply_schema_map(data: list[dict], schema_map: dict) -> list[dict]:
    """Apply transform.schema_map to rename/convert fields.

    schema_map format: { "SourceField": { "target": "dcl_field", "unit": "USD", ... } }
    """
    if not schema_map or not data:
        return data

    mapped = []
    for row in data:
        new_row = {}
        for key, value in row.items():
            if key in schema_map:
                mapping = schema_map[key]
                target_name = mapping.get("target", key)
                # Apply scale if specified
                if "scale" in mapping and isinstance(value, (int, float)):
                    value = value * mapping["scale"]
                new_row[target_name] = value
            else:
                new_row[key] = value
        mapped.append(new_row)
    return mapped
