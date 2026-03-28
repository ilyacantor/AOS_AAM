"""
Unit tests for AAM triple converter — pure conversion logic, no PG required.
"""
import json
import uuid

import pytest

from app.converters.triple_converter import (
    convert_pipe_to_triples,
    convert_connection_to_triples,
    convert_drift_to_triples,
    convert_fabric_plane_to_triples,
    convert_inference_batch,
    generate_run_id,
    resolve_entity_id,
    _tier_from_score,
    _should_skip,
    _to_tenant_uuid,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ENTITY_ID = "test-snapshot-001"
TENANT_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "test-tenant"))
RUN_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "test-run"))
RUN_TAG = "aam_triples_test_run"


def _sample_pipe():
    return {
        "pipe_id": str(uuid.uuid4()),
        "display_name": "Salesforce - Opportunities",
        "fabric_plane": "API_GATEWAY",
        "modality": "DECLARED_INTERFACE",
        "source_system": "salesforce",
        "transport_kind": "API",
        "entity_scope": json.dumps(["Opportunity", "Account"]),
        "identity_keys": json.dumps(["OpportunityId"]),
        "schema_info": json.dumps({"schema_hash": "abc123", "schema_version": "inferred"}),
    }


def _sample_connection():
    return {
        "matched_pipe_id": str(uuid.uuid4()),
        "vendor_name": "salesforce",
        "category": "crm",
        "match_score": 0.92,
        "status": "connected",
        "connected_via_plane": "API_GATEWAY",
    }


def _sample_drift():
    return {
        "drift_id": str(uuid.uuid4()),
        "pipe_id": str(uuid.uuid4()),
        "drift_type": "schema",
        "old_value": "hash_old",
        "new_value": "hash_new",
        "severity": "medium",
        "detected_at": "2026-03-20T10:00:00",
    }


def _sample_plane():
    return {
        "plane_type": "API_GATEWAY",
        "vendor": "kong",
        "is_healthy": True,
    }


# ---------------------------------------------------------------------------
# Pipe conversion
# ---------------------------------------------------------------------------

