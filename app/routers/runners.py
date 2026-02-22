"""
Runner API — dispatch manifests to Farm, list jobs, runner callback.

AAM dispatches JobManifests to Farm (Path 2).  Farm executes extraction
and pushes data to DCL (Path 3).  AAM never executes data extraction.

RACI: AAM is A/R for Collector Run Execution (Row 43) and Track Collector Runs (Row 48).
"""
import asyncio
import re
from fastapi import APIRouter, HTTPException, Header, Query
from typing import Optional

from ..models import (
    RunnerDispatchRequest,
    RunnerBatchDispatchRequest,
    RunnerCallbackRequest,
    RunnerJobStatus,
)
from ..services.runner_dispatch import dispatch_pipe, dispatch_batch, dispatch_to_farm
from ..db.runner_jobs import (
    get_runner_job,
    get_runner_progress,
    list_runner_jobs,
    update_runner_status,
    update_heartbeat,
    cancel_queued_jobs,
)
from ..config import settings
from ..logger import get_logger

_log = get_logger("routers.runners")

router = APIRouter(prefix="/api/runners", tags=["Runners"])


@router.post("/dispatch")
async def dispatch_single(req: RunnerDispatchRequest):
    """Dispatch a runner job for a single pipe.

    Builds a JobManifest, stores it, and POSTs it to Farm's intake
    endpoint.  AAM does NOT execute the job — Farm does.
    """
    try:
        result = dispatch_pipe(
            req.pipe_id,
            req.trigger,
        )
        manifest = result.pop("_manifest")
        farm_result = await dispatch_to_farm(manifest)
        result["status"] = farm_result.get("status", "dispatched")
        if farm_result.get("error_class"):
            result["error_class"] = farm_result["error_class"]
        if farm_result.get("error"):
            result["farm_error"] = farm_result["error"]
            # dispatch_to_farm already wrote "failed" to the DB for non-2xx responses.
            # farm_unreachable is the only case where the job stays queued for retry.
        if farm_result.get("farm_response"):
            result["farm_response"] = farm_result["farm_response"]
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/dispatch-batch")
async def dispatch_multiple(req: RunnerBatchDispatchRequest):
    """Dispatch runner jobs for multiple pipes to Farm.

    Builds manifests, stores them, and POSTs each to Farm's intake
    endpoint in parallel.  Pings Farm health first to wake cold instances.
    """
    if not req.pipe_ids:
        raise HTTPException(status_code=400, detail="pipe_ids is required")

    # Wake Farm if it's sleeping (free-tier cold start)
    import httpx
    farm_base = settings.FARM_INTAKE_URL.replace("/api/farm/manifest-intake", "")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.get(f"{farm_base}/api/health")
        _log.info("Farm health ping OK — proceeding with batch dispatch")
    except Exception as exc:
        _log.warning("Farm health ping failed (%s) — dispatching anyway", exc)

    results = dispatch_batch(req.pipe_ids, req.trigger)

    for result in results:
        result.pop("_manifest", None)

    queued = [r for r in results if r.get("status") == "queued"]
    errors = [r for r in results if r.get("status") in ("error", "skipped")]

    _log.info("Batch dispatch: %d queued for Farm, %d skipped/errors", len(queued), len(errors))

    return {
        "dispatched": len(queued),
        "errors": len(errors),
        "jobs": results,
        "message": f"{len(queued)} manifests queued for Farm worker",
    }


@router.post("/cancel-queued")
async def cancel_all_queued():
    """Cancel all queued and running jobs. Operator stop button."""
    cancelled = cancel_queued_jobs()
    _log.info("Operator cancelled %d queued/running jobs", cancelled)
    return {"cancelled": cancelled, "message": f"{cancelled} jobs cancelled"}


@router.get("/progress")
async def runner_progress():
    """Live progress monitor for batch dispatch — shows counts by status."""
    return get_runner_progress()


@router.get("/jobs")
async def list_jobs(
    pipe_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """List runner jobs with optional filters."""
    jobs = list_runner_jobs(pipe_id=pipe_id, status=status, limit=limit)
    for j in jobs:
        if j.get("error_message") and "<!DOCTYPE" in j["error_message"]:
            j["error_message"] = re.sub(r"<!DOCTYPE[\s\S]*", "", j["error_message"]).strip()
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get runner job details including full manifest."""
    job = get_runner_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/manifest")
async def get_job_manifest(job_id: str):
    """Download the immutable Job Manifest for a runner job."""
    job = get_runner_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.get("manifest", {})


@router.put("/callback/{run_id}")
async def runner_callback(run_id: str, req: RunnerCallbackRequest):
    """Runner reports status back to AAM (heartbeat / terminal status).

    RACI Row 48: AAM must track collector run status.
    Refinement A: Runners MUST call this on success or failure.
    """
    job = get_runner_job(run_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Validate state transition
    current = job.get("status")
    terminal = {"completed", "failed", "timed_out"}
    if current in terminal:
        raise HTTPException(
            status_code=409,
            detail=f"Job already in terminal state: {current}",
        )

    updated = update_runner_status(
        run_id,
        req.status.value,
        rows_transferred=req.rows_transferred,
        error_message=req.error_message,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update job")

    return {"job_id": run_id, "status": req.status.value, "message": "Status updated"}


@router.put("/heartbeat/{run_id}")
async def runner_heartbeat(run_id: str):
    """Runner sends periodic heartbeat to prevent stale-job reaping."""
    job = get_runner_job(run_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    update_heartbeat(run_id)
    return {"job_id": run_id, "heartbeat": "ok"}
