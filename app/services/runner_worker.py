"""
Background worker that re-dispatches queued runner jobs to Farm.

If the initial Farm dispatch failed (unreachable, timeout, etc.), jobs
remain "queued" in the DB.  This worker picks them up and retries the
Farm dispatch.  AAM never executes data extraction — Farm does.
"""
import asyncio
from typing import Optional

from ..logger import get_logger
from ..db.runner_jobs import get_runner_job, update_runner_status
from ..models import JobManifest

_log = get_logger("services.runner_worker")

WORKER_CONCURRENCY = 2
POLL_INTERVAL_S = 2.0

_worker_task: Optional[asyncio.Task] = None
_running = False


def _claim_queued_jobs(limit: int) -> list[str]:
    """Atomically claim queued jobs by updating them to 'running' and returning their IDs.

    Uses UPDATE ... RETURNING to prevent duplicate execution across restarts.
    """
    if limit <= 0:
        return []

    from ..db import supabase_client as sb
    from psycopg2 import sql as psql

    query = psql.SQL(
        "UPDATE {} SET status = 'running', started_at = NOW(), last_heartbeat = NOW() "
        "WHERE job_id IN ("
        "  SELECT job_id FROM {} WHERE status = 'queued' ORDER BY dispatched_at LIMIT %s"
        ") RETURNING job_id"
    ).format(sb._ident("runner_jobs"), sb._ident("runner_jobs"))

    try:
        rows = sb._execute_composed(query, params=(limit,))
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
    _log.info("Background runner worker started (concurrency=%d)", WORKER_CONCURRENCY)


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
    """Main loop: poll for queued jobs and dispatch to Farm with bounded concurrency.

    Only claims as many jobs as we have capacity for (WORKER_CONCURRENCY - active).
    This prevents marking hundreds of jobs 'running' that can't dispatch yet.
    """
    active_jobs: set = set()

    while _running:
        try:
            capacity = WORKER_CONCURRENCY - len(active_jobs)
            if capacity > 0:
                claimed_ids = await asyncio.to_thread(_claim_queued_jobs, capacity)

                if claimed_ids:
                    _log.info("Worker claimed %d jobs (%d active)", len(claimed_ids), len(active_jobs))
                    for job_id in claimed_ids:
                        active_jobs.add(job_id)
                        asyncio.create_task(_dispatch_job_to_farm(job_id, active_jobs))

            await asyncio.sleep(POLL_INTERVAL_S)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _log.error("Worker loop error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_S)


async def _dispatch_job_to_farm(job_id: str, active_jobs: set):
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
            # Return to queued for later retry, but record what was tried so
            # the Dispatch Status modal shows actionable context rather than silence.
            unreachable_msg = result.get("error", "Farm unreachable — no detail captured")
            _log.warning("Worker: Farm unreachable for job %s, returning to queued. %s", job_id, unreachable_msg)
            await asyncio.to_thread(
                update_runner_status, job_id, "queued",
                error_message=f"[REQUEUED] {unreachable_msg}",
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
    finally:
        active_jobs.discard(job_id)
