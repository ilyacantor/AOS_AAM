"""WP12b: data access for the `fabric_webhook_log` table.

One row per inbound webhook (or manual-entry submission). Two-phase write:

  1. _log_receipt(...)      — insert row at the start of the handler with the
                              signature-verification result. Returns id.
  2. _finalize_receipt(id)  — update the row with the push outcome at the end
                              of the handler (success or failure). Always
                              runs, even when the handler raises.

Drill-down query joins on aam_inference_id to semantic_triples (triples
written for the batch) and resolver_hitl_queue (resolver decisions).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from psycopg2 import sql as psql

from . import supabase_client as sb

_log = logging.getLogger("aam.db.fabric_webhook_log")


def log_receipt(
    *,
    vendor: str,
    event_type: Optional[str],
    payload_bytes: int,
    signature_verified: bool,
    signature_truncated: Optional[str],
    payload: Optional[dict[str, Any]] = None,
    source: str = "webhook",
) -> str:
    """Insert a fresh receipt row. Returns the row id (UUID string)."""
    payload_str = json.dumps(payload) if payload is not None else None
    rows = sb._execute_composed(
        psql.SQL(
            "INSERT INTO fabric_webhook_log "
            "(vendor, event_type, payload_bytes, signature_verified, "
            " signature_truncated, payload_jsonb, source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
        ),
        params=(vendor, event_type, payload_bytes, signature_verified,
                signature_truncated, payload_str, source),
        fetch=True,
    )
    return str(rows[0]["id"])


def finalize_receipt(
    receipt_id: str,
    *,
    aam_inference_id: Optional[str] = None,
    dcl_ingest_id: Optional[str] = None,
    rows_seen: Optional[int] = None,
    triples_built: Optional[int] = None,
    triples_pushed: Optional[int] = None,
    push_status_code: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    sb._execute_composed(
        psql.SQL(
            "UPDATE fabric_webhook_log SET "
            "finalized_utc = now(), "
            "aam_inference_id = %s, "
            "dcl_ingest_id = %s, "
            "rows_seen = %s, "
            "triples_built = %s, "
            "triples_pushed = %s, "
            "push_status_code = %s, "
            "error = %s "
            "WHERE id = %s"
        ),
        params=(aam_inference_id, dcl_ingest_id, rows_seen, triples_built,
                triples_pushed, push_status_code, error, receipt_id),
        fetch=False,
    )


def list_recent(
    *, vendor: Optional[str] = None, limit: int = 50,
) -> list[dict[str, Any]]:
    """Most recent receipts, newest first. Excludes payload_jsonb to keep
    the list lightweight; drill-down endpoint returns the full payload."""
    if vendor:
        rows = sb._execute_composed(
            psql.SQL(
                "SELECT id, received_utc, finalized_utc, vendor, event_type, "
                "payload_bytes, signature_verified, signature_truncated, "
                "aam_inference_id, dcl_ingest_id, rows_seen, triples_built, "
                "triples_pushed, push_status_code, error, source "
                "FROM fabric_webhook_log WHERE vendor = %s "
                "ORDER BY received_utc DESC LIMIT %s"
            ),
            params=(vendor, limit),
            fetch=True,
        )
    else:
        rows = sb._execute_composed(
            psql.SQL(
                "SELECT id, received_utc, finalized_utc, vendor, event_type, "
                "payload_bytes, signature_verified, signature_truncated, "
                "aam_inference_id, dcl_ingest_id, rows_seen, triples_built, "
                "triples_pushed, push_status_code, error, source "
                "FROM fabric_webhook_log "
                "ORDER BY received_utc DESC LIMIT %s"
            ),
            params=(limit,),
            fetch=True,
        )
    return [_serialize(r) for r in rows]


def get_one(receipt_id: str) -> Optional[dict[str, Any]]:
    rows = sb._execute_composed(
        psql.SQL("SELECT * FROM fabric_webhook_log WHERE id = %s"),
        params=(receipt_id,),
        fetch=True,
    )
    return _serialize(rows[0]) if rows else None


def aggregate_counts(
    *, vendor: Optional[str] = None, window_hours: int = 24,
) -> dict[str, Any]:
    """Aggregate counts for the per-vendor card. Returns {received, verified,
    push_succeeded, triples_pushed_total, errors}."""
    where = "received_utc >= now() - (%s || ' hours')::interval"
    params: tuple[Any, ...] = (str(window_hours),)
    if vendor:
        where += " AND vendor = %s"
        params = params + (vendor,)
    rows = sb._execute_composed(
        psql.SQL(
            "SELECT "
            "COUNT(*) AS received, "
            "COUNT(*) FILTER (WHERE signature_verified) AS verified, "
            "COUNT(*) FILTER (WHERE push_status_code BETWEEN 200 AND 299) AS push_succeeded, "
            "COALESCE(SUM(triples_pushed), 0) AS triples_pushed_total, "
            "COUNT(*) FILTER (WHERE error IS NOT NULL) AS errors "
            f"FROM fabric_webhook_log WHERE {where}"
        ),
        params=params,
        fetch=True,
    )
    if not rows:
        return {"received": 0, "verified": 0, "push_succeeded": 0,
                "triples_pushed_total": 0, "errors": 0}
    return {k: int(v or 0) for k, v in rows[0].items()}


def fetch_drill_companions(
    *, dcl_ingest_id: str,
) -> dict[str, Any]:
    """Pull the per-batch summary AND sample triples from DCL via HTTP.

    AAM and DCL run against different Supabase projects in production, so a
    direct SQL join from AAM into semantic_triples is wrong even when both
    schemas have the table. Use DCL's HTTP read endpoints — those are the
    authoritative read paths for batch state.

    Returns:
      ingest_status: full DCL response dict (triple_count, concept_summary,
                     created_at, is_active) or {error: "..."} on failure.
      triples: list of up to 50 triples for this dcl_ingest_id with all 5
               provenance fields (source_system, source_field, pipe_id,
               fabric_plane, confidence_score). Empty list on no-match or
               on error; the error explanation surfaces via ingest_status.
    """
    import os
    import httpx
    base = (os.environ.get("DCL_URL") or "").rstrip("/")
    if not base:
        return {
            "ingest_status": {"error": "DCL_URL not set; cannot fetch DCL state"},
            "triples": [],
        }

    status_url = f"{base}/api/dcl/ingest-status/{dcl_ingest_id}"
    triples_url = f"{base}/api/dcl/triples/browse?run_id={dcl_ingest_id}&limit=50"
    status: dict[str, Any]
    triples: list[dict[str, Any]] = []

    try:
        with httpx.Client(timeout=5.0) as client:
            sr = client.get(status_url)
            if sr.status_code == 404:
                status = {"error": f"DCL has no record of dcl_ingest_id={dcl_ingest_id}"}
            elif sr.status_code >= 400:
                status = {"error": f"DCL HTTP {sr.status_code}: {sr.text[:200]}"}
            else:
                status = sr.json()
            tr = client.get(triples_url)
            if tr.status_code < 400:
                triples = (tr.json() or {}).get("triples", [])
    except httpx.HTTPError as exc:
        return {
            "ingest_status": {"error": f"DCL unreachable: {exc}"},
            "triples": [],
        }
    return {"ingest_status": status, "triples": triples}


def fetch_hitl_for_receipt(
    *,
    tenant_id: str,
    entity_id: str,
    received_utc: str,
    window_seconds: int = 60,
) -> list[dict[str, Any]]:
    """Return resolver_hitl_queue rows created near this webhook's receipt timestamp.

    AAM and DCL share no schema for resolver/HITL — this reads AAM's local
    SQLite HITL store. The receipt and the HITL entries don't share a join
    key today, so we approximate by tenant_id + entity_id + a small time
    window around received_utc. Acceptable for drill-down operator UX; not
    suitable for cross-tenant aggregation.
    """
    from datetime import datetime, timedelta
    from .. import db as _db_pkg  # noqa: F401
    from ..db.hitl_store import list_all
    try:
        all_rows = list_all(tenant_id=tenant_id, limit=200)
    except Exception as exc:  # noqa: BLE001 — surface, don't swallow
        _log.warning("HITL lookup failed for receipt: %s", exc)
        return []
    def _to_naive_utc(s: str) -> datetime | None:
        """Parse an ISO timestamp into a naive UTC datetime — both the Postgres
        offset-aware receipt timestamps and SQLite naive HITL timestamps end
        up on the same comparable scale."""
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is not None:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    anchor = _to_naive_utc(received_utc)
    if anchor is None:
        return all_rows  # cannot window — return everything for this tenant
    lo = anchor - timedelta(seconds=window_seconds)
    hi = anchor + timedelta(seconds=window_seconds)
    out: list[dict[str, Any]] = []
    for r in all_rows:
        if r.get("entity_id") != entity_id:
            continue
        created = r.get("created_at")
        if not created:
            continue
        ts = _to_naive_utc(str(created))
        if ts is None:
            continue
        if lo <= ts <= hi:
            out.append(r)
    return out


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """Convert non-JSON-native types to JSON-safe primitives."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "hex") and not isinstance(v, (bytes, str)):
            # UUID
            out[k] = str(v)
        else:
            out[k] = v
    return out
