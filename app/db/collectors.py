"""
Collector operations
"""
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb


def list_collectors() -> list[dict]:
    """List all collectors"""
    rows = sb.select("collectors", order="name.asc")
    return [{
        "collector_id": row.get("collector_id"),
        "name": row.get("name"),
        "collector_type": row.get("collector_type"),
        "description": row.get("description"),
        "enabled": row.get("enabled", False),
        "last_run": row.get("last_run"),
        "created_at": row.get("created_at")
    } for row in rows]


def update_collector_last_run(collector_id: str):
    """Update collector's last run timestamp"""
    now = datetime.utcnow().isoformat()
    sb.update("collectors", {"last_run": now}, filters={"collector_id": collector_id})


def create_collector_run(collector_id: str) -> str:
    """Create a new collector run and return the run_id"""
    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    sb.insert("collector_runs", {
        "run_id": run_id,
        "collector_id": collector_id,
        "status": "running",
        "started_at": now,
    })

    return run_id


def complete_collector_run(run_id: str, status: str, observations_count: int, error_message: Optional[str] = None) -> bool:
    """Complete a collector run with final status"""
    now = datetime.utcnow().isoformat()

    result = sb.update("collector_runs", {
        "status": status,
        "completed_at": now,
        "observations_count": observations_count,
        "error_message": error_message,
    }, filters={"run_id": run_id})

    return len(result) > 0


def get_collector_run(run_id: str) -> Optional[dict]:
    """Get a collector run by ID"""
    row = sb.select("collector_runs", filters={"run_id": run_id}, single=True)

    if row:
        return {
            "run_id": row.get("run_id"),
            "collector_id": row.get("collector_id"),
            "status": row.get("status"),
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
            "observations_count": row.get("observations_count"),
            "error_message": row.get("error_message")
        }
    return None


def list_collector_runs(collector_id: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """List collector runs with optional collector filter"""
    filters = {}
    if collector_id:
        filters["collector_id"] = collector_id

    kwargs = {"order": "started_at.desc"}
    if filters:
        kwargs["filters"] = filters
    if limit:
        kwargs["limit"] = limit

    rows = sb.select("collector_runs", **kwargs)

    return [{
        "run_id": row.get("run_id"),
        "collector_id": row.get("collector_id"),
        "status": row.get("status"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "observations_count": row.get("observations_count"),
        "error_message": row.get("error_message")
    } for row in rows]
