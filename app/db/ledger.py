"""
Triple Write Ledger — SQLite-backed ledger for AAM triple write operations.

Tracks every batch of triples written to PG: pending → committed/failed.
AAM-local (SQLite), NOT in the DCL triple store.

Forward compat: when the flow controller lands, it calls the same
ledger write function with write_path='flow_controller' and a pipe_id.
"""
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Optional

_log = logging.getLogger("aam.db.ledger")

_DB_PATH = os.environ.get("AAM_LEDGER_DB_PATH", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "aam_ledger.db"
))

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS triple_write_ledger (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    trigger TEXT NOT NULL,
    write_path TEXT NOT NULL,
    concept_prefixes TEXT,
    triple_count INTEGER,
    status TEXT NOT NULL,
    error_detail TEXT,
    pipe_id TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
)
"""

_CREATE_IDX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_ledger_run_id ON triple_write_ledger(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_ledger_entity_id ON triple_write_ledger(entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_ledger_status ON triple_write_ledger(status)",
    "CREATE INDEX IF NOT EXISTS idx_ledger_created ON triple_write_ledger(created_at DESC)",
]


def _get_db() -> sqlite3.Connection:
    """Get a SQLite connection to the ledger database."""
    db_path = os.path.abspath(_DB_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_ledger_db() -> None:
    """Create the ledger table if it doesn't exist."""
    conn = _get_db()
    try:
        conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _CREATE_IDX_SQL:
            conn.execute(idx_sql)
        conn.commit()
        _log.info("Triple write ledger initialized (SQLite)")
    finally:
        conn.close()


def create_pending_entry(
    run_id: str,
    entity_id: str,
    trigger: str,
    write_path: str = "direct_execute",
    concept_prefixes: Optional[list[str]] = None,
    pipe_id: Optional[str] = None,
) -> str:
    """Create a pending ledger entry before a PG write. Returns the entry id."""
    entry_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO triple_write_ledger "
            "(id, run_id, entity_id, trigger, write_path, concept_prefixes, "
            "triple_count, status, error_detail, pipe_id, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id, run_id, entity_id, trigger, write_path,
                json.dumps(concept_prefixes) if concept_prefixes else None,
                None, "pending", None, pipe_id, None, now,
            ),
        )
        conn.commit()
        return entry_id
    finally:
        conn.close()


def mark_committed(
    entry_id: str,
    triple_count: int,
    duration_ms: int,
    concept_prefixes: Optional[list[str]] = None,
) -> None:
    """Update a ledger entry to committed status."""
    conn = _get_db()
    try:
        update_sql = (
            "UPDATE triple_write_ledger SET status='committed', "
            "triple_count=?, duration_ms=?"
        )
        params: list = [triple_count, duration_ms]
        if concept_prefixes is not None:
            update_sql += ", concept_prefixes=?"
            params.append(json.dumps(concept_prefixes))
        update_sql += " WHERE id=?"
        params.append(entry_id)
        conn.execute(update_sql, params)
        conn.commit()
    finally:
        conn.close()


def mark_failed(entry_id: str, error_detail: str, duration_ms: int) -> None:
    """Update a ledger entry to failed status."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE triple_write_ledger SET status='failed', "
            "error_detail=?, duration_ms=? WHERE id=?",
            (error_detail, duration_ms, entry_id),
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict with parsed JSON fields."""
    d = dict(row)
    if d.get("concept_prefixes"):
        try:
            d["concept_prefixes"] = json.loads(d["concept_prefixes"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def list_entries(
    entity_id: Optional[str] = None,
    trigger: Optional[str] = None,
    write_path: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List recent ledger entries with optional filters."""
    conn = _get_db()
    try:
        sql = "SELECT * FROM triple_write_ledger WHERE 1=1"
        params: list = []
        if entity_id:
            sql += " AND entity_id=?"
            params.append(entity_id)
        if trigger:
            sql += " AND trigger=?"
            params.append(trigger)
        if write_path:
            sql += " AND write_path=?"
            params.append(write_path)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_entries_for_run(run_id: str) -> list[dict]:
    """Get all ledger entries for a specific run."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM triple_write_ledger WHERE run_id=? ORDER BY created_at DESC",
            (run_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_summary() -> dict:
    """Aggregated summary: total triples, counts by prefix, write_path, failure rate."""
    conn = _get_db()
    try:
        # Total triples committed
        row = conn.execute(
            "SELECT COALESCE(SUM(triple_count), 0) as total FROM triple_write_ledger "
            "WHERE status='committed'"
        ).fetchone()
        total_triples = row["total"] if row else 0

        # Counts by write_path
        write_path_rows = conn.execute(
            "SELECT write_path, COUNT(*) as cnt, COALESCE(SUM(triple_count), 0) as triples "
            "FROM triple_write_ledger WHERE status='committed' GROUP BY write_path"
        ).fetchall()
        by_write_path = {r["write_path"]: {"entries": r["cnt"], "triples": r["triples"]}
                         for r in write_path_rows}

        # Counts by concept prefix (flatten JSON arrays)
        all_entries = conn.execute(
            "SELECT concept_prefixes FROM triple_write_ledger WHERE status='committed' "
            "AND concept_prefixes IS NOT NULL"
        ).fetchall()
        prefix_counts: dict[str, int] = {}
        for entry in all_entries:
            try:
                prefixes = json.loads(entry["concept_prefixes"])
                if isinstance(prefixes, list):
                    for p in prefixes:
                        prefix_counts[p] = prefix_counts.get(p, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

        # Latest timestamp
        latest_row = conn.execute(
            "SELECT created_at FROM triple_write_ledger ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        latest_timestamp = latest_row["created_at"] if latest_row else None

        # Failure rate (last 24h)
        total_24h = conn.execute(
            "SELECT COUNT(*) as cnt FROM triple_write_ledger "
            "WHERE created_at > datetime('now', '-24 hours')"
        ).fetchone()
        failed_24h = conn.execute(
            "SELECT COUNT(*) as cnt FROM triple_write_ledger "
            "WHERE status='failed' AND created_at > datetime('now', '-24 hours')"
        ).fetchone()
        total_count_24h = total_24h["cnt"] if total_24h else 0
        failed_count_24h = failed_24h["cnt"] if failed_24h else 0
        failure_rate = round(failed_count_24h / total_count_24h, 4) if total_count_24h > 0 else 0.0

        return {
            "total_triples": total_triples,
            "by_concept_prefix": prefix_counts,
            "by_write_path": by_write_path,
            "latest_timestamp": latest_timestamp,
            "failure_rate_24h": failure_rate,
            "total_entries_24h": total_count_24h,
            "failed_entries_24h": failed_count_24h,
        }
    finally:
        conn.close()
