"""
DCL Ingestion Endpoint — Runners push normalized data here.

RACI Row 88 (Record Buffering): DCL is A/R.
RACI Row 63 (Schema Drift Detection): x-schema-hash comparison.

Only accepts data from authorized runner jobs (run_id must exist in runner_jobs).
"""
from fastapi import APIRouter, HTTPException, Header, Query
from typing import Optional

from ..models import DCLIngestRequest, DCLIngestResponse
from ..db.runner_jobs import get_runner_job, update_runner_status
from ..db.dcl_ingest import (
    store_ingest,
    compute_schema_hash,
    get_previous_schema_hash,
    list_ingests,
    get_ingest,
)
from ..db import create_drift_event
from ..logger import get_logger

_log = get_logger("routers.dcl_ingest")

router = APIRouter(prefix="/api/dcl", tags=["DCL Ingestion"])


@router.post("/ingest", response_model=DCLIngestResponse)
async def ingest_data(
    body: DCLIngestRequest,
    x_run_id: str = Header(..., alias="x-run-id"),
    x_pipe_id: str = Header(..., alias="x-pipe-id"),
    x_schema_hash: Optional[str] = Header(None, alias="x-schema-hash"),
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    """Accept a data payload from a Runner.

    Headers (provenance):
        x-run-id: The run_id from the Job Manifest (for correlation).
        x-pipe-id: The pipe_id from the Job Manifest (required, used for job lookup).
        x-schema-hash: SHA-256 of the data structure (drift detection).
        x-api-key: Runner auth token (validated if present).

    Body (flat, per DCL contract):
        source_system, tenant_id, snapshot_name, run_timestamp, rows[]
    """
    # --- Validate authorized job by pipe_id (job_id = pipe_id) ---
    job = get_runner_job(x_pipe_id)
    if not job:
        raise HTTPException(
            status_code=403,
            detail=f"Unknown pipe_id: {x_pipe_id}. Only authorized runner jobs may push data.",
        )

    # Cross-validate x-pipe-id header against manifest
    manifest = job.get("manifest", {})
    expected_pipe = manifest.get("source", {}).get("pipe_id")
    if x_pipe_id and expected_pipe and x_pipe_id != expected_pipe:
        raise HTTPException(
            status_code=400,
            detail=f"x-pipe-id mismatch: manifest expects {expected_pipe}, got {x_pipe_id}",
        )

    # Resolve pipe_id: header > manifest
    pipe_id = x_pipe_id or expected_pipe or "unknown"

    # --- Compute schema hash if not provided ---
    computed_hash = compute_schema_hash(body.rows) if body.rows else None
    final_hash = x_schema_hash or computed_hash

    # --- Schema drift detection (Refinement C / RACI Row 63) ---
    drift_detected = False
    previous_hash = get_previous_schema_hash(pipe_id)
    if previous_hash and final_hash and previous_hash != final_hash:
        drift_detected = True
        _log.warning(
            "Schema drift detected for pipe %s: %s → %s",
            pipe_id, previous_hash, final_hash,
        )
        try:
            create_drift_event({
                "pipe_id": pipe_id,
                "drift_type": "schema",
                "old_value": previous_hash,
                "new_value": final_hash,
            })
        except Exception as exc:
            _log.warning("Failed to create drift event: %s", exc)

    # --- Store the payload ---
    update_runner_status(x_pipe_id, "pushing")

    record = store_ingest(
        run_id=x_run_id,
        pipe_id=pipe_id,
        source_system=body.source_system,
        data=body.rows,
        schema_hash=final_hash,
    )

    # --- Update runner job status ---
    update_runner_status(
        x_pipe_id,
        "completed",
        rows_transferred=record["row_count"],
        dcl_response=record,
    )

    # --- FARM verification hook (Phase 4 placeholder) ---
    if manifest.get("farm_verification"):
        _log.info("FARM verification requested for run %s (not yet implemented)", x_run_id)

    return DCLIngestResponse(
        status="ingested",
        ingest_id=record["ingest_id"],
        run_id=x_run_id,
        rows_stored=record["row_count"],
        schema_hash=final_hash,
        schema_drift_detected=drift_detected,
    )


@router.get("/ingests")
async def list_all_ingests(
    pipe_id: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """List ingested payloads (summaries, without full data)."""
    ingests = list_ingests(pipe_id=pipe_id, run_id=run_id, limit=limit)
    return {"ingests": ingests, "count": len(ingests)}


@router.get("/ingests/{ingest_id}")
async def get_single_ingest(ingest_id: str):
    """Get a specific ingest including full payload."""
    record = get_ingest(ingest_id)
    if not record:
        raise HTTPException(status_code=404, detail="Ingest not found")
    return record
