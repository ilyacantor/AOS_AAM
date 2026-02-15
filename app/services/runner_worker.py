"""
Background worker that processes queued runner jobs.

Polls for queued jobs, executes them with bounded concurrency (Semaphore 5),
and updates status in DB. The dispatch-batch endpoint just inserts jobs as 
'queued' and returns immediately — this worker handles execution.
"""
import asyncio
from typing import Optional

from ..logger import get_logger
from ..db.runner_jobs import update_runner_status
from ..services.runner_execute import execute_job_inline

_log = get_logger("services.runner_worker")

WORKER_CONCURRENCY = 5
POLL_INTERVAL_S = 2.0

_worker_task: Optional[asyncio.Task] = None
_running = False


def _claim_queued_jobs(limit: int = 50) -> list[str]:
    """Atomically claim queued jobs by updating them to 'running' and returning their IDs.

    Uses UPDATE ... RETURNING to prevent duplicate execution across restarts.
    """
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
    """Main loop: poll for queued jobs and execute with bounded concurrency."""
    sem = asyncio.Semaphore(WORKER_CONCURRENCY)
    active_jobs: set = set()

    while _running:
        try:
            claimed_ids = await asyncio.to_thread(_claim_queued_jobs, 50)
            new_ids = [jid for jid in claimed_ids if jid not in active_jobs]

            if new_ids:
                _log.info("Worker claimed %d queued jobs", len(new_ids))
                for job_id in new_ids:
                    active_jobs.add(job_id)
                    asyncio.create_task(_run_with_semaphore(sem, job_id, active_jobs))

            await asyncio.sleep(POLL_INTERVAL_S)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _log.error("Worker loop error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_S)


async def _run_with_semaphore(sem: asyncio.Semaphore, job_id: str, active_jobs: set):
    """Execute a single job under semaphore control."""
    try:
        async with sem:
            _log.info("Worker executing job %s", job_id)
            await execute_job_inline(job_id)
    except Exception as exc:
        _log.error("Worker job %s failed: %s", job_id, exc)
        try:
            await asyncio.to_thread(update_runner_status, job_id, "failed", error_message=str(exc))
        except Exception:
            pass
    finally:
        active_jobs.discard(job_id)
