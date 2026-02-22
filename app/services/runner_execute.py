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
import asyncio
import httpx
from datetime import datetime
from typing import Optional

from ..config import settings
from ..logger import get_logger
from ..db.runner_jobs import update_runner_status, get_runner_job
from ..db.dcl_ingest import compute_schema_hash

_log = get_logger("services.runner_execute")


def _resolve_dcl_url() -> str:
    dcl_ingest = settings.DCL_INGEST_URL
    if dcl_ingest.startswith("http://") or dcl_ingest.startswith("https://"):
        return dcl_ingest
    return f"{settings.BASE_URL}{dcl_ingest}"


def _prepare_job(job_id: str) -> dict:
    """Blocking: read manifest from DB, build payload. Returns prep dict.
    
    Skips redundant status updates — the background worker already marks
    jobs 'running' atomically via _claim_queued_jobs.
    """
    job = get_runner_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    manifest = job.get("manifest", {})
    source = manifest.get("source", {})
    target = manifest.get("target", {})
    pipe_id = source.get("pipe_id", "unknown")
    system = source.get("system", "unknown")

    if job.get("status") != "running":
        update_runner_status(job_id, "running")

    extracted_data = _generate_simulated_data(source)
    transform = manifest.get("transform")
    if transform and transform.get("schema_map"):
        extracted_data = _apply_schema_map(extracted_data, transform["schema_map"])

    schema_hash = compute_schema_hash(extracted_data)

    provenance = manifest.get("provenance", {})
    run_ts = provenance.get("run_timestamp", datetime.utcnow().isoformat())
    headers = {
        "x-run-id": manifest.get("run_id", job_id),
        "x-pipe-id": pipe_id,
        "x-schema-hash": schema_hash,
        "x-api-key": settings.DCL_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "source_system": system,
        "tenant_id": target.get("tenant_id") or "default",
        "snapshot_name": target.get("snapshot_name") or f"snap_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        "run_timestamp": run_ts,
        "schema_version": schema_hash[:16],
        "row_count": len(extracted_data),
        "rows": extracted_data,
    }
    return {
        "manifest": manifest,
        "pipe_id": pipe_id,
        "system": system,
        "extracted_data": extracted_data,
        "schema_hash": schema_hash,
        "headers": headers,
        "payload": payload,
    }


def _finalize_job(job_id: str, status: str, **kwargs):
    """Blocking: write final status to DB."""
    update_runner_status(job_id, status, **kwargs)


async def execute_job_inline(job_id: str, http_client: httpx.AsyncClient | None = None) -> dict:
    """Execute a runner job inline (v1 in-process worker).

    DB calls are offloaded to threads so they don't block the event loop.
    HTTP push uses async httpx for true concurrency.
    """
    try:
        prep = await asyncio.to_thread(_prepare_job, job_id)
    except ValueError as exc:
        raise exc

    pipe_id = prep["pipe_id"]
    schema_hash = prep["schema_hash"]
    extracted_data = prep["extracted_data"]
    dcl_url = _resolve_dcl_url()

    try:
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=float(settings.RUNNER_JOB_TIMEOUT_S))
        try:
            resp = await client.post(dcl_url, json=prep["payload"], headers=prep["headers"])
        finally:
            if owns_client:
                await client.aclose()

        if resp.status_code == 200:
            dcl_body = resp.json()
            dcl_status = dcl_body.get("status", "")
            if dcl_status == "ingested":
                await asyncio.to_thread(
                    _finalize_job, job_id, "completed",
                    rows_transferred=dcl_body.get("rows_stored", len(extracted_data)),
                    dcl_response=dcl_body,
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
                await asyncio.to_thread(
                    _finalize_job, job_id, "failed",
                    error_message=f"DCL returned unexpected status: {dcl_status}",
                )
                return {"job_id": job_id, "status": "failed", "error": f"DCL unexpected: {dcl_status}"}
        else:
            error_detail = resp.text[:500]
            await asyncio.to_thread(
                _finalize_job, job_id, "failed",
                error_message=f"DCL returned {resp.status_code}: {error_detail}",
            )
            return {"job_id": job_id, "status": "failed", "error": f"DCL {resp.status_code}: {error_detail}"}

    except httpx.ConnectError as exc:
        _log.error("DCL unreachable for job %s — job failed, no fallback: %s", job_id, exc)
        await asyncio.to_thread(
            _finalize_job, job_id, "failed",
            error_message=f"DCL unreachable: {exc}",
        )
        return {"job_id": job_id, "status": "failed", "error": f"DCL unreachable: {exc}"}

    except Exception as exc:
        _log.error("Runner failed job %s: %s", job_id, exc)
        await asyncio.to_thread(_finalize_job, job_id, "failed", error_message=str(exc))
        return {"job_id": job_id, "status": "failed", "error": str(exc)}


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
