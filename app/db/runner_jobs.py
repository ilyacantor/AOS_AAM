"""
Runner Jobs — tracks the lifecycle of each dispatched runner job.

State machine: queued → dispatched → running → pushing → completed / failed / timed_out
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def _build_job_row(manifest_dict: dict) -> dict:
    """Build a complete runner_jobs row dict from a manifest.

    Explicitly sets ALL columns so that UPSERT resets stale values
    from a previous run (e.g. completed_at, error_message).
    """
    now = datetime.utcnow().isoformat()
    return {
        "job_id": manifest_dict["source"]["pipe_id"],
        "pipe_id": manifest_dict["source"]["pipe_id"],
        "run_id": manifest_dict["run_id"],
        "status": "queued",
        "manifest": json.dumps(manifest_dict, default=str),
        "dispatched_at": now,
        "started_at": None,
        "completed_at": None,
        "last_heartbeat": None,
        "rows_transferred": 0,
        "error_message": None,
        "dcl_response": None,
        "retry_count": 0,
        "retry_after": None,
    }


def create_runner_job(manifest_dict: dict) -> str:
    """Create a new runner job from a manifest dict. Returns job_id (= pipe_id).

    Uses UPSERT (ON CONFLICT DO UPDATE) so re-dispatch overwrites
    the previous job in a single round-trip instead of DELETE + INSERT.
    All columns are explicitly set to prevent stale values leaking through.
    """
    row = _build_job_row(manifest_dict)
    sb.insert("runner_jobs", row, on_conflict="job_id")
    return row["job_id"]


def create_runner_jobs_batch(manifests: list[dict]) -> list[str]:
    """Bulk-upsert runner jobs from a list of manifest dicts. Returns list of job_ids (pipe_ids).

    Uses manifest.source.pipe_id as the job_id (PRIMARY KEY) for AAM's internal tracking.
    The manifest.run_id may be shared across manifests in a batch (for Farm grouping).
    UPSERT resets ALL columns so re-dispatched jobs start clean.
    """
    if not manifests:
        return []
    rows = [_build_job_row(m) for m in manifests]
    job_ids = [r["job_id"] for r in rows]
    sb.insert_many("runner_jobs", rows, on_conflict="job_id")
    from ..logger import get_logger
    get_logger("db.runner_jobs").info(
        "Upserted %d runner jobs (batch dispatch)", len(rows)
    )
    return job_ids


def create_skipped_jobs_batch(skipped_entries: list[dict], run_id: str, snapshot_name: Optional[str] = None) -> list[str]:
    """Bulk-insert runner_jobs rows with status='skipped' for pipes filtered out pre-dispatch.

    Each entry in skipped_entries must have 'pipe_id' and 'error' (skip reason).
    Entries may also carry 'source_system', 'category', 'matched_pipe_id' for display.
    A minimal manifest stub is stored so list_runner_jobs can extract source_system
    and snapshot_name via the same JSON paths used for real jobs.
    Uses UPSERT so re-runs overwrite previous skip records.
    """
    if not skipped_entries:
        return []
    now = datetime.utcnow().isoformat()
    rows = []
    for entry in skipped_entries:
        pid = entry["pipe_id"]
        # Build minimal manifest stub for SQL extraction compatibility
        manifest_stub = {
            "source": {
                "pipe_id": pid,
                "system": entry.get("source_system"),
            },
            "snapshot_name": snapshot_name,
            "run_id": run_id,
            "category": entry.get("category"),
            "matched_pipe_id": entry.get("matched_pipe_id"),
        }
        rows.append({
            "job_id": pid,
            "pipe_id": pid,
            "run_id": run_id,
            "status": "skipped",
            "manifest": json.dumps(manifest_stub, default=str),
            "dispatched_at": now,
            "started_at": None,
            "completed_at": now,
            "last_heartbeat": None,
            "rows_transferred": 0,
            "error_message": entry.get("error", "Skipped"),
            "dcl_response": None,
            "retry_count": 0,
            "retry_after": None,
        })
    job_ids = [r["job_id"] for r in rows]
    sb.insert_many("runner_jobs", rows, on_conflict="job_id")
    from ..logger import get_logger
    get_logger("db.runner_jobs").info(
        "Upserted %d skipped runner jobs (pre-dispatch filter)", len(rows)
    )
    return job_ids


def update_runner_status(
    job_id: str,
    status: str,
    *,
    rows_transferred: Optional[int] = None,
    error_message: Optional[str] = None,
    dcl_response: Optional[dict] = None,
) -> bool:
    """Update runner job status and optional fields.

    Returns True if a row was updated, False if no matching job found.
    Logs a warning when no job is found to help diagnose mismatches.
    """
    data: dict = {"status": status}
    now = datetime.utcnow().isoformat()

    if status == "running":
        data["started_at"] = now
        data["last_heartbeat"] = now
    elif status in ("completed", "failed", "timed_out"):
        data["completed_at"] = now

    if rows_transferred is not None:
        data["rows_transferred"] = rows_transferred
    if error_message is not None:
        data["error_message"] = error_message
    if dcl_response is not None:
        data["dcl_response"] = json.dumps(dcl_response, default=str)

    result = sb.update("runner_jobs", data, filters={"job_id": job_id})

    if not result:
        from ..logger import get_logger
        _log = get_logger("db.runner_jobs")
        _log.warning(
            "No runner job found for job_id=%s when updating to status=%s. "
            "This may indicate a job_id mismatch between create and update calls.",
            job_id, status
        )

    return len(result) > 0


def update_heartbeat(job_id: str) -> bool:
    """Update last_heartbeat timestamp for a running job."""
    now = datetime.utcnow().isoformat()
    result = sb.update("runner_jobs", {"last_heartbeat": now}, filters={"job_id": job_id})
    return len(result) > 0


def get_runner_job(job_id: str) -> Optional[dict]:
    """Get a runner job by ID, parsing manifest and dcl_response JSON."""
    row = sb.select("runner_jobs", filters={"job_id": job_id}, single=True)
    if not row:
        return None
    if row.get("manifest") and isinstance(row["manifest"], str):
        row["manifest"] = json.loads(row["manifest"])
    if row.get("dcl_response") and isinstance(row["dcl_response"], str):
        row["dcl_response"] = json.loads(row["dcl_response"])
    return row


def get_runner_jobs_batch(job_ids: list[str]) -> dict[str, dict]:
    """Bulk-fetch runner jobs by ID in a single query. Returns {job_id: job_dict}.

    Replaces N serial get_runner_job() calls with one WHERE job_id = ANY(%s)
    query. At ~75ms/roundtrip to Supabase PG, fetching 57 jobs serially costs
    ~4-5s; this batch query costs ~75ms total.
    """
    if not job_ids:
        return {}
    from psycopg2 import sql as psql

    query = psql.SQL("SELECT * FROM {} WHERE job_id = ANY(%s)").format(
        sb._ident("runner_jobs")
    )
    rows = sb._execute_composed(query, (job_ids,))

    result = {}
    for row in rows:
        if row.get("manifest") and isinstance(row["manifest"], str):
            row["manifest"] = json.loads(row["manifest"])
        if row.get("dcl_response") and isinstance(row["dcl_response"], str):
            row["dcl_response"] = json.loads(row["dcl_response"])
        result[row["job_id"]] = row
    return result


def get_runner_progress(aod_run_id: str = None) -> dict:
    """Get aggregate progress counts for runner jobs, optionally scoped to a run.

    When *aod_run_id* is provided, only jobs linked to that AOD discovery run
    are counted — preventing stale data from previous dispatches from inflating
    the summary.
    """
    from psycopg2 import sql as psql
    from . import supabase_client as sb2

    if aod_run_id:
        query = psql.SQL(
            "SELECT status, COUNT(*) as cnt, "
            "MIN(dispatched_at) as earliest, MAX(completed_at) as latest, "
            "SUM(COALESCE(rows_transferred, 0)) as total_rows "
            "FROM {} WHERE aod_run_id = %s GROUP BY status ORDER BY status"
        ).format(sb2._ident("runner_jobs"))
        rows = sb2._execute_composed(query, [aod_run_id])
    else:
        query = psql.SQL(
            "SELECT status, COUNT(*) as cnt, "
            "MIN(dispatched_at) as earliest, MAX(completed_at) as latest, "
            "SUM(COALESCE(rows_transferred, 0)) as total_rows "
            "FROM {} GROUP BY status ORDER BY status"
        ).format(sb2._ident("runner_jobs"))
        rows = sb2._execute_composed(query)

    by_status = {}
    total = 0
    total_rows = 0
    earliest = None
    latest = None
    for r in rows:
        s = r["status"]
        c = int(r["cnt"])
        by_status[s] = c
        total += c
        total_rows += int(r["total_rows"] or 0)
        e = r.get("earliest")
        l = r.get("latest")
        if e and (earliest is None or str(e) < str(earliest)):
            earliest = str(e)
        if l and (latest is None or str(l) > str(latest)):
            latest = str(l)

    done = by_status.get("completed", 0) + by_status.get("failed", 0) + by_status.get("timed_out", 0)
    pct = round(done / total * 100, 1) if total else 0

    return {
        "total_jobs": total,
        "by_status": by_status,
        "done": done,
        "remaining": total - done,
        "percent_complete": pct,
        "total_rows_transferred": total_rows,
        "earliest_dispatch": earliest,
        "latest_completion": latest,
    }


def cancel_queued_jobs() -> int:
    """Cancel all queued jobs by setting status to 'cancelled'. Returns count cancelled."""
    from psycopg2 import sql as psql
    from . import supabase_client as sb2

    query = psql.SQL(
        "UPDATE {} SET status = 'cancelled', completed_at = NOW(), "
        "error_message = 'Cancelled by operator' "
        "WHERE status IN ('queued', 'dispatched', 'running') RETURNING job_id"
    ).format(sb2._ident("runner_jobs"))

    try:
        rows = sb2._execute_composed(query)
        return len(rows)
    except Exception as exc:
        raise RuntimeError(f"Failed to cancel queued jobs: {exc}") from exc


def list_runner_jobs(
    pipe_id: Optional[str] = None,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List runner jobs with optional filters, including source_system extracted from manifest."""
    from psycopg2 import sql as psql

    conditions = []
    params: list = []
    if pipe_id:
        conditions.append("pipe_id = %s")
        params.append(pipe_id)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if run_id:
        conditions.append("run_id = %s")
        params.append(run_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    query = psql.SQL(
        "SELECT job_id, pipe_id, run_id, status, dispatched_at, started_at, completed_at, "
        "rows_transferred, error_message, last_heartbeat, dcl_response, "
        "manifest::json->'source'->>'system' AS source_system, "
        "manifest::json->>'snapshot_name' AS snapshot_name "
        "FROM {} " + where + " ORDER BY dispatched_at DESC NULLS LAST LIMIT %s"
    ).format(sb._ident("runner_jobs"))
    rows = sb._execute_composed(query, tuple(params) if params else None)
    return rows


def increment_retry_count(job_id: str) -> int:
    """Atomically increment retry_count and return the new value.

    Uses COALESCE to handle rows where retry_count is NULL (pre-migration).
    """
    from psycopg2 import sql as psql

    query = psql.SQL(
        "UPDATE {} SET retry_count = COALESCE(retry_count, 0) + 1 "
        "WHERE job_id = %s RETURNING retry_count"
    ).format(sb._ident("runner_jobs"))

    rows = sb._execute_composed(query, (job_id,))
    if rows:
        return int(rows[0]["retry_count"])

    from ..logger import get_logger
    get_logger("db.runner_jobs").warning(
        "increment_retry_count: no row found for job_id=%s", job_id
    )
    return 0
