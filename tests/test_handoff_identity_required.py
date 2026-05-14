"""WP1: identity pair (tenant_id + entity_id) is required at POST /api/handoff/aod/receive.

Operator-visible outcome: when AOD posts a handoff with tenant_id or entity_id missing,
AAM responds HTTP 422 at the receive endpoint, the response body names the missing field
in plain English, and no row is created in aod_handoff_log.

This is a backend integration test (not Playwright) — handoff is machine-to-machine,
no UI. B17's "UI-driven only" clause applies to user-facing features.
"""
from fastapi.testclient import TestClient


def _client():
    from app.main import app as fastapi_app
    return TestClient(fastapi_app, raise_server_exceptions=False)


def _list_handoff_rows(aod_discovery_id: str):
    """Return rows from aod_handoff_log matching the given aod_run_id."""
    from app.db import supabase_client as sb
    return sb.select("aod_handoff_log", filters={"aod_run_id": aod_discovery_id})


def _candidate(asset_key, vendor, run_id):
    return {
        "asset_key": asset_key,
        "vendor_name": vendor,
        "display_name": f"{vendor} App",
        "category": "crm",
        "aod_asset_id": f"asset-{asset_key}",
        "aod_run_id": run_id,
        "execution_allowed": True,
        "action_type": "provision",
    }


def test_handoff_rejects_missing_tenant_id(db):
    """Missing tenant_id -> 422, error body names the field, no aod_handoff_log row."""
    run_id = "wp1-reject-missing-tenant-id"
    with _client() as client:
        resp = client.post("/api/handoff/aod/receive", json={
            "aod_discovery_id": run_id,
            "entity_id": "wp1-entity",
            "candidates": [_candidate("salesforce.com", "Salesforce", run_id)],
        })

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "detail" in body, f"Response missing 'detail': {body}"
    # Pydantic error shape: each error has loc pointing to the missing field
    error_locs = [".".join(str(p) for p in err.get("loc", [])) for err in body["detail"]]
    assert "tenant_id" in error_locs, (
        f"422 body does not name 'tenant_id' as the missing field. "
        f"Got locs: {error_locs}"
    )
    # And the msg names "Field required" in plain English
    tenant_errs = [err for err in body["detail"] if err.get("loc") == ["tenant_id"]]
    assert tenant_errs, f"No error entry for tenant_id: {body['detail']}"
    assert "required" in tenant_errs[0].get("msg", "").lower(), (
        f"tenant_id error msg not in plain English: {tenant_errs[0]}"
    )

    # No row in aod_handoff_log
    rows = _list_handoff_rows(run_id)
    assert len(rows) == 0, (
        f"Expected 0 aod_handoff_log rows for rejected handoff {run_id!r}, got {len(rows)}: {rows}"
    )


def test_handoff_rejects_missing_entity_id(db):
    """Missing entity_id -> 422, error body names the field, no aod_handoff_log row."""
    run_id = "wp1-reject-missing-entity-id"
    import uuid
    with _client() as client:
        resp = client.post("/api/handoff/aod/receive", json={
            "aod_discovery_id": run_id,
            "tenant_id": str(uuid.uuid4()),
            "candidates": [_candidate("salesforce.com", "Salesforce", run_id)],
        })

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "detail" in body, f"Response missing 'detail': {body}"
    error_locs = [".".join(str(p) for p in err.get("loc", [])) for err in body["detail"]]
    assert "entity_id" in error_locs, (
        f"422 body does not name 'entity_id' as the missing field. "
        f"Got locs: {error_locs}"
    )
    entity_errs = [err for err in body["detail"] if err.get("loc") == ["entity_id"]]
    assert entity_errs, f"No error entry for entity_id: {body['detail']}"
    assert "required" in entity_errs[0].get("msg", "").lower(), (
        f"entity_id error msg not in plain English: {entity_errs[0]}"
    )

    rows = _list_handoff_rows(run_id)
    assert len(rows) == 0, (
        f"Expected 0 aod_handoff_log rows for rejected handoff {run_id!r}, got {len(rows)}: {rows}"
    )


def test_handoff_rejects_missing_both_identity_fields(db):
    """Missing tenant_id AND entity_id -> 422, both named, no row."""
    run_id = "wp1-reject-missing-both"
    with _client() as client:
        resp = client.post("/api/handoff/aod/receive", json={
            "aod_discovery_id": run_id,
            "candidates": [_candidate("salesforce.com", "Salesforce", run_id)],
        })

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "detail" in body, f"Response missing 'detail': {body}"
    error_locs = [".".join(str(p) for p in err.get("loc", [])) for err in body["detail"]]
    assert "tenant_id" in error_locs, f"422 missing tenant_id loc: {error_locs}"
    assert "entity_id" in error_locs, f"422 missing entity_id loc: {error_locs}"

    rows = _list_handoff_rows(run_id)
    assert len(rows) == 0, (
        f"Expected 0 aod_handoff_log rows for rejected handoff {run_id!r}, got {len(rows)}: {rows}"
    )
