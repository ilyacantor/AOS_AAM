"""Tests for GET /maestra/status endpoint.

Tests seed real data through the handoff service and runner_jobs DB layer,
then query the endpoint via FastAPI TestClient. No mocks, no backdoors.
"""
import json
import time
from datetime import datetime

from fastapi.testclient import TestClient


def _seed_handoff(db, run_id: str, snapshot_name: str, candidates: list[dict]):
    """Seed a handoff log and candidates for a tenant."""
    from app.models import AODHandoffRequest
    from app.services.handoff_service import process_handoff

    request = AODHandoffRequest(
        run_id=run_id,
        snapshot_name=snapshot_name,
        handoff_timestamp=datetime.utcnow(),
        candidates=candidates,
    )
    return process_handoff(request)


def _candidate(asset_key, vendor, display, category, aod_asset_id, run_id, execution_allowed=True):
    return {
        "asset_key": asset_key,
        "vendor_name": vendor,
        "display_name": display,
        "category": category,
        "aod_asset_id": aod_asset_id,
        "aod_run_id": run_id,
        "execution_allowed": execution_allowed,
        "action_type": "provision",
    }


def _seed_runner_jobs(run_id: str, statuses: list[tuple[str, str]]):
    """Seed runner_jobs with given (pipe_id, status) pairs linked to run_id."""
    from app.db import supabase_client as sb

    now = datetime.utcnow().isoformat()
    rows = []
    for pipe_id, status in statuses:
        completed = now if status in ("completed", "failed", "timed_out") else None
        manifest = json.dumps({"source": {"pipe_id": pipe_id}, "run_id": run_id})
        rows.append({
            "job_id": pipe_id,
            "pipe_id": pipe_id,
            "run_id": run_id,
            "status": status,
            "manifest": manifest,
            "dispatched_at": now,
            "started_at": now if status != "queued" else None,
            "completed_at": completed,
            "last_heartbeat": None,
            "rows_transferred": 10 if status == "completed" else 0,
            "error_message": "timeout" if status == "timed_out" else None,
            "dcl_response": None,
            "retry_count": 0,
            "retry_after": None,
        })
    if rows:
        sb.insert_many("runner_jobs", rows, on_conflict="job_id")


def _seed_declared_pipe(pipe_id: str, source_system: str):
    """Seed a declared_pipe."""
    from app.db import supabase_client as sb

    now = datetime.utcnow().isoformat()
    sb.insert("declared_pipes", {
        "pipe_id": pipe_id,
        "display_name": f"Pipe for {source_system}",
        "fabric_plane": "API_GATEWAY",
        "modality": "DECLARED_INTERFACE",
        "source_system": source_system,
        "transport_kind": "API",
        "provenance": json.dumps({"discovered_by": "test"}),
        "created_at": now,
        "updated_at": now,
    }, on_conflict="pipe_id")


def _cleanup_tables():
    """Remove test data from all relevant tables."""
    from app.db import supabase_client as sb
    for table in ("runner_jobs", "connection_candidates", "declared_pipes",
                   "aod_handoff_log", "drift_events"):
        try:
            sb.delete(table, delete_all=True)
        except Exception:
            pass


def _get_client():
    from app.main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_maestra_status_returns_200(db):
    """GET /maestra/status with a valid tenant_id returns 200."""
    _cleanup_tables()
    run_id = "maestra-test-run-001"
    _seed_handoff(db, run_id, "test-tenant", [
        _candidate("sf.com", "Salesforce", "Salesforce", "crm", "a1", run_id),
    ])

    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "test-tenant"})
    assert resp.status_code == 200


def test_maestra_status_valid_json_schema(db):
    """Response matches the Maestra contract schema — all required fields present."""
    _cleanup_tables()
    run_id = "maestra-schema-run"
    _seed_handoff(db, run_id, "schema-tenant", [
        _candidate("sf.com", "Salesforce", "Salesforce", "crm", "a1", run_id),
    ])

    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "schema-tenant"})
    data = resp.json()

    assert data["module"] == "aam"
    assert data["tenant_id"] == "schema-tenant"
    assert isinstance(data["manifests"], dict)
    assert all(k in data["manifests"] for k in ("total", "succeeded", "failed", "pending"))
    assert isinstance(data["sso_pending"], dict)
    assert "count" in data["sso_pending"]
    assert "items" in data["sso_pending"]
    assert isinstance(data["connections"], list)
    assert "last_execution_at" in data
    assert isinstance(data["healthy"], bool)


