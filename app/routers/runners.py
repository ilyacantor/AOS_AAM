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
from ..services.runner_dispatch import dispatch_pipe, dispatch_batch, dispatch_to_farm, dispatch_to_farm_batch, notify_dcl_dispatch
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
from ..db.dcl_pushes import has_dcl_push_for_run, get_exported_pipe_ids
from ..db.handoff import list_handoff_logs

_log = get_logger("routers.runners")

router = APIRouter(prefix="/api/runners", tags=["Runners"])


def _require_dcl_export() -> set[str]:
    """Guard: reject dispatch if export-pipes hasn't been pushed to DCL for the current snapshot.

    Without the export, DCL has no schema blueprints and will reject every
    record Farm pushes — wasting Farm compute and producing only NO_MATCHING_PIPE errors.

    Returns the set of pipe_ids from the last DCL export so callers can
    verify that every pipe being dispatched was actually exported.
    """
    handoffs = list_handoff_logs(limit=1)
    if not handoffs:
        raise HTTPException(
            status_code=409,
            detail=(
                "No AOD handoff found. Run the full pipeline "
                "(Fetch AOD → Infer → Export → Dispatch) before dispatching runners."
            ),
        )
    aod_run_id = handoffs[0].get("aod_run_id")
    snapshot_name = handoffs[0].get("snapshot_name", "unknown")
    if not aod_run_id:
        raise HTTPException(
            status_code=409,
            detail="Latest handoff has no aod_run_id — cannot verify DCL export.",
        )
    if not has_dcl_push_for_run(aod_run_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"DCL has not received pipe blueprints for snapshot '{snapshot_name}' "
                f"(aod_run_id={aod_run_id}). Run 'Export to DCL' first — without it, "
                f"Farm data will be rejected by DCL with NO_MATCHING_PIPE."
            ),
        )
    return get_exported_pipe_ids(aod_run_id)


@router.get("/can-dispatch")
def can_dispatch():
    """Check whether the Dispatch Runner button should be enabled."""
    handoffs = list_handoff_logs(limit=1)
    if not handoffs:
        return {"ready": False, "reason": "No AOD data fetched yet. Run the full pipeline first."}
    aod_run_id = handoffs[0].get("aod_run_id")
    snapshot_name = handoffs[0].get("snapshot_name", "unknown")
    if not aod_run_id:
        return {"ready": False, "reason": "Latest handoff has no run ID."}
    if not has_dcl_push_for_run(aod_run_id):
        return {
            "ready": False,
            "reason": f"Export to DCL required first for '{snapshot_name}'. Without it, Farm data will be rejected.",
        }
    return {"ready": True, "reason": None, "snapshot_name": snapshot_name}


