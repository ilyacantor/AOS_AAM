"""
Runner API — dispatch jobs, list jobs, runner callback.

RACI: AAM is A/R for Collector Run Execution (Row 43) and Track Collector Runs (Row 48).
"""
from fastapi import APIRouter, HTTPException, Header, Query
from typing import Optional

from ..models import (
    RunnerDispatchRequest,
    RunnerBatchDispatchRequest,
    RunnerCallbackRequest,
    RunnerJobStatus,
)
from ..services.runner_dispatch import dispatch_pipe, dispatch_batch
from ..services.runner_execute import execute_job_inline
from ..db.runner_jobs import (
    get_runner_job,
    list_runner_jobs,
    update_runner_status,
    update_heartbeat,
)

router = APIRouter(prefix="/api/runners", tags=["Runners"])


@router.post("/dispatch")
async def dispatch_single(req: RunnerDispatchRequest):
    """Dispatch a runner job for a single pipe.

    Builds a JobManifest from the pipe definition and queues it.
    """
    try:
        result = dispatch_pipe(
            req.pipe_id,
            req.trigger,
        )
        # v1: execute inline immediately after dispatch
        exec_result = await execute_job_inline(result["job_id"])
        result.update(exec_result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/dispatch-batch")
async def dispatch_multiple(req: RunnerBatchDispatchRequest):
    """Dispatch runner jobs for multiple pipes."""
    if not req.pipe_ids:
        raise HTTPException(status_code=400, detail="pipe_ids is required")
    results = dispatch_batch(req.pipe_ids, req.trigger)
    return {
        "dispatched": len([r for r in results if r.get("status") == "queued"]),
        "errors": len([r for r in results if r.get("status") == "error"]),
        "jobs": results,
    }


@router.get("/jobs")
async def list_jobs(
    pipe_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """List runner jobs with optional filters."""
    jobs = list_runner_jobs(pipe_id=pipe_id, status=status, limit=limit)
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