def test_maestra_status_module_field(db):
    """The module field must be 'aam'."""
    _cleanup_tables()
    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "any-tenant"})
    assert resp.json()["module"] == "aam"


def test_maestra_status_healthy_is_boolean(db):
    """The healthy field must be a boolean."""
    _cleanup_tables()
    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "any-tenant"})
    assert isinstance(resp.json()["healthy"], bool)


def test_maestra_status_tenant_id_matches_request(db):
    """The tenant_id in the response must match what was requested."""
    _cleanup_tables()
    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "my-tenant-123"})
    assert resp.json()["tenant_id"] == "my-tenant-123"


def test_maestra_status_response_time(db):
    """Response time must be under 500ms."""
    _cleanup_tables()
    client = _get_client()
    start = time.monotonic()
    resp = client.get("/maestra/status", params={"tenant_id": "perf-tenant"})
    elapsed_ms = (time.monotonic() - start) * 1000
    assert resp.status_code == 200
    assert elapsed_ms < 500, f"Response took {elapsed_ms:.0f}ms (limit: 500ms)"


def test_maestra_status_manifest_counts(db):
    """Manifest counts reflect actual runner_jobs state."""
    _cleanup_tables()
    run_id = "maestra-counts-run"
    _seed_handoff(db, run_id, "counts-tenant", [
        _candidate("sf.com", "Salesforce", "Salesforce", "crm", "a1", run_id),
    ])
    _seed_runner_jobs(run_id, [
        ("pipe-1", "completed"),
        ("pipe-2", "completed"),
        ("pipe-3", "failed"),
        ("pipe-4", "queued"),
        ("pipe-5", "running"),
    ])

    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "counts-tenant"})
    m = resp.json()["manifests"]

    assert m["total"] == 5
    assert m["succeeded"] == 2
    assert m["failed"] == 1
    assert m["pending"] == 2


def test_maestra_status_sso_pending(db):
    """SSO pending reflects candidates with execution_allowed=false."""
    _cleanup_tables()
    run_id = "maestra-sso-run"
    _seed_handoff(db, run_id, "sso-tenant", [
        _candidate("sf.com", "Salesforce", "Salesforce", "crm", "a1", run_id, execution_allowed=True),
        _candidate("okta.com", "Okta", "Okta IdP", "identity", "a2", run_id, execution_allowed=False),
        _candidate("duo.com", "Duo", "Duo MFA", "identity", "a3", run_id, execution_allowed=False),
    ])

    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "sso-tenant"})
    sso = resp.json()["sso_pending"]

    assert sso["count"] == 2
    assert len(sso["items"]) == 2
    vendors = {item["vendor"] for item in sso["items"]}
    assert "Okta" in vendors
    assert "Duo" in vendors


def test_maestra_status_connections(db):
    """Connections lists declared pipes linked to tenant's candidates."""
    _cleanup_tables()
    run_id = "maestra-conn-run"
    _seed_handoff(db, run_id, "conn-tenant", [
        _candidate("sf.com", "Salesforce", "Salesforce", "crm", "a1", run_id),
    ])
    _seed_declared_pipe("pipe-sf-001", "Salesforce")

    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "conn-tenant"})
    conns = resp.json()["connections"]

    assert len(conns) == 1
    assert conns[0]["pipe_id"] == "pipe-sf-001"
    assert conns[0]["source_system"] == "Salesforce"


def test_maestra_status_last_execution_at(db):
    """last_execution_at reflects the latest completed runner job."""
    _cleanup_tables()
    run_id = "maestra-exec-run"
    _seed_handoff(db, run_id, "exec-tenant", [
        _candidate("sf.com", "Salesforce", "Salesforce", "crm", "a1", run_id),
    ])
    _seed_runner_jobs(run_id, [("pipe-done", "completed")])

    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "exec-tenant"})
    assert resp.json()["last_execution_at"] is not None


