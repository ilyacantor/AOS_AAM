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
        # Migration 2026-03-03: Store AOD reconciliation manifest in handoff log
        ("ALTER TABLE aod_handoff_log ADD COLUMN IF NOT EXISTS reconciliation_manifest TEXT", "add_reconciliation_manifest_column"),
        # Migration 2026-03-27: Add tenant_id and entity_id to handoff log
        ("ALTER TABLE aod_handoff_log ADD COLUMN IF NOT EXISTS tenant_id TEXT", "add_handoff_tenant_id_column"),
        ("ALTER TABLE aod_handoff_log ADD COLUMN IF NOT EXISTS entity_id TEXT", "add_handoff_entity_id_column"),
        # Migration 2026-05-15 (WP12b): per-receipt observability for fabric webhook receivers.
        # Canonical SQL recorded at migrations/add_fabric_webhook_log.sql.
        (
            "CREATE TABLE IF NOT EXISTS fabric_webhook_log ("
            "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
            "received_utc TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "finalized_utc TIMESTAMPTZ, "
            "vendor VARCHAR(32) NOT NULL, "
            "event_type VARCHAR(128), "
            "payload_bytes INTEGER NOT NULL, "
            "signature_verified BOOLEAN NOT NULL, "
            "signature_truncated VARCHAR(24), "
            "aam_inference_id UUID, "
            "dcl_ingest_id UUID, "
            "rows_seen INTEGER, "
            "triples_built INTEGER, "
            "triples_pushed INTEGER, "
            "push_status_code INTEGER, "
            "error TEXT, "
            "payload_jsonb JSONB, "
            "source VARCHAR(16) NOT NULL DEFAULT 'webhook' CHECK (source IN ('webhook','manual'))"
            ")",
            "create_fabric_webhook_log_table",
        ),
        ("CREATE INDEX IF NOT EXISTS idx_fabric_webhook_log_received ON fabric_webhook_log (received_utc DESC)",
         "idx_fabric_webhook_log_received"),
        ("CREATE INDEX IF NOT EXISTS idx_fabric_webhook_log_vendor_received ON fabric_webhook_log (vendor, received_utc DESC)",
         "idx_fabric_webhook_log_vendor_received"),
        ("CREATE INDEX IF NOT EXISTS idx_fabric_webhook_log_aam_inference ON fabric_webhook_log (aam_inference_id) WHERE aam_inference_id IS NOT NULL",
         "idx_fabric_webhook_log_aam_inference"),
        # Migration 2026-05-16 (DISP #24): persistent canonical registry.
        # Replaces the in-memory CanonicalRegistry in app/ingest/resolver.py so
        # resolver decisions survive AAM restart, memory is bounded to the
        # current webhook batch's snapshot, and discovery is race-safe via
        # ON CONFLICT.
        (
            "CREATE TABLE IF NOT EXISTS canonical_registry ("
            "canonical_id UUID NOT NULL, "
            "tenant_id TEXT NOT NULL, "
            "domain TEXT NOT NULL, "
            "normalized_value TEXT NOT NULL, "
            "original_value TEXT NOT NULL, "
            "aliases_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "PRIMARY KEY (tenant_id, domain, normalized_value)"
            ")",
            "create_canonical_registry_table",
        ),
        ("CREATE INDEX IF NOT EXISTS idx_canonical_registry_canonical_id ON canonical_registry (canonical_id)",
         "idx_canonical_registry_canonical_id"),
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