class TestConvertPipe:
    def test_basic(self):
        pipe = _sample_pipe()
        triples = convert_pipe_to_triples(pipe, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        # 7 standard properties + 1 schema_hash = 8 triples
        assert len(triples) == 8
        concepts = {t["concept"] for t in triples}
        assert concepts == {"mapping.pipe"}

    def test_all_have_source_system_aam(self):
        triples = convert_pipe_to_triples(_sample_pipe(), ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["source_system"] == "AAM"

    def test_pipe_id_set(self):
        pipe = _sample_pipe()
        triples = convert_pipe_to_triples(pipe, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["pipe_id"] == pipe["pipe_id"]

    def test_skips_none_values(self):
        pipe = _sample_pipe()
        pipe["fabric_plane"] = None
        triples = convert_pipe_to_triples(pipe, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        props = {t["property"] for t in triples}
        assert "fabric_plane" not in props

    def test_skips_empty_string(self):
        pipe = _sample_pipe()
        pipe["modality"] = ""
        triples = convert_pipe_to_triples(pipe, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        props = {t["property"] for t in triples}
        assert "modality" not in props

    def test_entity_scope_parsed_from_json(self):
        pipe = _sample_pipe()
        triples = convert_pipe_to_triples(pipe, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        es_triple = [t for t in triples if t["property"] == "entity_scope"][0]
        assert es_triple["value"] == ["Opportunity", "Account"]

    def test_schema_hash_extracted(self):
        pipe = _sample_pipe()
        triples = convert_pipe_to_triples(pipe, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        sh_triple = [t for t in triples if t["property"] == "schema_hash"][0]
        assert sh_triple["value"] == "abc123"

    def test_no_schema_hash_when_missing(self):
        pipe = _sample_pipe()
        pipe["schema_info"] = json.dumps({"schema_version": "inferred"})
        triples = convert_pipe_to_triples(pipe, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        props = {t["property"] for t in triples}
        assert "schema_hash" not in props

    def test_source_table_is_declared_pipes(self):
        triples = convert_pipe_to_triples(_sample_pipe(), ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["source_table"] == "declared_pipes"


# ---------------------------------------------------------------------------
# Connection conversion
# ---------------------------------------------------------------------------

class TestConvertConnection:
    def test_basic(self):
        conn = _sample_connection()
        triples = convert_connection_to_triples(conn, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        assert len(triples) == 4
        concepts = {t["concept"] for t in triples}
        assert concepts == {"mapping.connection"}

    def test_confidence_tier_high(self):
        conn = _sample_connection()
        conn["match_score"] = 0.9
        triples = convert_connection_to_triples(conn, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["confidence_tier"] == "high"
            assert t["confidence_score"] == 0.9

    def test_confidence_tier_medium(self):
        conn = _sample_connection()
        conn["match_score"] = 0.6
        triples = convert_connection_to_triples(conn, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["confidence_tier"] == "medium"

    def test_confidence_tier_low(self):
        conn = _sample_connection()
        conn["match_score"] = 0.3
        triples = convert_connection_to_triples(conn, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["confidence_tier"] == "low"

    def test_pipe_id_from_matched(self):
        conn = _sample_connection()
        triples = convert_connection_to_triples(conn, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["pipe_id"] == conn["matched_pipe_id"]


# ---------------------------------------------------------------------------
# Drift conversion
# ---------------------------------------------------------------------------

class TestConvertDrift:
    def test_schema_drift_exact_confidence(self):
        drift = _sample_drift()
        drift["drift_type"] = "schema"
        triples = convert_drift_to_triples(drift, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["confidence_score"] == 1.0
            assert t["confidence_tier"] == "exact"

    def test_freshness_drift_high_confidence(self):
        drift = _sample_drift()
        drift["drift_type"] = "freshness"
        triples = convert_drift_to_triples(drift, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["confidence_score"] == 0.85
            assert t["confidence_tier"] == "high"

    def test_drift_has_period(self):
        drift = _sample_drift()
        triples = convert_drift_to_triples(drift, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["period"] == "2026-03-20T10:00:00"

    def test_drift_properties(self):
        drift = _sample_drift()
        triples = convert_drift_to_triples(drift, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        props = {t["property"] for t in triples}
        assert "drift_type" in props
        assert "severity" in props
        assert "affected_pipe" in props

    def test_concept_prefix(self):
        triples = convert_drift_to_triples(_sample_drift(), ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["concept"] == "mapping.drift"


# ---------------------------------------------------------------------------
# Fabric plane conversion
# ---------------------------------------------------------------------------

class TestConvertFabricPlane:
    def test_basic(self):
        plane = _sample_plane()
        triples = convert_fabric_plane_to_triples(plane, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        assert len(triples) == 3

    def test_concept_prefix(self):
        triples = convert_fabric_plane_to_triples(_sample_plane(), ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["concept"] == "mapping.fabric"

    def test_properties(self):
        triples = convert_fabric_plane_to_triples(_sample_plane(), ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        props = {t["property"] for t in triples}
        assert props == {"plane_type", "vendor", "health_status"}

    def test_confidence(self):
        triples = convert_fabric_plane_to_triples(_sample_plane(), ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        for t in triples:
            assert t["confidence_score"] == 0.90
            assert t["confidence_tier"] == "high"


# ---------------------------------------------------------------------------
# Run ID generation
# ---------------------------------------------------------------------------

class TestGenerateRunId:
    def test_returns_valid_uuid(self):
        run_uuid, run_tag = generate_run_id()
        uuid.UUID(run_uuid)  # Raises ValueError if invalid

    def test_run_tag_format(self):
        _, run_tag = generate_run_id()
        assert run_tag.startswith("aam_triples_")

    def test_unique_across_calls(self):
        id1, _ = generate_run_id()
        id2, _ = generate_run_id()
        assert id1 != id2


# ---------------------------------------------------------------------------
# Entity ID resolution
# ---------------------------------------------------------------------------

class TestResolveEntityId:
    def test_snapshot_preferred(self):
        result = resolve_entity_id("my-snapshot", "my-run-id")
        assert result == "my-snapshot"

    def test_falls_back_to_aod_run_id(self):
        result = resolve_entity_id(None, "my-run-id")
        assert result == "my-run-id"

    def test_returns_none_when_both_missing(self):
        result = resolve_entity_id(None, None)
        assert result is None

    def test_strips_whitespace(self):
        result = resolve_entity_id("  snapshot  ", None)
        assert result == "snapshot"

    def test_empty_string_returns_none(self):
        result = resolve_entity_id("", "")
        assert result is None


# ---------------------------------------------------------------------------
# Batch conversion
# ---------------------------------------------------------------------------

class TestBatchConversion:
    def test_empty_inputs(self):
        result = convert_inference_batch([], [], [], ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        assert result == []

    def test_combines_all_types(self):
        pipes = [_sample_pipe()]
        conns = [_sample_connection()]
        planes = [_sample_plane()]
        result = convert_inference_batch(pipes, conns, planes, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        concepts = {t["concept"] for t in result}
        assert "mapping.pipe" in concepts
        assert "mapping.connection" in concepts
        assert "mapping.fabric" in concepts

    def test_all_have_run_id(self):
        result = convert_inference_batch(
            [_sample_pipe()], [_sample_connection()], [_sample_plane()],
            ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID,
        )
        for t in result:
            assert t["run_id"] == RUN_ID

    def test_all_have_entity_id(self):
        result = convert_inference_batch(
            [_sample_pipe()], [], [],
            ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID,
        )
        for t in result:
            assert t["entity_id"] == ENTITY_ID


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_tier_exact(self):
        assert _tier_from_score(1.0) == "exact"
        assert _tier_from_score(0.95) == "exact"

    def test_tier_high(self):
        assert _tier_from_score(0.85) == "high"
        assert _tier_from_score(0.75) == "high"

    def test_tier_medium(self):
        assert _tier_from_score(0.6) == "medium"
        assert _tier_from_score(0.5) == "medium"

    def test_tier_low(self):
        assert _tier_from_score(0.3) == "low"
        assert _tier_from_score(0.0) == "low"

    def test_should_skip_none(self):
        assert _should_skip(None) is True

    def test_should_skip_empty_str(self):
        assert _should_skip("") is True
        assert _should_skip("   ") is True

    def test_should_skip_empty_list(self):
        assert _should_skip([]) is True

    def test_should_not_skip_valid(self):
        assert _should_skip("value") is False
        assert _should_skip(0) is False
        assert _should_skip(False) is False
        assert _should_skip(["item"]) is False

    def test_to_tenant_uuid_valid_uuid(self):
        u = str(uuid.uuid4())
        assert _to_tenant_uuid(u) == u

    def test_to_tenant_uuid_string(self):
        result = _to_tenant_uuid("my-snapshot")
        uuid.UUID(result)  # Must be valid UUID
        # Deterministic
        assert _to_tenant_uuid("my-snapshot") == result

    def test_value_none_excluded(self):
        """Properties with None values must produce no triples."""
        pipe = {
            "pipe_id": str(uuid.uuid4()),
            "display_name": None,
            "fabric_plane": None,
            "modality": None,
            "source_system": None,
            "transport_kind": None,
            "entity_scope": None,
            "identity_keys": None,
            "schema_info": None,
        }
        triples = convert_pipe_to_triples(pipe, ENTITY_ID, RUN_ID, RUN_TAG, tenant_id=TENANT_ID)
        assert len(triples) == 0
