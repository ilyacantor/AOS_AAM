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


def init_db():
    """Initialize database schema"""
    from ..logger import get_logger
    _log = get_logger("db")
    try:
        _ensure_tables()
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
