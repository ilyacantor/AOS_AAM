"""
Shared test fixtures for AAM unit tests.
"""
import os
import tempfile
import pytest


@pytest.fixture(autouse=True)
def _use_temp_db(monkeypatch, tmp_path):
    """Point every test at a fresh temporary SQLite file."""
    db_path = str(tmp_path / "test_aam.db")
    monkeypatch.setenv("AAM_DATABASE_URL", db_path)
    # Re-create settings so the value takes effect
    from app.config import Settings
    s = Settings()
    monkeypatch.setattr("app.config.settings", s)
    # Patch the module-level DATABASE in db.connection (the canonical location)
    import app.db.connection as db_conn
    monkeypatch.setattr(db_conn, "DATABASE", db_path)


@pytest.fixture
def db():
    """Initialise the database and return the module."""
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
