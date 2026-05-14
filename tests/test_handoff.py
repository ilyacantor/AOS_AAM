"""Tests for AOD->AAM handoff service — idempotency and error classification."""
import uuid as _uuid
from datetime import datetime


def _identity():
    """Build a fresh tenant_id + entity_id pair (required per I2)."""
    return str(_uuid.uuid4()), f"test-entity-{_uuid.uuid4().hex[:8]}"


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
    tenant_id, entity_id = _identity()
    request = AODHandoffRequest(
        aod_discovery_id=run_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
        snapshot_name="test-snapshot",
        handoff_timestamp=datetime.utcnow(),
        candidates=[
            _candidate("salesforce.com", "Salesforce", "Salesforce CRM", "crm", "asset-1", run_id),
            _candidate("workday.com", "Workday", "Workday HCM", "hcm", "asset-2", run_id),
        ],
    )

    result = process_handoff(request)

    assert result.aod_discovery_id == run_id
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
    tenant_id, entity_id = _identity()
    request = AODHandoffRequest(
        aod_discovery_id=run_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
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


def test_handoff_does_not_infer_planes_from_categories(db):
    """SOR candidates do NOT auto-create fabric planes — categories aren't infrastructure."""
    from app.models import AODHandoffRequest
    from app.services.handoff_service import process_handoff

    run_id = "sor-run-001"
    tenant_id, entity_id = _identity()
    request = AODHandoffRequest(
        aod_discovery_id=run_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
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
    # No planes — ServiceNow being "itsm" doesn't create infrastructure
    assert len(planes) == 0


def test_handoff_explicit_planes_stored_and_vendor_linked(db):
    """When AOD sends explicit fabric_planes, they're stored. Candidates linked by vendor match."""
    from app.models import AODHandoffRequest, FabricPlaneSummary
    from app.services.handoff_service import process_handoff
    from app.db import get_fabric_planes, list_candidates

    run_id = "planes-run-001"
    tenant_id, entity_id = _identity()
    request = AODHandoffRequest(
        aod_discovery_id=run_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
        snapshot_name="planes-snap",
        handoff_timestamp=datetime.utcnow(),
        candidates=[
            _candidate("mulesoft.com", "mulesoft", "MuleSoft iPaaS", "ipaas", "ms1", run_id),
            _candidate("servicenow.com", "ServiceNow", "ServiceNow ITSM", "itsm", "sn1", run_id),
        ],
        fabric_planes=[
            FabricPlaneSummary(plane_type="IPAAS", vendor="mulesoft", is_healthy=True),
            FabricPlaneSummary(plane_type="API_GATEWAY", vendor="kong", is_healthy=True),
        ],
    )

    result = process_handoff(request)
    assert result.candidates_accepted == 2

    # Both explicit planes stored
    planes = get_fabric_planes()
    assert len(planes) == 2
    plane_vendors = {p["vendor"] for p in planes}
    assert plane_vendors == {"mulesoft", "kong"}

    # MuleSoft vendor-matched to IPAAS plane
    candidates = list_candidates()
    ms = [c for c in candidates if c["asset_key"] == "mulesoft.com"][0]
    assert ms["fabric_plane_id"] == "IPAAS:mulesoft"

    # ServiceNow has no vendor match — not linked (no category-based routing)
    sn = [c for c in candidates if c["asset_key"] == "servicenow.com"][0]
    assert sn["fabric_plane_id"] is None


def test_handoff_no_planes_when_aod_sends_none(db):
    """When AOD omits fabric_planes, AAM stores zero planes — AOD owns detection."""
    from app.models import AODHandoffRequest
    from app.services.handoff_service import process_handoff
    from app.db import get_fabric_planes

    run_id = "no-planes-run-001"
    tenant_id, entity_id = _identity()
    request = AODHandoffRequest(
        aod_discovery_id=run_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
        snapshot_name="hint-snap",
        handoff_timestamp=datetime.utcnow(),
        candidates=[
            _candidate("mulesoft.com", "MuleSoft", "MuleSoft - Ipaas", "other", "ms1", run_id),
            _candidate("konghq.com", "Kong", "Kong - Api Gateway", "other", "k1", run_id),
            _candidate("amazonaws.com", "AWS Redshift", "AWS Redshift - Data Warehouse", "data", "r1", run_id),
            _candidate("servicenow.com", "ServiceNow", "ServiceNow ITSM", "itsm", "sn1", run_id),
        ],
        fabric_planes=[],  # AOD omits planes
    )

    result = process_handoff(request)
    assert result.candidates_accepted == 4

    # AAM does NOT infer planes — display names, categories, vendor identity
    # are all irrelevant.  No AOD planes → no AAM planes.
    planes = get_fabric_planes()
    assert len(planes) == 0
