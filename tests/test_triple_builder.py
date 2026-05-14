"""Unit tests for app.ingest.triple_builder.

Coverage:
  - concept canonicalization translates PascalCase -> DCL-valid lowercase roots
  - source_system is lowercased from the record (never literal "AAM")
  - resolver metadata propagates: canonical_id, resolution_method (translated to
    DCL vocab), resolution_confidence
  - confidence_score is min(field_mapping, resolver) when resolver lowered it
  - fabric_plane is normalized to DCL's lowercase enum
  - pipe_id is coerced to UUID5 when not already a UUID
  - missing tenant_id / entity_id / source_system raises ValueError
"""

from __future__ import annotations

import uuid

import pytest

from app.ingest.mappings import FieldMapping
from app.ingest.triple_builder import (
    VENDOR_TO_SOURCE_SYSTEM,
    _canonical_concept,
    build_dcl_triples,
    expected_source_system,
)
from app.transport.http import TransportRecord


def _record(payload: dict, *, pipe_id="wk-recipe-101", source_system="NetSuite",
            metadata=None) -> TransportRecord:
    return TransportRecord(
        pipe_id=pipe_id,
        record_key=payload.get("vendor_id", "rec-0"),
        payload=payload,
        offset="0",
        source_system=source_system,
        metadata=metadata or {},
    )


def _pipe(pipe_id="wk-recipe-101", fabric_plane="IPAAS"):
    return {"pipe_id": pipe_id, "fabric_plane": fabric_plane}


def test_canonical_concept_translates_pascalcase():
    """Known PascalCase concepts map to ontology-valid lowercase roots."""
    assert _canonical_concept("Vendor") == "vendor"
    assert _canonical_concept("Customer") == "customer"
    assert _canonical_concept("SaaSApp") == "it_asset"
    assert _canonical_concept("APInvoice") == "invoice"
    assert _canonical_concept("User") == "employee"


def test_canonical_concept_passes_through_lowercase():
    """Already-lowercase concepts are accepted as-is."""
    assert _canonical_concept("vendor") == "vendor"
    assert _canonical_concept("invoice.amount") == "invoice.amount"


def test_canonical_concept_raises_on_unknown():
    """Unknown PascalCase concept surfaces a readable error so the operator
    can add an explicit mapping rather than letting DCL reject it.
    """
    with pytest.raises(ValueError) as exc:
        _canonical_concept("MysteryThing")
    assert "MysteryThing" in str(exc.value)
    assert "_CONCEPT_TO_DCL_ROOT" in str(exc.value)


def test_vendor_source_system_map_covers_demo_scenarios():
    """The map must include every (vendor, source) pair the FinOps + healthy
    scenarios produce, or DCL ingest will reject those triples with no
    explicit operator-visible reason.
    """
    # healthy scenario
    assert expected_source_system("workato", "salesforce") == "salesforce"
    assert expected_source_system("workato", "workday") == "workday"
    assert expected_source_system("boomi", "servicenow") == "servicenow"
    # FinOps scenario
    assert expected_source_system("workato", "netsuite") == "netsuite"
    assert expected_source_system("boomi", "okta") == "okta"


def test_expected_source_system_raises_on_unknown():
    """Unknown vendor pair surfaces a loud error, not a silent default."""
    with pytest.raises(KeyError):
        expected_source_system("salesforce", "mystery")


def test_build_dcl_triples_happy_path():
    """One mapped record -> N TriplePayloads, all carrying DCL-valid shape."""
    rec = _record(
        payload={"vendor_id": "NS-V-00000", "vendor_name": "LinkedIn"},
        source_system="NetSuite",
    )
    mappings = [
        FieldMapping("vendor_id", "Vendor", "id"),
        FieldMapping("vendor_name", "Vendor", "name"),
    ]
    triples = build_dcl_triples(
        rec, pipe=_pipe(), mappings=mappings,
        tenant_id="00000000-0000-0000-0000-000000000001",
        entity_id="test-entity",
        vendor="workato",
    )
    assert len(triples) == 2
    # source_system lowercased
    for t in triples:
        assert t["source_system"] == "netsuite"
        assert t["entity_id"] == "test-entity"
        assert t["concept"].startswith("vendor.")
        assert t["confidence_score"] == 0.95
        assert t["confidence_tier"] == "exact"
        assert t["fabric_plane"] == "ipaas"
        assert t["fabric_product"] == "netsuite"
        # pipe_id coerced to UUID5 since "wk-recipe-101" isn't a UUID
        uuid.UUID(t["pipe_id"])  # raises if not parseable
        assert t["source_table"] == "aam_via:workato"