@router.post("/dispatch")
async def dispatch_single(req: RunnerDispatchRequest):
    """Dispatch a runner job for a single pipe.

    Builds a JobManifest, stores it, and POSTs it to Farm's intake
    endpoint.  AAM does NOT execute the job — Farm does.
    """
    exported_ids = _require_dcl_export()
    try:
        result = dispatch_pipe(
            req.pipe_id,
            req.trigger,
        )
        manifest = result.pop("_manifest")

        # Verify the pipe_id was included in the last DCL export
        if exported_ids and manifest.source.pipe_id not in exported_ids:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Pipe {manifest.source.pipe_id} was not included in the last DCL export. "
                    "Re-run 'Export to DCL' before dispatching."
                ),
            )

        # Notify DCL of dispatch intent (best-effort, non-blocking)
        dcl_signal = await notify_dcl_dispatch()
        if dcl_signal.get("status") != "notified":
            _log.warning("DCL dispatch signal did not succeed: %s", dcl_signal)

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
    exported_ids = _require_dcl_export()
    if not req.pipe_ids:
        raise HTTPException(status_code=400, detail="pipe_ids is required")

    # Fire-and-forget Farm wake ping — runs concurrently while manifests are built.
    # Its only purpose is waking Render cold-start; dispatch proceeds regardless.
    import httpx
    farm_base = settings.FARM_INTAKE_URL.replace("/api/farm/manifest-intake", "")

    async def _wake_farm():
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(f"{farm_base}/api/health")
            if resp.status_code == 200:
                _log.info("Farm health wake-ping OK (status=%d)", resp.status_code)
            else:
                _log.warning(
                    "Farm health wake-ping returned non-200: status=%d body=%s",
                    resp.status_code, resp.text[:200],
                )
        except Exception as exc:
            _log.warning("Farm health wake-ping failed: %s", exc)

    asyncio.create_task(_wake_farm())

    results = dispatch_batch(req.pipe_ids, req.trigger)

    # Validate every dispatched pipe_id was included in the last DCL export
    if exported_ids:
        for result in results:
            manifest = result.get("_manifest")
            if manifest and result.get("status") == "queued":
                if manifest.source.pipe_id not in exported_ids:
                    result["status"] = "skipped"
                    result["error"] = (
                        f"Pipe {manifest.source.pipe_id} was not included in the last DCL export. "
                        "Re-run 'Export to DCL' before dispatching."
                    )
                    _log.warning(
                        "Blocking dispatch of pipe %s — not in last DCL export",
                        manifest.source.pipe_id,
                    )

    # Extract manifests and dispatch to Farm inline (not just queued for background worker)
    farm_tasks = []
    for result in results:
        manifest = result.pop("_manifest", None)
        payload = result.pop("_payload", None)
        if manifest and result.get("status") == "queued":
            farm_tasks.append((result, manifest, payload))

    async def _dispatch_one(result_dict: dict, manifest_obj, payload_dict: dict):
        try:
            farm_result = await dispatch_to_farm(manifest_obj, payload=payload_dict)
            result_dict["status"] = farm_result.get("status", "dispatched")
            if farm_result.get("error_class"):
                result_dict["error_class"] = farm_result["error_class"]
            if farm_result.get("error"):
                result_dict["farm_error"] = farm_result["error"]
            if farm_result.get("farm_response"):
                result_dict["farm_response"] = farm_result["farm_response"]
        except Exception as exc:
            result_dict["status"] = "error"
            result_dict["farm_error"] = str(exc)

    # Notify DCL of dispatch intent ONCE for the whole batch (best-effort)
    if farm_tasks:
        dcl_signal = await notify_dcl_dispatch()
        if dcl_signal.get("status") != "notified":
            _log.warning("DCL dispatch signal did not succeed: %s", dcl_signal)

    if farm_tasks:
        # Try batch dispatch first (single HTTP round-trip to Farm).
        # Fall back to individual POSTs if batch fails.
        all_payloads = [p for _, _, p in farm_tasks]
        all_manifests = [m for _, m, _ in farm_tasks]
        batch_id = all_manifests[0].run_id if all_manifests else "unknown"

        batch_result = await dispatch_to_farm_batch(
            manifests=[m.model_dump() for m in all_manifests],
            batch_id=batch_id,
            concurrency=5,
            payloads=all_payloads,
        )

        if batch_result.get("status") == "batch_dispatched":
            # Batch succeeded — update result dicts from Farm's batch response
            farm_resp = batch_result.get("farm_response", {})
            push_results_list = farm_resp.get("push_results", [])
            # Build lookup from pipe_id → push_result for status mapping
            push_by_pipe = {pr.get("pipe_id"): pr for pr in push_results_list}
            for result_dict, manifest_obj, _ in farm_tasks:
                pid = manifest_obj.source.pipe_id
                pr = push_by_pipe.get(pid, {})
                pr_status = pr.get("status", "unknown")

                # Guard: Farm processes synchronously and fires callbacks
                # before returning the batch response. Don't regress a
                # terminal status that the callback already wrote.
                current_job = get_runner_job(pid)
                current_status = current_job.get("status") if current_job else None
                _terminal = ("completed", "failed", "timed_out")

                if pr_status == "success":
                    result_dict["status"] = "dispatched"
                    if current_status not in _terminal:
                        update_runner_status(pid, "dispatched")
                    else:
                        _log.info(
                            "Skipping 'dispatched' write — job %s already %s (callback arrived first)",
                            pid, current_status,
                        )
                elif pr_status == "rejected":
                    result_dict["status"] = "farm_error"
                    result_dict["error_class"] = pr.get("error_type", "")
                    result_dict["farm_error"] = pr.get("error", "")
                    if current_status not in _terminal:
                        update_runner_status(pid, "failed", error_message=pr.get("error", ""))
                else:
                    result_dict["status"] = "dispatched"
                    if current_status not in _terminal:
                        update_runner_status(pid, "dispatched")
                    else:
                        _log.info(
                            "Skipping 'dispatched' write — job %s already %s (callback arrived first)",
                            pid, current_status,
                        )
                result_dict["farm_response"] = pr
            _log.info(
                "Batch dispatch succeeded: %d manifests, Farm elapsed=%ss",
                len(farm_tasks), farm_resp.get("elapsed_seconds"),
            )
        else:
            # Batch failed — fall back to individual dispatch.
            # WARNING: if the failure was a timeout, Farm may still be processing
            # the original batch. Individual POSTs will create DUPLICATE work
            # (57 + 57 = 114 manifests in flight against DCL).
            batch_status = batch_result.get("status", "unknown")
            is_timeout = "unreachable" in batch_status or "timeout" in batch_result.get("error", "").lower()
            if is_timeout:
                _log.error(
                    "[BATCH_TIMEOUT_FALLBACK] Batch POST timed out (status=%s). "
                    "Farm may still be processing the original batch — falling back "
                    "to %d individual POSTs risks double-dispatch. error=%s",
                    batch_status, len(farm_tasks),
                    batch_result.get("error", "")[:300],
                )
            else:
                _log.warning(
                    "[BATCH_FALLBACK] Batch dispatch failed (status=%s), "
                    "falling back to %d individual POSTs: %s",
                    batch_status, len(farm_tasks),
                    batch_result.get("error", "")[:200],
                )
            _FARM_CONCURRENCY = 10
            sem = asyncio.Semaphore(_FARM_CONCURRENCY)

            async def _throttled(result_dict: dict, manifest_obj, payload_dict: dict):
                async with sem:
                    await _dispatch_one(result_dict, manifest_obj, payload_dict)

            await asyncio.gather(*[_throttled(r, m, p) for r, m, p in farm_tasks])

    dispatched = [r for r in results if r.get("status") == "dispatched"]
    errors = [r for r in results if r.get("status") in ("error", "skipped", "farm_error", "farm_unreachable", "failed")]

    _log.info("Batch dispatch: %d dispatched to Farm, %d errors/skipped", len(dispatched), len(errors))

    return {
        "dispatched": len(dispatched),
        "errors": len(errors),
        "jobs": results,
        "message": f"{len(dispatched)} manifests dispatched to Farm",
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
    import json as _json
    jobs = list_runner_jobs(pipe_id=pipe_id, status=status, limit=limit)
    for j in jobs:
        if j.get("error_message") and "<!DOCTYPE" in j["error_message"]:
            j["error_message"] = re.sub(r"<!DOCTYPE[\s\S]*", "", j["error_message"]).strip()
        # Parse dcl_response from JSON string to dict for frontend consumption
        if j.get("dcl_response") and isinstance(j["dcl_response"], str):
            try:
                j["dcl_response"] = _json.loads(j["dcl_response"])
            except (ValueError, TypeError):
                pass
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


@router.put("/callback/{pipe_id}")
async def runner_callback(pipe_id: str, req: RunnerCallbackRequest):
    """Runner reports status back to AAM (heartbeat / terminal status).

    RACI Row 48: AAM must track collector run status.
    Refinement A: Runners MUST call this on success or failure.
    Farm sends pipe_id (= job_id) as the path parameter.
    """
    job = get_runner_job(pipe_id)
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
        pipe_id,
        req.status.value,
        rows_transferred=req.rows_transferred,
        error_message=req.error_message,
        dcl_response=req.dcl_response,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update job")

    return {"job_id": pipe_id, "status": req.status.value, "message": "Status updated"}


@router.put("/heartbeat/{pipe_id}")
async def runner_heartbeat(pipe_id: str):
    """Runner sends periodic heartbeat to prevent stale-job reaping."""
    job = get_runner_job(pipe_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    update_heartbeat(pipe_id)
    return {"job_id": pipe_id, "heartbeat": "ok"}


@router.get("/farm-status/{job_id}")
async def farm_status_proxy(job_id: str):
    """Proxy to Farm's /api/farm/status/{job_id} for dispatch modal enrichment.

    Returns Farm-side execution state (rows_generated vs rows_accepted)
    alongside the AAM-side status. Only called when the dispatch modal
    is open to avoid unnecessary requests.
    """
    import httpx
    farm_base = settings.FARM_INTAKE_URL.replace("/api/farm/manifest-intake", "")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{farm_base}/api/farm/status/{job_id}")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Job not found on Farm")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Farm returned {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        _log.warning("Farm status proxy failed for %s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail=f"Farm unreachable: {exc}")
