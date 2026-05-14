"""Resolver HITL Queue — SQLite-backed store for record-level identity
resolution decisions that need human review.

AAM-local control plane (SQLite), same pattern as `app/db/ledger.py`. The
queue holds pending resolver matches in the fuzzy band [0.70, 0.90); operators
approve or reject via the resolver router. Approved rows flip the downstream
triple's `resolution_method` to `hitl_confirmed` at confidence 0.99.

Forward compat: when AAM's full WP-8 LLM-assisted mapper lands, the same
queue absorbs LLM-proposed canonical bindings without schema change — the
`proposed_canonical_id` column already exists.

Hard requirements:
  - tenant_id, entity_id, domain, left_value, right_value are NOT NULL.
  - confidence in [0.0, 1.0].
  - status in {'pending','approved','rejected'}.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

_log = logging.getLogger("aam.db.hitl_store")

_DB_PATH = os.environ.get(
    "AAM_HITL_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "aam_hitl.db"),
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS resolver_hitl_queue (
    hitl_queue_id TEXT NOT NULL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    left_pipe_id TEXT,
    left_record_key TEXT,
    left_value TEXT NOT NULL,
    right_pipe_id TEXT,
    right_record_key TEXT,
    right_value TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    proposed_canonical_id TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    audit_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    extra_json TEXT
)
"""

_CREATE_AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS resolver_hitl_audit (
    audit_id TEXT NOT NULL,
    hitl_queue_id TEXT NOT NULL,
    event TEXT NOT NULL,
    details TEXT,
    actor TEXT,
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (audit_id, occurred_at)
)
"""

_CREATE_IDX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_hitl_status ON resolver_hitl_queue(tenant_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_hitl_entity ON resolver_hitl_queue(entity_id, domain)",
    "CREATE INDEX IF NOT EXISTS idx_hitl_created ON resolver_hitl_queue(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_hitl_canonical ON resolver_hitl_queue(proposed_canonical_id)",
    "CREATE INDEX IF NOT EXISTS idx_hitl_audit_qid ON resolver_hitl_audit(hitl_queue_id)",
]


def _get_db() -> sqlite3.Connection:
    db_path = os.path.abspath(_DB_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_hitl_db() -> None:
    """Create the HITL tables if they don't exist. Idempotent."""
    conn = _get_db()
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_AUDIT_SQL)
        for sql_idx in _CREATE_IDX_SQL:
            conn.execute(sql_idx)
        conn.commit()
        _log.info("Resolver HITL queue initialized (SQLite at %s)", _DB_PATH)
    finally:
        conn.close()


def _now() -> str:
    return datetime.utcnow().isoformat()


def insert_pending(
    *,
    tenant_id: str,
    entity_id: str,
    domain: str,
    left_pipe_id: Optional[str],
    left_record_key: Optional[str],
    left_value: str,
    right_pipe_id: Optional[str],
    right_record_key: Optional[str],
    right_value: str,
    confidence: float,
    proposed_canonical_id: str,
    extra: Optional[dict] = None,
) -> str:
    """Insert a pending HITL row. Returns the hitl_queue_id.

    Raises ValueError on missing required fields — no silent fallback.
    """
    if not tenant_id or not entity_id or not domain:
        raise ValueError(
            f"insert_pending: tenant_id, entity_id, domain required "
            f"(got tenant_id={tenant_id!r} entity_id={entity_id!r} domain={domain!r})"
        )
    if not left_value or not right_value:
        raise ValueError(
            f"insert_pending: left_value and right_value required "
            f"(got left={left_value!r} right={right_value!r})"
        )
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"insert_pending: confidence must be in [0, 1] (got {confidence})")
    if not proposed_canonical_id:
        raise ValueError("insert_pending: proposed_canonical_id required")

    hitl_queue_id = str(uuid.uuid4())
    audit_id = str(uuid.uuid4())
    now = _now()
    extra_json = json.dumps(extra) if extra else None

    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO resolver_hitl_queue "
            "(hitl_queue_id, tenant_id, entity_id, domain, "
            " left_pipe_id, left_record_key, left_value, "
            " right_pipe_id, right_record_key, right_value, "
            " confidence, status, proposed_canonical_id, "
            " decided_by, decided_at, audit_id, created_at, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, ?, ?, ?)",
            (
                hitl_queue_id, tenant_id, entity_id, domain,
                left_pipe_id, left_record_key, left_value,
                right_pipe_id, right_record_key, right_value,
                confidence, proposed_canonical_id, audit_id, now, extra_json,
            ),
        )
        conn.execute(
            "INSERT INTO resolver_hitl_audit (audit_id, hitl_queue_id, event, details, actor, occurred_at) "
            "VALUES (?, ?, 'created', ?, ?, ?)",
            (audit_id, hitl_queue_id,
             json.dumps({"confidence": confidence, "domain": domain}),
             "resolver", now),
        )
        conn.commit()
        return hitl_queue_id
    finally:
        conn.close()


