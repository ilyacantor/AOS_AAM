"""
Background worker that re-dispatches queued runner jobs to Farm.

If the initial Farm dispatch failed (unreachable, timeout, etc.), jobs
remain "queued" in the DB.  This worker picks them up and retries the
Farm dispatch.  AAM never executes data extraction — Farm does.
"""
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

from ..logger import get_logger
from ..config import settings
from ..db.runner_jobs import get_runner_job, update_runner_status, increment_retry_count
from ..models import JobManifest

_log = get_logger("services.runner_worker")

POLL_INTERVAL_S = float(os.environ.get("RUNNER_POLL_INTERVAL_S", "0.5"))

_worker_task: Optional[asyncio.Task] = None
_running = False


def _claim_queued_jobs() -> list[str]:
    """Atomically claim ALL queued jobs by updating them to 'running' and returning their IDs.

    Uses UPDATE ... RETURNING to prevent duplicate execution across restarts.
    No limit — every queued job is claimed and dispatched in parallel.
    """
    from ..db import supabase_client as sb
    from psycopg2 import sql as psql

    query = psql.SQL(
        "UPDATE {} SET status = 'running', started_at = NOW(), last_heartbeat = NOW() "
        "WHERE job_id IN ("
        "  SELECT job_id FROM {} WHERE status = 'queued'"
        "  AND (retry_after IS NULL OR retry_after <= NOW()::text)"
        "  ORDER BY dispatched_at"
        ") RETURNING job_id"
    ).format(sb._ident("runner_jobs"), sb._ident("runner_jobs"))

    try:
        rows = sb._execute_composed(query)
        return [r["job_id"] for r in rows]
    except Exception as exc:
        _log.error("Failed to claim queued jobs: %s", exc)
        return []


async def start_worker():
    """Start the background worker loop. Called from app lifespan."""
    global _worker_task, _running
    if _worker_task is not None:
        return
    _running = True
    _worker_task = asyncio.create_task(_worker_loop())
    _log.info("Background runner worker started (poll=%.1fs, unlimited concurrency)", POLL_INTERVAL_S)


async def stop_worker():
    """Stop the background worker. Called from app lifespan shutdown."""
    global _worker_task, _running
    _running = False
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    _log.info("Background runner worker stopped")


async def _worker_loop():
    """Main loop: poll for queued jobs and dispatch ALL to Farm in parallel.

    Claims every queued job each cycle and dispatches them concurrently
    via asyncio.gather. Farm handles its own concurrency/backpressure.
    """
    while _running:
        try:
            claimed_ids = await asyncio.to_thread(_claim_queued_jobs)

            if claimed_ids:
                _log.info("Worker claimed %d jobs, dispatching in parallel", len(claimed_ids))
                await asyncio.gather(
                    *[_dispatch_job_to_farm(job_id) for job_id in claimed_ids]
                )

            await asyncio.sleep(POLL_INTERVAL_S)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _log.error("Worker loop error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_S)


def _requeue_with_backoff(
    job_id: str, attempt: int, max_retries: int, error_msg: str, retry_after: str,
):
    """Set job back to queued with a retry_after timestamp for backoff."""
    from ..db import supabase_client as sb
    sb.update("runner_jobs", {
        "status": "queued",
        "error_message": f"[REQUEUED attempt {attempt}/{max_retries}] {error_msg}",
        "retry_after": retry_after,
    }, filters={"job_id": job_id})


async def _dispatch_job_to_farm(job_id: str):
    """Load a job's manifest and dispatch to Farm.

    AAM never executes data extraction.  If Farm is unreachable, the job
    is returned to 'queued' for later retry.
    """
    from .runner_dispatch import dispatch_to_farm

    try:
        job = await asyncio.to_thread(get_runner_job, job_id)
        if not job:
            _log.warning("Worker: job %s not found, skipping", job_id)
            return

        manifest_data = job.get("manifest")
        if not manifest_data:
            _log.warning("Worker: job %s has no manifest, marking failed", job_id)
            await asyncio.to_thread(
                update_runner_status, job_id, "failed",
                error_message="No manifest found in job record",
            )
            return

        manifest = JobManifest(**manifest_data)
        _log.info("Worker dispatching job %s (pipe %s) to Farm", job_id, manifest.source.pipe_id)

        result = await dispatch_to_farm(manifest)

        if result.get("status") == "dispatched":
            _log.info("Worker: job %s dispatched to Farm successfully", job_id)
        elif result.get("status") == "farm_unreachable":
            # Transient error — increment retry count and decide: requeue or exhaust.
            unreachable_msg = result.get("error", "Farm unreachable — no detail captured")
            new_count = await asyncio.to_thread(increment_retry_count, job_id)
            max_retries = settings.FARM_MAX_RETRIES

            if new_count > max_retries:
                exhaust_msg = (
                    f"[RETRIES_EXHAUSTED] Failed after {new_count - 1}/{max_retries} retries. "
                    f"Last error: {unreachable_msg}"
                )
                _log.warning("Worker: job %s exhausted %d retries, marking failed", job_id, max_retries)
                await asyncio.to_thread(
                    update_runner_status, job_id, "failed",
                    error_message=exhaust_msg,
                )
            else:
                # Exponential backoff: base * 2^(attempt-1), capped at 5 min
                backoff_s = min(settings.FARM_RETRY_BACKOFF_S * (2 ** (new_count - 1)), 300)
                retry_at = (datetime.utcnow() + timedelta(seconds=backoff_s)).isoformat()
                _log.warning(
                    "Worker: Farm unreachable for job %s (attempt %d/%d), "
                    "returning to queued with retry_after=%s (%ds). %s",
                    job_id, new_count, max_retries, retry_at, backoff_s, unreachable_msg,
                )
                await asyncio.to_thread(
                    _requeue_with_backoff, job_id, new_count, max_retries,
                    unreachable_msg, retry_at,
                )
        else:
            err = result.get("error", "Farm dispatch failed")
            _log.warning("Worker: Farm rejected job %s [%s]: %s", job_id, result.get("error_class", "?"), err)
            await asyncio.to_thread(
                update_runner_status, job_id, "failed",
                error_message=err,
            )

    except Exception as exc:
        _log.error("Worker job %s dispatch failed: %s", job_id, exc)
        try:
            await asyncio.to_thread(
                update_runner_status, job_id, "failed",
                error_message=str(exc),
            )
        except Exception as _status_exc:
            _log.error("Failed to mark job %s as failed in DB after dispatch error: %s", job_id, _status_exc)
