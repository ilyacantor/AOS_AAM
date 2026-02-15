"""
Schema initialization and migrations.

Tables are created in Supabase SQL Editor. This module only ensures
the mock collector seed row exists.
"""
from datetime import datetime


def init_db():
    """Initialize database schema"""
    from ..logger import get_logger
    _log = get_logger("db")
    try:
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