def get_pending(
    *,
    tenant_id: str,
    entity_id: Optional[str] = None,
    domain: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List pending HITL rows for a tenant. Optional entity_id/domain filter."""
    if not tenant_id:
        raise ValueError("get_pending: tenant_id required")
    conn = _get_db()
    try:
        sql = "SELECT * FROM resolver_hitl_queue WHERE tenant_id=? AND status='pending'"
        params: list = [tenant_id]
        if entity_id:
            sql += " AND entity_id=?"
            params.append(entity_id)
        if domain:
            sql += " AND domain=?"
            params.append(domain)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_by_id(hitl_queue_id: str) -> Optional[dict]:
    if not hitl_queue_id:
        raise ValueError("get_by_id: hitl_queue_id required")
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM resolver_hitl_queue WHERE hitl_queue_id=?",
            (hitl_queue_id,),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def decide(
    *,
    hitl_queue_id: str,
    decision: str,
    decided_by: str,
) -> dict:
    """Update a pending row to approved/rejected and append an audit event.

    Returns the updated row.
    Raises if the row doesn't exist or isn't currently pending.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError(f"decide: decision must be 'approved' or 'rejected' (got {decision!r})")
    if not decided_by:
        raise ValueError("decide: decided_by required (audit trail)")

    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM resolver_hitl_queue WHERE hitl_queue_id=?",
            (hitl_queue_id,),
        ).fetchone()
        if not row:
            raise LookupError(f"decide: hitl_queue_id {hitl_queue_id} not found")
        if row["status"] != "pending":
            raise ValueError(
                f"decide: hitl_queue_id {hitl_queue_id} is already {row['status']}; "
                f"refusing to overwrite a finalized decision"
            )
        now = _now()
        conn.execute(
            "UPDATE resolver_hitl_queue SET status=?, decided_by=?, decided_at=? "
            "WHERE hitl_queue_id=?",
            (decision, decided_by, now, hitl_queue_id),
        )
        conn.execute(
            "INSERT INTO resolver_hitl_audit "
            "(audit_id, hitl_queue_id, event, details, actor, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row["audit_id"], hitl_queue_id, f"decided_{decision}",
             json.dumps({"prior_status": "pending"}), decided_by, now),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM resolver_hitl_queue WHERE hitl_queue_id=?",
            (hitl_queue_id,),
        ).fetchone()
        return _row_to_dict(updated)
    finally:
        conn.close()


def get_audit(hitl_queue_id: str) -> list[dict]:
    if not hitl_queue_id:
        raise ValueError("get_audit: hitl_queue_id required")
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM resolver_hitl_audit WHERE hitl_queue_id=? "
            "ORDER BY occurred_at ASC",
            (hitl_queue_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def append_audit(
    *, hitl_queue_id: str, event: str, details: Optional[dict] = None, actor: str = "system",
) -> None:
    """Append an audit row to an existing queue entry's audit_id stream."""
    row = get_by_id(hitl_queue_id)
    if not row:
        raise LookupError(f"append_audit: hitl_queue_id {hitl_queue_id} not found")
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO resolver_hitl_audit "
            "(audit_id, hitl_queue_id, event, details, actor, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row["audit_id"], hitl_queue_id, event,
             json.dumps(details or {}), actor, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def list_all(*, tenant_id: str, status: Optional[str] = None, limit: int = 200) -> list[dict]:
    """All rows for a tenant, optionally filtered by status."""
    if not tenant_id:
        raise ValueError("list_all: tenant_id required")
    conn = _get_db()
    try:
        sql = "SELECT * FROM resolver_hitl_queue WHERE tenant_id=?"
        params: list = [tenant_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def reset_for_tenant(tenant_id: str) -> int:
    """Test helper: delete every queue row + its audit entries for a tenant.

    Returns the count of queue rows removed. Used by Playwright reset endpoints.
    """
    if not tenant_id:
        raise ValueError("reset_for_tenant: tenant_id required")
    conn = _get_db()
    try:
        audit_ids = [r["audit_id"] for r in conn.execute(
            "SELECT audit_id FROM resolver_hitl_queue WHERE tenant_id=?",
            (tenant_id,),
        ).fetchall()]
        for aid in audit_ids:
            conn.execute("DELETE FROM resolver_hitl_audit WHERE audit_id=?", (aid,))
        cur = conn.execute("DELETE FROM resolver_hitl_queue WHERE tenant_id=?", (tenant_id,))
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row | None) -> dict:
    if row is None:
        return {}
    d = dict(row)
    if d.get("extra_json"):
        try:
            d["extra"] = json.loads(d["extra_json"])
        except (json.JSONDecodeError, TypeError):
            d["extra"] = {}
    return d
