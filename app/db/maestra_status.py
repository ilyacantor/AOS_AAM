"""
Maestra status queries — aggregate AAM state for a given tenant.

Tenant scoping: tenant_id maps to aod_handoff_log.snapshot_name.
All queries are scoped through the aod_run_ids linked to that snapshot.
"""
from typing import Optional

from psycopg2 import sql as psql

from . import supabase_client as sb
from ..logger import get_logger

_log = get_logger("db.maestra_status")


def get_maestra_status(tenant_id: str) -> dict:
    """Return structured AAM status for a tenant.

    Queries runner_jobs, connection_candidates, declared_pipes, and
    drift_events scoped to the aod_run_ids associated with the given
    tenant_id (= aod_handoff_log.snapshot_name).
    """
    aod_run_ids = _get_aod_run_ids_for_tenant(tenant_id)

    if not aod_run_ids:
        return {
            "module": "aam",
            "tenant_id": tenant_id,
            "manifests": {"total": 0, "succeeded": 0, "failed": 0, "pending": 0},
            "sso_pending": {"count": 0, "items": []},
            "connections": [],
            "last_execution_at": None,
            "healthy": True,
        }

    manifests = _get_manifest_counts(aod_run_ids)
    sso_pending = _get_sso_pending(aod_run_ids)
    connections = _get_connections(aod_run_ids)
    last_execution_at = _get_last_execution_at(aod_run_ids)

    has_failures = manifests["failed"] > 0
    has_open_drift = _has_open_drift_events(aod_run_ids)
    healthy = not has_failures and not has_open_drift

    return {
        "module": "aam",
        "tenant_id": tenant_id,
        "manifests": manifests,
        "sso_pending": sso_pending,
        "connections": connections,
        "last_execution_at": last_execution_at,
        "healthy": healthy,
    }


def _get_aod_run_ids_for_tenant(tenant_id: str) -> list[str]:
    """Find all aod_run_ids where snapshot_name matches tenant_id."""
    query = psql.SQL(
        "SELECT DISTINCT {aod_run_id} FROM {table} WHERE {snapshot_name} = %s"
    ).format(
        aod_run_id=sb._ident("aod_run_id"),
        table=sb._ident("aod_handoff_log"),
        snapshot_name=sb._ident("snapshot_name"),
    )
    rows = sb._execute_composed(query, (tenant_id,))
    return [r["aod_run_id"] for r in rows if r.get("aod_run_id")]


def _get_manifest_counts(aod_run_ids: list[str]) -> dict:
    """Aggregate runner_jobs by status for the given run_ids.

    Maps job statuses to the Maestra contract:
    - succeeded: completed
    - failed: failed + timed_out
    - pending: queued + dispatched + running + pushing
    """
    query = psql.SQL(
        "SELECT {status}, COUNT(*) AS cnt "
        "FROM {table} WHERE {run_id} = ANY(%s) "
        "GROUP BY {status}"
    ).format(
        status=sb._ident("status"),
        table=sb._ident("runner_jobs"),
        run_id=sb._ident("run_id"),
    )
    rows = sb._execute_composed(query, (aod_run_ids,))

    counts = {}
    for r in rows:
        counts[r["status"]] = int(r["cnt"])

    succeeded = counts.get("completed", 0)
    failed = counts.get("failed", 0) + counts.get("timed_out", 0)
    pending = (
        counts.get("queued", 0)
        + counts.get("dispatched", 0)
        + counts.get("running", 0)
        + counts.get("pushing", 0)
    )
    total = sum(counts.values())

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "pending": pending,
    }


def _get_sso_pending(aod_run_ids: list[str]) -> dict:
    """Return candidates with execution_allowed=false for the given run_ids.

    These represent connections blocked on auth/SSO configuration.
    Returns {count, items} where items contains vendor_name + asset_key.
    """
    query = psql.SQL(
        "SELECT {vendor_name}, {asset_key} FROM {table} "
        "WHERE {aod_run_id} = ANY(%s) AND {execution_allowed} = FALSE"
    ).format(
        vendor_name=sb._ident("vendor_name"),
        asset_key=sb._ident("asset_key"),
        table=sb._ident("connection_candidates"),
        aod_run_id=sb._ident("aod_run_id"),
        execution_allowed=sb._ident("execution_allowed"),
    )
    rows = sb._execute_composed(query, (aod_run_ids,))
    items = [{"vendor": r["vendor_name"], "asset_key": r["asset_key"]} for r in rows]
    return {"count": len(items), "items": items}


def _get_connections(aod_run_ids: list[str]) -> list[dict]:
    """Return declared pipes linked to this tenant's candidates.

    Joins declared_pipes with connection_candidates on vendor_name/source_system
    to find pipes that belong to the tenant's discovered assets.
    """
    query = psql.SQL(
        "SELECT DISTINCT dp.{pipe_id}, dp.{source_system}, dp.{fabric_plane}, "
        "dp.{modality}, dp.{transport_kind} "
        "FROM {pipes} dp "
        "INNER JOIN {candidates} cc "
        "  ON LOWER(dp.{source_system}) = LOWER(cc.{vendor_name}) "
        "WHERE cc.{aod_run_id} = ANY(%s)"
    ).format(
        pipe_id=sb._ident("pipe_id"),
        source_system=sb._ident("source_system"),
        fabric_plane=sb._ident("fabric_plane"),
        modality=sb._ident("modality"),
        transport_kind=sb._ident("transport_kind"),
        pipes=sb._ident("declared_pipes"),
        candidates=sb._ident("connection_candidates"),
        vendor_name=sb._ident("vendor_name"),
        aod_run_id=sb._ident("aod_run_id"),
    )
    rows = sb._execute_composed(query, (aod_run_ids,))
    return [
        {
            "pipe_id": r["pipe_id"],
            "source_system": r["source_system"],
            "fabric_plane": r["fabric_plane"],
            "modality": r["modality"],
            "transport_kind": r["transport_kind"],
        }
        for r in rows
    ]


def _get_last_execution_at(aod_run_ids: list[str]) -> Optional[str]:
    """Get the most recent completed_at timestamp from runner_jobs for these runs."""
    query = psql.SQL(
        "SELECT MAX({completed_at}) AS last_at FROM {table} "
        "WHERE {run_id} = ANY(%s) AND {completed_at} IS NOT NULL"
    ).format(
        completed_at=sb._ident("completed_at"),
        table=sb._ident("runner_jobs"),
        run_id=sb._ident("run_id"),
    )
    rows = sb._execute_composed(query, (aod_run_ids,))
    if rows and rows[0].get("last_at"):
        return str(rows[0]["last_at"])
    return None


def _has_open_drift_events(aod_run_ids: list[str]) -> bool:
    """Check for open drift events on pipes belonging to this tenant's candidates."""
    query = psql.SQL(
        "SELECT EXISTS ("
        "  SELECT 1 FROM {drift} de "
        "  INNER JOIN {candidates} cc "
        "    ON de.{pipe_id} = cc.{matched_pipe_id} "
        "  WHERE cc.{aod_run_id} = ANY(%s) AND de.{status} = 'open'"
        ") AS has_drift"
    ).format(
        drift=sb._ident("drift_events"),
        candidates=sb._ident("connection_candidates"),
        pipe_id=sb._ident("pipe_id"),
        matched_pipe_id=sb._ident("matched_pipe_id"),
        aod_run_id=sb._ident("aod_run_id"),
        status=sb._ident("status"),
    )
    rows = sb._execute_composed(query, (aod_run_ids,))
    return rows[0]["has_drift"] if rows else False