def test_maestra_status_healthy_true_when_no_failures(db):
    """Healthy is true when all jobs succeeded and no drift."""
    _cleanup_tables()
    run_id = "maestra-healthy-run"
    _seed_handoff(db, run_id, "healthy-tenant", [
        _candidate("sf.com", "Salesforce", "Salesforce", "crm", "a1", run_id),
    ])
    _seed_runner_jobs(run_id, [
        ("pipe-ok-1", "completed"),
        ("pipe-ok-2", "completed"),
    ])

    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "healthy-tenant"})
    assert resp.json()["healthy"] is True


def test_maestra_status_healthy_false_when_failures(db):
    """Healthy is false when there are failed jobs."""
    _cleanup_tables()
    run_id = "maestra-unhealthy-run"
    _seed_handoff(db, run_id, "unhealthy-tenant", [
        _candidate("sf.com", "Salesforce", "Salesforce", "crm", "a1", run_id),
    ])
    _seed_runner_jobs(run_id, [
        ("pipe-ok", "completed"),
        ("pipe-bad", "failed"),
    ])

    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "unhealthy-tenant"})
    assert resp.json()["healthy"] is False


def test_maestra_status_unknown_tenant_returns_empty(db):
    """An unknown tenant returns zeroed-out response, not an error."""
    _cleanup_tables()
    client = _get_client()
    resp = client.get("/maestra/status", params={"tenant_id": "nonexistent-tenant"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["manifests"]["total"] == 0
    assert data["sso_pending"]["count"] == 0
    assert data["connections"] == []
    assert data["last_execution_at"] is None
    assert data["healthy"] is True


def test_maestra_status_requires_tenant_id(db):
    """Missing tenant_id query param returns 422."""
    client = _get_client()
    resp = client.get("/maestra/status")
    assert resp.status_code == 422


def test_maestra_status_tenant_isolation(db):
    """Data from one tenant does not leak into another tenant's response."""
    _cleanup_tables()

    # Seed directly via DB to avoid process_handoff clearing state between tenants.
    from app.db import supabase_client as sb

    run_a = "iso-run-a"
    run_b = "iso-run-b"
    now = datetime.utcnow().isoformat()

    sb.insert_many("aod_handoff_log", [
        {"handoff_id": "h-a", "aod_run_id": run_a, "snapshot_name": "tenant-a",
         "candidates_received": 1, "candidates_accepted": 1, "candidates_rejected": 0,
         "handoff_timestamp": now, "processed_at": now},
        {"handoff_id": "h-b", "aod_run_id": run_b, "snapshot_name": "tenant-b",
         "candidates_received": 1, "candidates_accepted": 1, "candidates_rejected": 0,
         "handoff_timestamp": now, "processed_at": now},
    ])
    sb.insert_many("connection_candidates", [
        {"candidate_id": "c-a", "asset_key": "sf.com", "vendor_name": "Salesforce",
         "display_name": "Salesforce", "category": "crm", "aod_run_id": run_a,
         "execution_allowed": True, "action_type": "provision",
         "created_at": now, "updated_at": now},
        {"candidate_id": "c-b", "asset_key": "sap.com", "vendor_name": "SAP",
         "display_name": "SAP ERP", "category": "erp", "aod_run_id": run_b,
         "execution_allowed": True, "action_type": "provision",
         "created_at": now, "updated_at": now},
    ])
    _seed_runner_jobs(run_a, [("pipe-a", "completed")])
    _seed_runner_jobs(run_b, [("pipe-b", "failed")])

    client = _get_client()

    resp_a = client.get("/maestra/status", params={"tenant_id": "tenant-a"})
    data_a = resp_a.json()
    assert data_a["manifests"]["succeeded"] == 1
    assert data_a["manifests"]["failed"] == 0
    assert data_a["healthy"] is True

    resp_b = client.get("/maestra/status", params={"tenant_id": "tenant-b"})
    data_b = resp_b.json()
    assert data_b["manifests"]["succeeded"] == 0
    assert data_b["manifests"]["failed"] == 1
    assert data_b["healthy"] is False
