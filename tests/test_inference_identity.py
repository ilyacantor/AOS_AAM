"""Test that AAM inference responses carry pipeline identity fields (I1–I2).

Validates: aam_inference_id, source_handoff_id, tenant_id, entity_id
on every response path from POST /api/aam/infer.
"""
import asyncio
import uuid
from datetime import datetime


def _do_handoff(db, entity_id="test-entity", tenant_id=None):
    """Create an AOD handoff and return the handoff result."""
    from app.models import AODHandoffRequest
    from app.services.handoff_service import process_handoff

    if tenant_id is None:
        tenant_id = str(uuid.uuid4())
    run_id = f"identity-run-{uuid.uuid4().hex[:8]}"
    request = AODHandoffRequest(
        run_id=run_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
        snapshot_name=entity_id,
        handoff_timestamp=datetime.utcnow(),
        candidates=[{
            "asset_key": f"test-{uuid.uuid4().hex[:6]}.com",
            "vendor_name": "TestVendor",
            "display_name": "Test Vendor App",
            "category": "crm",
            "aod_asset_id": f"asset-{uuid.uuid4().hex[:6]}",
            "aod_run_id": run_id,
            "execution_allowed": True,
            "action_type": "provision",
        }],
    )
    return process_handoff(request), tenant_id


def test_infer_response_has_identity_fields(db):
    """Inference response must carry aam_inference_id, source_handoff_id,
    tenant_id, entity_id on the main response path."""
    handoff, expected_tenant = _do_handoff(db, entity_id="test-entity")

    from app.routers.collectors import infer_pipes
    result = asyncio.run(infer_pipes())

    # aam_inference_id: new canonical identifier — must be a valid UUID
    assert "aam_inference_id" in result, "aam_inference_id missing from inference response"
    assert result["aam_inference_id"] is not None
    uuid.UUID(result["aam_inference_id"])

    # source_handoff_id: traces back to the AOD handoff
    assert "source_handoff_id" in result, "source_handoff_id missing from inference response"
    assert result["source_handoff_id"] == handoff.handoff_id

    # tenant_id + entity_id: pipeline identity pair (I2)
    assert "tenant_id" in result, "tenant_id missing from inference response"
    assert result["tenant_id"] == expected_tenant
    assert "entity_id" in result, "entity_id missing from inference response"
    assert result["entity_id"] == "test-entity"

    # run_id still present (backward compat) — matches aam_inference_id, not ledger_id
    assert result["run_id"] == result["aam_inference_id"]


def test_infer_empty_response_has_identity_fields(db):
    """Even when nothing to process, identity fields must be present."""
    handoff, expected_tenant = _do_handoff(db, entity_id="empty-entity")

    from app.routers.collectors import infer_pipes
    # First call processes candidates
    asyncio.run(infer_pipes())
    # Second call: nothing to process (all candidates matched)
    result = asyncio.run(infer_pipes())

    assert "aam_inference_id" in result
    assert result["aam_inference_id"] is not None
    uuid.UUID(result["aam_inference_id"])
    assert "source_handoff_id" in result
    assert result["source_handoff_id"] == handoff.handoff_id
    assert "tenant_id" in result
    assert result["tenant_id"] == expected_tenant
    assert "entity_id" in result
    assert result["entity_id"] == "empty-entity"
