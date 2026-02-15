"""
Runner Jobs — tracks the lifecycle of each dispatched runner job.

State machine: queued → dispatched → running → pushing → completed / failed / timed_out
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def create_runner_job(manifest_dict: dict) -> str:
    """Create a new runner job from a manifest dict. Returns job_id (= run_id)."""
    job_id = manifest_dict["run_id"]
    now = datetime.utcnow().isoformat()

    sb.insert("runner_jobs", {
        "job_id": job_id,
        "pipe_id": manifest_dict["source"]["pipe_id"],
        "status": "queued",
        "manifest": json.dumps(manifest_dict, default=str),
        "dispatched_at": now,
        "rows_transferred": 0,
    })
    return job_id


def create_runner_jobs_batch(manifests: list[dict]) -> list[str]:
    """Bulk-insert runner jobs from a list of manifest dicts. Returns list of job_ids."""
    if not manifests:
        return []
    now = datetime.utcnow().isoformat()
    rows = []
    for m in manifests:
        rows.append({
            "job_id": m["run_id"],
            "pipe_id": m["source"]["pipe_id"],
            "status": "queued",
            "manifest": json.dumps(m, default=str),
            "dispatched_at": now,
            "rows_transferred": 0,
        })
    sb.insert_many("runner_jobs", rows)
    return [m["run_id"] for m in manifests]


def update_runner_status(
    job_id: str,
    status: str,
    *,
    rows_transferred: Optional[int] = None,
    error_message: Optional[str] = None,
    dcl_response: Optional[dict] = None,
) -> bool:
    """Update runner job status and optional fields."""
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


def get_runner_progress() -> dict:
    """Get aggregate progress counts for all runner jobs.
    Returns counts by status, plus timing info for the current batch."""
    from psycopg2 import sql as psql
    from . import supabase_client as sb2

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


def list_runner_jobs(
    pipe_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List runner jobs with optional filters."""
    filters = {}
    if pipe_id:
        filters["pipe_id"] = pipe_id
    if status:
        filters["status"] = status

    kwargs: dict = {"order": "dispatched_at.desc", "limit": limit}
    if filters:
        kwargs["filters"] = filters

    rows = sb.select(
        "runner_jobs",
        columns="job_id,pipe_id,status,dispatched_at,started_at,completed_at,rows_transferred,error_message,last_heartbeat",
        **kwargs,
    )
    return rows
