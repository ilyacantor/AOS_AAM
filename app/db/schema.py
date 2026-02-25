"""
Schema initialization and migrations.

Ensures required tables exist in Supabase and seeds the mock collector.
"""
import os
from datetime import datetime


def _ensure_tables():
    """Run CREATE TABLE IF NOT EXISTS for tables that may not exist yet."""
    from ..logger import get_logger
    from . import supabase_client as sb
    _log = get_logger("db.schema")

    sql_path = os.path.join(os.path.dirname(__file__), "create_tables.sql")
    if not os.path.exists(sql_path):
        return

    with open(sql_path) as f:
        sql_content = f.read()

    statements = [s.strip() for s in sql_content.split(";") if s.strip()]
    for stmt in statements:
        if not stmt.upper().startswith("CREATE TABLE"):
            continue
        try:
            sb._execute_composed(
                __import__("psycopg2").sql.SQL(stmt),
                fetch=False,
            )
        except Exception as e:
            if "already exists" not in str(e):
                _log.warning("DDL skipped: %s", str(e)[:100])


def _run_migrations():
    """Run pending migrations that are idempotent (safe to run multiple times)."""
    from ..logger import get_logger
    from . import supabase_client as sb
    from psycopg2 import sql as psql
    _log = get_logger("db.migrations")

    migrations = [
        # Migration 2026-02-23: Add run_id column for batch grouping
        ("ALTER TABLE runner_jobs ADD COLUMN IF NOT EXISTS run_id VARCHAR", "add_run_id_column"),
        ("CREATE INDEX IF NOT EXISTS idx_runner_jobs_run_id ON runner_jobs(run_id)", "add_run_id_index"),
        # Migration 2026-02-24: Add indexes for status queries and dispatch ordering
        ("CREATE INDEX IF NOT EXISTS idx_runner_jobs_status ON runner_jobs(status)", "add_status_index"),
        ("CREATE INDEX IF NOT EXISTS idx_runner_jobs_dispatched_at ON runner_jobs(dispatched_at DESC NULLS LAST)", "add_dispatched_at_index"),
        # Migration 2026-02-24: Add retry_count for transient Farm error retry tracking
        ("ALTER TABLE runner_jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0", "add_retry_count_column"),
        # Migration 2026-02-24: Add retry_after for backoff between transient retries
        ("ALTER TABLE runner_jobs ADD COLUMN IF NOT EXISTS retry_after TEXT", "add_retry_after_column"),
        # Migration 2026-02-25: Track every DCL export attempt (success + failure) for diagnostics
        (
            "CREATE TABLE IF NOT EXISTS dcl_export_attempts ("
            "attempt_id TEXT PRIMARY KEY, "
            "aod_run_id TEXT, "
            "pipe_count INTEGER DEFAULT 0, "
            "dcl_ok BOOLEAN DEFAULT FALSE, "
            "dcl_status INTEGER, "
            "dcl_body TEXT, "
            "dcl_error TEXT, "
            "created_at TEXT NOT NULL"
            ")",
            "create_dcl_export_attempts_table",
        ),
    ]

    for sql_stmt, migration_name in migrations:
        try:
            sb._execute_composed(psql.SQL(sql_stmt), fetch=False)
            _log.info("Migration applied: %s", migration_name)
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                _log.debug("Migration already applied: %s", migration_name)
            else:
                _log.warning("Migration failed (%s): %s", migration_name, str(e)[:200])


def init_db():
    """Initialize database schema and run migrations"""
    from ..logger import get_logger
    _log = get_logger("db")
    try:
        _ensure_tables()
        _run_migrations()
        from . import supabase_client as sb
        sb.insert("collectors", {
            "collector_id": "mock-collector-001",
            "name": "Mock Collector",
            "collector_type": "mock",
            "description": "Generates sample observations from JSON for testing",
            "created_at": datetime.utcnow().isoformat()
        }, on_conflict="collector_id")
        _log.info("Database initialized (Supabase)")
    except Exception as e:
        _log.warning("init_db: %s", e)
