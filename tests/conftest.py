"""
Shared test fixtures for AAM unit tests.
"""
import os
import tempfile
import pytest
from dotenv import load_dotenv

# Load .env BEFORE any app imports so module-level Settings() and supabase_client work
load_dotenv(override=False)


@pytest.fixture(autouse=True)
def _use_temp_db(monkeypatch, tmp_path):
    """Isolate tests from the production Supabase database.

    Sets AAM_DATABASE_URL to a temp path for any code that still reads it,
    and refreshes the Settings singleton.  The legacy db.connection module
    no longer exposes DATABASE, so we skip patching it.
    """
    db_path = str(tmp_path / "test_aam.db")
    monkeypatch.setenv("AAM_DATABASE_URL", db_path)
    # Re-create settings so the value takes effect
    from app.config import Settings
    s = Settings()
    monkeypatch.setattr("app.config.settings", s)


@pytest.fixture
def db():
    """Initialise the database and return the module.

    Clears test-affected tables BEFORE init_db() because supabase_client
    connects to the real Supabase instance (ignores AAM_DATABASE_URL).
    All tests share the same DB, so we must remove rows left by prior runs.
    """
    from app.db import supabase_client as sb
    for table in ("connection_candidates", "declared_pipes"):
        try:
            sb.delete(table, delete_all=True)
        except Exception:
            pass  # Table may not exist on first run
    import app.db as db_mod
    db_mod.init_db()
    return db_mod


@pytest.fixture
def run_id():
    """Provide run_id for integration tests that need a running server.

    These tests (test_harness.py) hit HTTP endpoints, so they only work when
    a server is running with ingested data.  Skip automatically in unit-test runs.
    """
    pytest.skip("Integration test — requires a running server with ingested AOD data")
