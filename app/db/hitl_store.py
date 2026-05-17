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
  - status in {'pending','approved','rejected','auto_applied'}.

WS-2: status='auto_applied' rows record resolver matches at confidence
>= auto_threshold (0.90). These are NOT operator-actionable (no approve/
reject buttons) — the resolver already applied them. They surface in
/ui/candidates Recent Matches so operators can audit auto-applied
matches with confidence + source pointers + timestamp + match rule,
per deck Slide 8.
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
    extra_json TEXT,
    -- DISP #24 follow-up — dedup_key collapses (tenant, domain, normalized
    -- left, normalized right, status) into one column so SQLite can enforce
    -- a unique index. The non-idempotent INSERT path caused 10× duplicate
    -- pending rows across 5 B6 runs; this column makes re-insert a no-op.
    -- _dedup_key() is the canonical builder. Populated on every insert,
    -- NULL for legacy rows pre-migration.
    dedup_key TEXT
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
    # DISP #24 follow-up — partial unique index on dedup_key for non-null
    # rows. Makes INSERT OR IGNORE a no-op when the (tenant, domain,
    # normalized left, normalized right, status) tuple already exists.
    # Partial WHERE clause keeps legacy NULL-dedup rows unaffected.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_hitl_dedup ON resolver_hitl_queue(dedup_key) WHERE dedup_key IS NOT NULL",
]


# Same normalization as the resolver — collapses whitespace + common
# punctuation, lowercases, strips. Kept in-module to avoid a circular
# import from app.ingest.resolver. If the resolver's normalization changes,
# update both call sites.
import re as _re
_NORM_SEP = _re.compile(r"[\s\-_./,;:]+")


def _normalize(s: str) -> str:
    return _NORM_SEP.sub(" ", str(s).lower()).strip()


def _dedup_key(*, tenant_id: str, domain: str, left_value: str,
               right_value: str, status: str) -> str:
    """Canonical dedup key for a HITL row. Two inserts with the same key
    converge to one row regardless of pipe_id / record_key / confidence /
    proposed_canonical_id (those are write-time noise — the dedup
    semantics are the operator-visible pair + status)."""
    return "|".join([
        tenant_id, domain.lower(), _normalize(left_value),
        _normalize(right_value), status,
    ])


def _get_db() -> sqlite3.Connection:
    db_path = os.path.abspath(_DB_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_hitl_db() -> None:
    """Create the HITL tables if they don't exist. Idempotent.

    Also runs an idempotent column-add migration for the dedup_key column
    (added 2026-05-17 per DISP #24 follow-up). Existing rows keep their
    NULL dedup_key (legacy bypass of the unique index); new inserts
    populate the column.
    """
    conn = _get_db()
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_AUDIT_SQL)
        # Idempotent migration: ALTER TABLE ADD COLUMN if missing.
        cols = {row["name"] for row in conn.execute(
            "PRAGMA table_info(resolver_hitl_queue)"
        ).fetchall()}
        if "dedup_key" not in cols:
            conn.execute("ALTER TABLE resolver_hitl_queue ADD COLUMN dedup_key TEXT")
            _log.info("Migration applied: added dedup_key column to resolver_hitl_queue")
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
    # DISP #24 follow-up: idempotent insert. Same (tenant, domain,
    # normalized left, normalized right, status='pending') → return the
    # existing hitl_queue_id instead of inserting a duplicate. Pre-fix,
    # 5 B6 runs produced 9140 pending rows for 912 distinct pairs (~10×
    # duplication); this rewrite makes re-insert a no-op.
    dedup = _dedup_key(
        tenant_id=tenant_id, domain=domain, left_value=left_value,
        right_value=right_value, status="pending",
    )

    conn = _get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO resolver_hitl_queue "
            "(hitl_queue_id, tenant_id, entity_id, domain, "
            " left_pipe_id, left_record_key, left_value, "
            " right_pipe_id, right_record_key, right_value, "
            " confidence, status, proposed_canonical_id, "
            " decided_by, decided_at, audit_id, created_at, extra_json, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, ?, ?, ?, ?)",
            (
                hitl_queue_id, tenant_id, entity_id, domain,
                left_pipe_id, left_record_key, left_value,
                right_pipe_id, right_record_key, right_value,
                confidence, proposed_canonical_id, audit_id, now, extra_json, dedup,
            ),
        )
        if cur.rowcount == 0:
            # Dedup conflict — fetch the existing row's hitl_queue_id and
            # return it. The caller's audit trail still records that the
            # resolver saw this pair (audit row created below), but the
            # queue itself stays single-row per pair.
            existing = conn.execute(
                "SELECT hitl_queue_id, audit_id FROM resolver_hitl_queue "
                "WHERE dedup_key=?",
                (dedup,),
            ).fetchone()
            if existing is None:
                # Race: INSERT was ignored but row vanished. SQLite shouldn't
                # do this — raise loudly per A1.
                raise RuntimeError(
                    f"insert_pending: INSERT OR IGNORE returned 0 rows AND "
                    f"no row found for dedup_key={dedup!r} — DB inconsistency"
                )
            existing_qid = existing["hitl_queue_id"]
            existing_audit_id = existing["audit_id"]
            # Append a 'reseen' audit event so the audit trail shows the
            # resolver re-encountered this pair (operator-visible if they
            # check audit history). No new queue row, just an audit entry.
            conn.execute(
                "INSERT INTO resolver_hitl_audit "
                "(audit_id, hitl_queue_id, event, details, actor, occurred_at) "
                "VALUES (?, ?, 'reseen', ?, ?, ?)",
                (str(uuid.uuid4()), existing_qid,
                 json.dumps({"confidence": confidence, "domain": domain,
                             "dedup_collapsed_into": existing_qid}),
                 "resolver", now),
            )
            conn.commit()
            return existing_qid
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


