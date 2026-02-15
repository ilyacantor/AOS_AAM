"""
Inline v1 Runner Execution — executes a job manifest in-process.

In production (v2+), this becomes a Docker container / serverless function.
For v1, the Runner executes as an async task and pushes to DCL via HTTP:
  1. Accept manifest
  2. Mark job "running"
  3. (Simulated) Connect to source, extract data
  4. POST to DCL /api/dcl/ingest with x-run-id + x-pipe-id + x-schema-hash
  5. Status derived from DCL HTTP response (200 = completed, else = failed)

Data bytes flow: Source → Runner → DCL (via HTTP).  AAM never sees the payload.
"""
import httpx
from datetime import datetime
from typing import Optional

from ..config import settings
from ..logger import get_logger
from ..db.runner_jobs import update_runner_status, get_runner_job
from ..db.dcl_ingest import compute_schema_hash

_log = get_logger("services.runner_execute")


async def execute_job_inline(job_id: str) -> dict:
    """Execute a runner job inline (v1 in-process worker).

    The Runner lifecycle:
    1. Read manifest from runner_jobs
    2. Mark status "running"
    3. Resolve credentials (v1: no-op, v2: vault fetch)
    4. Extract data from source (v1: simulated)
    5. Apply schema_map transform
    6. POST to DCL_INGEST_URL with headers:
       - x-run-id: from manifest
       - x-pipe-id: from manifest.source
       - x-schema-hash: computed from payload structure
    7. Status from DCL response: 200=completed, else=failed
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
        # --- Step 2: Resolve credentials (v1 = no-op) ---
        # In production: credentials_ref (vault://aam/secrets/xxx) is resolved
        # just-in-time here — never stored in the manifest JSON.
        cred_ref = source.get("credentials_ref")
        if cred_ref and cred_ref.startswith("vault://"):
            _log.info("Would resolve credential: %s (v1: skipped)", cred_ref)

        # --- Step 3: Extract data from source (v1 = simulated) ---
        extracted_data = _generate_simulated_data(source)

        # --- Step 4: Apply transform (schema normalization, Option A) ---
        transform = manifest.get("transform")
        if transform and transform.get("schema_map"):
            extracted_data = _apply_schema_map(extracted_data, transform["schema_map"])

        # --- Step 5: Compute schema hash (Refinement C) ---
        schema_hash = compute_schema_hash(extracted_data)

        # --- Step 6: Push to DCL via HTTP ---
        update_runner_status(job_id, "pushing")

        dcl_url = f"{settings.BASE_URL}{settings.DCL_INGEST_URL}"

        # --- Header mapping (exact DCL contract) ---
        #   x-run-id      ← manifest.run_id
        #   x-pipe-id     ← manifest.source.pipe_id
        #   x-schema-hash ← SHA-256 of transformed field structure
        #   x-api-key     ← resolved from vault/env (JIT, never stored in manifest)
        headers = {
            "x-run-id": manifest.get("run_id", job_id),
            "x-pipe-id": pipe_id,
            "x-schema-hash": schema_hash,
            "x-api-key": settings.DCL_API_KEY,
            "Content-Type": "application/json",
        }

        # --- Body mapping (flat, per DCL contract) ---
        #   source_system  ← manifest.source.system
        #   tenant_id      ← manifest.target.tenant_id
        #   snapshot_name  ← manifest.target.snapshot_name
        #   run_timestamp  ← manifest.provenance.run_timestamp
        #   rows           ← the actual transformed data list
        provenance = manifest.get("provenance", {})
        payload = {
            "source_system": system,
            "tenant_id": target.get("tenant_id"),
            "snapshot_name": target.get("snapshot_name"),
            "run_timestamp": provenance.get("run_timestamp", datetime.utcnow().isoformat()),
            "rows": extracted_data,
        }

        _log.info("Runner pushing %d rows to %s", len(extracted_data), dcl_url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(dcl_url, json=payload, headers=headers)

        # --- Step 7: Status from DCL response ---
        #   200 OK + status "ingested" → COMPLETED
        #   Anything else             → FAILED
        if resp.status_code == 200:
            dcl_body = resp.json()
            dcl_status = dcl_body.get("status", "")
            if dcl_status == "ingested":
                update_runner_status(
                    job_id,
                    "completed",
                    rows_transferred=dcl_body.get("rows_stored", len(extracted_data)),
                    dcl_response=dcl_body,
                )
                _log.info(
                    "Runner completed job %s: %d rows, hash=%s, drift=%s",
                    job_id,
                    dcl_body.get("rows_stored", 0),
                    schema_hash,
                    dcl_body.get("schema_drift_detected", False),
                )
                return {
                    "job_id": job_id,
                    "status": "completed",
                    "rows_transferred": dcl_body.get("rows_stored", 0),
                    "ingest_id": dcl_body.get("ingest_id"),
                    "schema_hash": schema_hash,
                    "schema_drift_detected": dcl_body.get("schema_drift_detected", False),
                }
            else:
                # 200 but unexpected status — treat as failure
                update_runner_status(
                    job_id,
                    "failed",
                    error_message=f"DCL returned unexpected status: {dcl_status}",
                )
                return {
                    "job_id": job_id,
                    "status": "failed",
                    "error": f"DCL returned unexpected status: {dcl_status}",
                }
        else:
            error_detail = resp.text[:500]
            _log.error(
                "DCL rejected ingest for job %s: %d %s",
                job_id, resp.status_code, error_detail,
            )
            update_runner_status(
                job_id,
                "failed",
                error_message=f"DCL returned {resp.status_code}: {error_detail}",
            )
            return {
                "job_id": job_id,
                "status": "failed",
                "error": f"DCL returned {resp.status_code}: {error_detail}",
            }

    except httpx.ConnectError as exc:
        # DCL endpoint unreachable — fall back to direct store for v1
        _log.warning(
            "DCL endpoint unreachable (%s), falling back to direct store for job %s",
            exc, job_id,
        )
        return await _fallback_direct_store(job_id, manifest, extracted_data, schema_hash)

    except Exception as exc:
        _log.error("Runner failed job %s: %s", job_id, exc)
        update_runner_status(job_id, "failed", error_message=str(exc))
        return {
            "job_id": job_id,
            "status": "failed",
            "error": str(exc),
        }


async def _fallback_direct_store(
    job_id: str,
    manifest: dict,
    data: list[dict],
    schema_hash: str,
) -> dict:
    """Fallback when DCL HTTP endpoint is unreachable (dev/test only).

    Stores directly via store_ingest, bypassing HTTP.
    """
    from ..db.dcl_ingest import store_ingest

    source = manifest.get("source", {})
    pipe_id = source.get("pipe_id", "unknown")
    system = source.get("system", "unknown")

    record = store_ingest(
        run_id=job_id,
        pipe_id=pipe_id,
        source_system=system,
        data=data,
        schema_hash=schema_hash,
    )
    update_runner_status(
        job_id,
        "completed",
        rows_transferred=record["row_count"],
        dcl_response={**record, "fallback": True},
    )
    _log.info("Fallback store completed for job %s: %d rows", job_id, record["row_count"])
    return {
        "job_id": job_id,
        "status": "completed",
        "rows_transferred": record["row_count"],
        "ingest_id": record["ingest_id"],
        "schema_hash": schema_hash,
        "schema_drift_detected": False,
        "fallback": True,
    }


def _generate_simulated_data(source: dict) -> list[dict]:
    """Generate simulated extraction data for v1 testing.

    In production, this is replaced by actual source connection + query.
    """
    system = source.get("system", "unknown").lower()
    now = datetime.utcnow().isoformat()

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
                if "scale" in mapping and isinstance(value, (int, float)):
                    value = value * mapping["scale"]
                new_row[target_name] = value
            else:
                new_row[key] = value
        mapped.append(new_row)
    return mapped
