"""Tests for AOD->AAM handoff service — idempotency and error classification."""
from datetime import datetime


def _candidate(asset_key, vendor, display, category, aod_asset_id, run_id):
    """Helper to build a candidate dict with all required fields."""
    return {
        "asset_key": asset_key,
        "vendor_name": vendor,
        "display_name": display,
        "category": category,
        "aod_asset_id": aod_asset_id,
        "aod_run_id": run_id,
        "execution_allowed": True,
        "action_type": "provision",
    }


def test_handoff_basic_flow(db):
    """A minimal handoff should create candidates and a handoff log."""
    from app.models import AODHandoffRequest
    from app.services.handoff_service import process_handoff

    run_id = "test-run-001"
    request = AODHandoffRequest(
        run_id=run_id,
        snapshot_name="test-snapshot",
        handoff_timestamp=datetime.utcnow(),
        candidates=[
            _candidate("salesforce.com", "Salesforce", "Salesforce CRM", "crm", "asset-1", run_id),
            _candidate("workday.com", "Workday", "Workday HCM", "hcm", "asset-2", run_id),
        ],
    )

    result = process_handoff(request)

    assert result.run_id == run_id
    assert result.candidates_received == 2
    assert result.candidates_accepted == 2
    assert result.candidates_rejected == 0
    assert result.handoff_id is not None

    candidates = db.list_candidates()
    assert len(candidates) == 2


def test_handoff_idempotency(db):
    """Submitting the same run_id twice returns cached result, not duplicates."""
    from app.models import AODHandoffRequest
    from app.services.handoff_service import process_handoff

    run_id = "idempotent-run-001"
    request = AODHandoffRequest(
        run_id=run_id,
        snapshot_name="snap",
        handoff_timestamp=datetime.utcnow(),
        candidates=[
            _candidate("slack.com", "Slack", "Slack", "collaboration", "a1", run_id),
        ],
    )

    result1 = process_handoff(request)
    assert result1.candidates_accepted == 1

    # Submit again — should return cached result
    result2 = process_handoff(request)
    assert result2.candidates_accepted == 1
    assert result2.handoff_id == result1.handoff_id  # Same handoff

    # Only 1 candidate should exist (not 2)
    candidates = db.list_candidates()
    assert len(candidates) == 1


def test_handoff_creates_fabric_planes_for_sors(db):
    """SOR candidates auto-create fabric planes during handoff."""
    from app.models import AODHandoffRequest
    from app.services.handoff_service import process_handoff

    run_id = "sor-run-001"
    request = AODHandoffRequest(
        run_id=run_id,
        snapshot_name="sor-snap",
        handoff_timestamp=datetime.utcnow(),
        candidates=[
            _candidate("servicenow.com", "ServiceNow", "ServiceNow ITSM", "itsm", "sn1", run_id),
        ],
    )

    result = process_handoff(request)
    assert result.candidates_accepted == 1

    from app.db import get_fabric_planes
    planes = get_fabric_planes()
    assert len(planes) >= 1
    plane_vendors = [p["vendor"] for p in planes]
    assert "ServiceNow" in plane_vendors