def insert_auto_applied(
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
    canonical_id: str,
    match_rule: str,
    extra: Optional[dict] = None,
) -> str:
    """Insert an auto-applied resolver match (status='auto_applied').

    Auto-applied = resolver confidence >= auto_threshold (0.90) per
    Slide 6 thresholds. Not operator-actionable; surfaces in
    /ui/candidates Recent Matches for auditability (Slide 8).

    The proposed_canonical_id column is repurposed for the canonical_id
    the resolver bound (since the match is already applied, "proposed"
    is now "applied"). match_rule is the resolver_method that produced
    the match (e.g., "fuzzy", "exact"); stored in audit details + the
    extra_json column under key 'match_rule' for query-time access.

    Raises ValueError on missing required fields — no silent fallback.
    """
    if not tenant_id or not entity_id or not domain:
        raise ValueError(
            f"insert_auto_applied: tenant_id, entity_id, domain required "
            f"(got tenant_id={tenant_id!r} entity_id={entity_id!r} domain={domain!r})"
        )
    if not left_value or not right_value:
        raise ValueError(
            f"insert_auto_applied: left_value and right_value required "
            f"(got left={left_value!r} right={right_value!r})"
        )
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"insert_auto_applied: confidence must be in [0, 1] (got {confidence})")
    if not canonical_id:
        raise ValueError("insert_auto_applied: canonical_id required")
    if not match_rule:
        raise ValueError("insert_auto_applied: match_rule required")

    enriched = dict(extra or {})
    enriched["match_rule"] = match_rule
    hitl_queue_id = str(uuid.uuid4())
    audit_id = str(uuid.uuid4())
    now = _now()
    extra_json = json.dumps(enriched)
    # DISP #24 follow-up: idempotent insert (same shape as insert_pending).
    dedup = _dedup_key(
        tenant_id=tenant_id, domain=domain, left_value=left_value,
        right_value=right_value, status="auto_applied",
    )

    conn = _get_db()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO resolver_hitl_queue "
            "(hitl_queue_id, tenant_id, entity_id, domain, "
            " left_pipe_id, left_record_key, left_value, "
            " right_pipe_id, right_record_key, right_value, "
            " confidence, status, proposed_canonical_id, "
            " decided_by, decided_at, audit_id, created_at, extra_json, dedup_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'auto_applied', ?, 'resolver', ?, ?, ?, ?, ?)",
            (
                hitl_queue_id, tenant_id, entity_id, domain,
                left_pipe_id, left_record_key, left_value,
                right_pipe_id, right_record_key, right_value,
                confidence, canonical_id, now, audit_id, now, extra_json, dedup,
            ),
        )
        if cur.rowcount == 0:
            existing = conn.execute(
                "SELECT hitl_queue_id FROM resolver_hitl_queue WHERE dedup_key=?",
                (dedup,),
            ).fetchone()
            if existing is None:
                raise RuntimeError(
                    f"insert_auto_applied: INSERT OR IGNORE returned 0 rows AND "
                    f"no row found for dedup_key={dedup!r} — DB inconsistency"
                )
            existing_qid = existing["hitl_queue_id"]
            conn.execute(
                "INSERT INTO resolver_hitl_audit "
                "(audit_id, hitl_queue_id, event, details, actor, occurred_at) "
                "VALUES (?, ?, 'reseen', ?, ?, ?)",
                (str(uuid.uuid4()), existing_qid,
                 json.dumps({"confidence": confidence, "domain": domain,
                             "match_rule": match_rule, "canonical_id": canonical_id,
                             "dedup_collapsed_into": existing_qid}),
                 "resolver", now),
            )
            conn.commit()
            return existing_qid
        conn.execute(
            "INSERT INTO resolver_hitl_audit (audit_id, hitl_queue_id, event, details, actor, occurred_at) "
            "VALUES (?, ?, 'auto_applied', ?, ?, ?)",
            (audit_id, hitl_queue_id,
             json.dumps({"confidence": confidence, "domain": domain,
                         "match_rule": match_rule, "canonical_id": canonical_id}),
             "resolver", now),
        )
        conn.commit()
        return hitl_queue_id
    finally:
        conn.close()


def list_auto_applied(
    *,
    tenant_id: str,
    domain: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Auto-applied resolver matches (status='auto_applied'), newest first.

    Used by /api/aam/resolver/auto-matches + /ui/candidates Recent
    Matches surface (Slide 8 operator-visible auto-apply audit).
    """
    if not tenant_id:
        raise ValueError("list_auto_applied: tenant_id required")
    conn = _get_db()
    try:
        sql = ("SELECT * FROM resolver_hitl_queue "
               "WHERE tenant_id=? AND status='auto_applied'")
        params: list = [tenant_id]
        if domain:
            sql += " AND domain=?"
            params.append(domain)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
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
