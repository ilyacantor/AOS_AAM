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

    Also invalidates the canonical_registry per-process snapshot cache
    between tests so the PG-backed registry doesn't return stale data
    from a previous test's tenant_id (DISP #24).
    """
    db_path = str(tmp_path / "test_aam.db")
    monkeypatch.setenv("AAM_DATABASE_URL", db_path)
    # Re-create settings so the value takes effect
    from app.config import Settings
    s = Settings()
    monkeypatch.setattr("app.config.settings", s)
    # Snapshot cache reset — cheap and avoids cross-test leakage.
    try:
        from app.db.canonical_registry import _SNAPSHOTS as _registry_snapshots
        _registry_snapshots.clear()
    except Exception:
        pass


@pytest.fixture
def db():
    """Initialise the database and return the module.

    NOTE: supabase_client connects to the real Supabase instance.
    Test cleanup is scoped to known test IDs — never delete_all=True.
    Individual test files handle their own scoped cleanup.
    """
    import app.db as db_mod
    db_mod.init_db()
    return db_mod


@pytest.fixture
def run_id(db, monkeypatch):
    """Provide a real run_id with test data routed through TestClient.

    Seeds an AOD handoff (candidates + planes + SORs) so that every harness
    test has data to work with, and monkey-patches test_harness.api() to route
    through FastAPI TestClient — no external server needed.
    """
    import uuid as _uuid
    from datetime import datetime as _dt
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.models import AODHandoffRequest, FabricPlaneSummary, SORDeclaration
    from app.services.handoff_service import process_handoff
    from app.db.ledger import init_ledger_db

    init_ledger_db()

    aod_run_id = f"harness-{_uuid.uuid4().hex[:8]}"
    request = AODHandoffRequest(
        aod_discovery_id=aod_run_id,
        tenant_id=str(_uuid.uuid4()),
        entity_id="harness-entity",
        snapshot_name="harness-entity",
        handoff_timestamp=_dt.utcnow(),
        candidates=[
            {"asset_key": "salesforce.com", "vendor_name": "Salesforce",
             "display_name": "Salesforce CRM", "category": "crm",
             "aod_asset_id": "sf-1", "aod_run_id": aod_run_id,
             "execution_allowed": True, "action_type": "provision"},
            {"asset_key": "workday.com", "vendor_name": "Workday",
             "display_name": "Workday HCM", "category": "hcm",
             "aod_asset_id": "wd-1", "aod_run_id": aod_run_id,
             "execution_allowed": True, "action_type": "provision"},
            {"asset_key": "netsuite.com", "vendor_name": "NetSuite",
             "display_name": "NetSuite ERP", "category": "erp",
             "aod_asset_id": "ns-1", "aod_run_id": aod_run_id,
             "execution_allowed": True, "action_type": "provision"},
            {"asset_key": "servicenow.com", "vendor_name": "ServiceNow",
             "display_name": "ServiceNow ITSM", "category": "itsm",
             "aod_asset_id": "sn-1", "aod_run_id": aod_run_id,
             "execution_allowed": True, "action_type": "provision"},
        ],
        fabric_planes=[
            FabricPlaneSummary(plane_type="API_GATEWAY", vendor="kong",
                               is_healthy=True),
            FabricPlaneSummary(plane_type="IPAAS", vendor="mulesoft",
                               is_healthy=True),
        ],
        sors=[
            SORDeclaration(domain="CRM", vendor="Salesforce",
                           category="crm", confidence="high", source="farm"),
            SORDeclaration(domain="ERP", vendor="NetSuite",
                           category="erp", confidence="high", source="farm"),
        ],
    )
    process_handoff(request)

    with TestClient(fastapi_app, raise_server_exceptions=False) as client:
        import tests.test_harness as harness_mod

        def _patched_api(method, path, **kwargs):
            kwargs.pop("timeout", None)
            return getattr(client, method)(path, **kwargs)

        monkeypatch.setattr(harness_mod, "api", _patched_api)
        yield aod_run_id