def test_build_dcl_triples_propagates_resolver_metadata():
    """When the resolver attached _resolution metadata, every triple carries
    canonical_id / resolution_method / resolution_confidence.
    """
    canonical = str(uuid.uuid4())
    rec = _record(
        payload={"vendor_id": "NS-V-00001", "vendor_name": "Acme"},
        source_system="NetSuite",
        metadata={
            "_resolution": {
                "canonical_id": canonical,
                "resolution_method": "fuzzy",
                "resolution_confidence": 0.71,
            }
        },
    )
    mappings = [FieldMapping("vendor_name", "Vendor", "name", confidence=0.95)]
    triples = build_dcl_triples(
        rec, pipe=_pipe(), mappings=mappings,
        tenant_id="00000000-0000-0000-0000-000000000001",
        entity_id="test-entity",
        vendor="workato",
    )
    assert len(triples) == 1
    t = triples[0]
    assert t["canonical_id"] == canonical
    assert t["resolution_method"] == "fuzzy"
    assert t["resolution_confidence"] == 0.71
    # Resolver lowered confidence below the field-mapping confidence — min wins
    assert t["confidence_score"] == 0.71


def test_build_dcl_triples_translates_resolver_method_to_dcl_vocab():
    """hitl_pending in AAM's vocab becomes 'fuzzy' in DCL's CHECK constraint;
    hitl_confirmed becomes 'manual'.
    """
    canonical = str(uuid.uuid4())
    cases = [
        ("hitl_pending", "fuzzy"),
        ("hitl_confirmed", "manual"),
        ("exact", "deterministic"),
        ("discovery", "deterministic"),
    ]
    for aam_method, dcl_method in cases:
        rec = _record(
            payload={"vendor_name": "X"},
            source_system="NetSuite",
            metadata={
                "_resolution": {
                    "canonical_id": canonical,
                    "resolution_method": aam_method,
                    "resolution_confidence": 0.99,
                }
            },
        )
        triples = build_dcl_triples(
            rec, pipe=_pipe(),
            mappings=[FieldMapping("vendor_name", "Vendor", "name")],
            tenant_id="00000000-0000-0000-0000-000000000001",
            entity_id="test-entity",
            vendor="workato",
        )
        assert triples[0]["resolution_method"] == dcl_method, (
            f"expected {aam_method} -> {dcl_method}"
        )


def test_build_dcl_triples_loud_fail_missing_identity():
    """Missing tenant_id or entity_id raises immediately — no silent default."""
    rec = _record(payload={"vendor_name": "X"}, source_system="NetSuite")
    mappings = [FieldMapping("vendor_name", "Vendor", "name")]
    with pytest.raises(ValueError, match="tenant_id and entity_id"):
        build_dcl_triples(
            rec, pipe=_pipe(), mappings=mappings,
            tenant_id="", entity_id="e", vendor="workato",
        )
    with pytest.raises(ValueError, match="tenant_id and entity_id"):
        build_dcl_triples(
            rec, pipe=_pipe(), mappings=mappings,
            tenant_id="t", entity_id="", vendor="workato",
        )


def test_build_dcl_triples_loud_fail_missing_source_system():
    """Empty record.source_system is a contract violation — no 'AAM' default."""
    rec = _record(payload={"vendor_name": "X"}, source_system="")
    with pytest.raises(ValueError, match="source_system is empty"):
        build_dcl_triples(
            rec, pipe=_pipe(),
            mappings=[FieldMapping("vendor_name", "Vendor", "name")],
            tenant_id="00000000-0000-0000-0000-000000000001",
            entity_id="test-entity",
            vendor="workato",
        )


def test_build_dcl_triples_skips_unmapped_fields():
    """Fields without a FieldMapping are warned-and-skipped, not silently
    fabricated as triples.
    """
    rec = _record(
        payload={"vendor_name": "X", "mystery_field": "ignored"},
        source_system="NetSuite",
    )
    triples = build_dcl_triples(
        rec, pipe=_pipe(),
        mappings=[FieldMapping("vendor_name", "Vendor", "name")],
        tenant_id="00000000-0000-0000-0000-000000000001",
        entity_id="test-entity",
        vendor="workato",
    )
    assert len(triples) == 1
    assert triples[0]["source_field"] == "vendor_name"
