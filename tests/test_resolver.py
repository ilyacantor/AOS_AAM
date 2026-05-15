"""Tests for the record-level identity resolver (app.ingest.resolver) and
the HITL queue + decision endpoints (app.db.hitl_store, app.routers.resolver).

The operator-visible outcome under test is the FinTeam-NA / Finance North
America pair: real data flows through the resolver, scores in [0.65, 0.78],
and lands in the HITL queue. An operator decision approval flips the
downstream resolution_method to 'hitl_confirmed' at 0.99.

These are unit tests against the resolver + HITL store directly. End-to-end
wiring against the /api/aam/infer write path is covered by test_smoke and
test_inference_identity.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

# Force a per-test HITL DB before any app import resolves the env var.
@pytest.fixture(autouse=True)
def _isolated_hitl_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_aam_hitl.db")
    monkeypatch.setenv("AAM_HITL_DB_PATH", db_path)
    # Force the module-level constant in hitl_store to pick up our path.
    import importlib
    from app.db import hitl_store as hs
    monkeypatch.setattr(hs, "_DB_PATH", db_path)
    hs.init_hitl_db()
    yield
    # tmp_path teardown removes the file


@pytest.fixture
def tenant_entity():
    return str(uuid.uuid4()), "harness-entity"


@pytest.fixture
def seeded_registry(tenant_entity):
    """Seed a registry with three ServiceNow team canonicals + one exact match
    for 'Zoom' (so the exact-match test has something to hit).
    """
    from app.ingest.resolver import CanonicalRegistry
    tenant_id, _ = tenant_entity
    reg = CanonicalRegistry()
    # ServiceNow team canonicals
    reg.add_canonical(tenant_id=tenant_id, domain="cost_center",
                      value="Finance North America")
    reg.add_canonical(tenant_id=tenant_id, domain="cost_center",
                      value="Engineering EMEA")
    reg.add_canonical(tenant_id=tenant_id, domain="cost_center",
                      value="Marketing Asia Pacific")
    # SaaS canonicals
    reg.add_canonical(tenant_id=tenant_id, domain="saas_subscription",
                      value="Zoom")
    return reg


# ---------------------------------------------------------------------------
# Test 1 — operator-visible outcome: FinTeam-NA -> HITL pending
# ---------------------------------------------------------------------------

def test_finteam_na_lands_in_hitl_queue(seeded_registry, tenant_entity):
    """NetSuite cost-center 'FinTeam-NA' + ServiceNow team 'Finance North
    America' — the resolver scores them in [0.65, 0.78] and queues HITL.

    This is the verbatim WP3 operator-visible outcome.
    """
    from app.db import hitl_store
    from app.ingest.resolver import RecordResolver, similarity_score
    tenant_id, entity_id = tenant_entity

    # Sanity-check the algorithm: the pair must land in the expected band.
    raw = similarity_score("FinTeam-NA", "Finance North America")
    assert 0.65 <= raw <= 0.78, f"FinTeam-NA score must be in [0.65, 0.78]; got {raw:.4f}"

    resolver = RecordResolver(seeded_registry, fuzzy_threshold=0.65, auto_threshold=0.90)
    netsuite_record = {
        "vendor_id": "NS-V-99999",
        "vendor_name": "AOS Internal Cost Center",
        "cost_center": "FinTeam-NA",
    }
    result = resolver.resolve(
        netsuite_record,
        domain="cost_center",
        pipe_id="netsuite-pipe-001",
        tenant_id=tenant_id,
        entity_id=entity_id,
        value_field="cost_center",
        record_key_field="vendor_id",
    )

    assert result.resolution_method == "hitl_pending", (
        f"Expected hitl_pending; got {result.resolution_method} "
        f"at confidence {result.resolution_confidence}"
    )
    assert 0.65 <= result.resolution_confidence <= 0.78, (
        f"HITL confidence must be in [0.65, 0.78]; got {result.resolution_confidence}"
    )
    assert result.hitl_queue_id is not None
    assert result.canonical_id is not None

    # The HITL row exists and is pending.
    pending = hitl_store.get_pending(tenant_id=tenant_id, entity_id=entity_id,
                                     domain="cost_center")
    assert len(pending) == 1, f"Expected exactly 1 pending HITL row; got {len(pending)}"
    row = pending[0]
    assert row["status"] == "pending"
    assert row["left_value"] == "FinTeam-NA"
    assert row["right_value"] == "Finance North America"
    assert row["domain"] == "cost_center"
    assert row["left_record_key"] == "NS-V-99999"
    assert abs(row["confidence"] - result.resolution_confidence) < 1e-6


# ---------------------------------------------------------------------------
# Test 2 — operator approves: triples flip to hitl_confirmed at 0.99
# ---------------------------------------------------------------------------

def test_approve_decision_flips_method_to_hitl_confirmed(seeded_registry, tenant_entity, monkeypatch):
    """After /api/aam/resolver/decisions approves the pending pair, the row
    becomes status='approved' and any downstream semantic_triples row with
    the proposed canonical_id flips to resolution_method='hitl_confirmed',
    resolution_confidence=0.99.

    The PG promotion step is a separate concern (its own DB write); we patch
    it out here and assert the call shape. Real promotion is covered by the
    /api/aam/infer integration tests when run against the live DB.
    """
    from app.db import hitl_store
    from app.ingest.resolver import RecordResolver
    from app.routers import resolver as resolver_router
    from fastapi import FastAPI

    tenant_id, entity_id = tenant_entity
    resolver = RecordResolver(seeded_registry, fuzzy_threshold=0.65, auto_threshold=0.90)
    record = {
        "vendor_id": "NS-V-99999",
        "vendor_name": "AOS Internal",
        "cost_center": "FinTeam-NA",
    }
    pre = resolver.resolve(record, domain="cost_center", pipe_id="ns-001",
                           tenant_id=tenant_id, entity_id=entity_id,
                           value_field="cost_center", record_key_field="vendor_id")
    hitl_queue_id = pre.hitl_queue_id
    proposed_canonical_id = pre.canonical_id

    # Patch the PG triple-promotion to avoid hitting Supabase from the unit suite.
    promoted_calls: list[tuple[str, str, str]] = []
    def _fake_promote(*, tenant_id, entity_id, canonical_id):
        promoted_calls.append((tenant_id, entity_id, canonical_id))
        return 7  # pretend 7 triples were promoted
    monkeypatch.setattr(resolver_router, "_promote_triples_to_confirmed", _fake_promote)

    app = FastAPI()
    app.include_router(resolver_router.router)
    client = TestClient(app)
    resp = client.post("/api/aam/resolver/decisions", json={
        "hitl_queue_id": hitl_queue_id,
        "decision": "approved",
        "decided_by": "harness-test",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision"] == "approved"
    assert body["status"] == "approved"
    assert body["triples_promoted"] == 7
    assert promoted_calls == [(tenant_id, entity_id, proposed_canonical_id)]

    # Re-read the queue row — it must be approved now.
    final = hitl_store.get_by_id(hitl_queue_id)
    assert final["status"] == "approved"
    assert final["decided_by"] == "harness-test"
    assert final["decided_at"] is not None

    # Audit trail carries the promotion event.
    audit = hitl_store.get_audit(hitl_queue_id)
    events = [a["event"] for a in audit]
    assert "created" in events
    assert "decided_approved" in events
    assert "triples_promoted" in events


# ---------------------------------------------------------------------------
# Test 3 — exact match short-circuits everything
# ---------------------------------------------------------------------------

def test_exact_match_no_hitl(seeded_registry, tenant_entity):
    """A NetSuite record carrying 'Zoom' resolves exactly against the seeded
    canonical at confidence=1.0 with method='exact' — and no HITL row is
    created.
    """
    from app.db import hitl_store
    from app.ingest.resolver import RecordResolver

    tenant_id, entity_id = tenant_entity
    resolver = RecordResolver(seeded_registry, fuzzy_threshold=0.65, auto_threshold=0.90)
    res = resolver.resolve(
        {"vendor_id": "NS-V-00001", "vendor_name": "Zoom"},
        domain="saas_subscription",
        pipe_id="netsuite-pipe-001",
        tenant_id=tenant_id,
        entity_id=entity_id,
        value_field="vendor_name",
        record_key_field="vendor_id",
    )
    assert res.resolution_method == "exact"
    assert res.resolution_confidence == 1.0
    assert res.hitl_queue_id is None
    pending = hitl_store.get_pending(tenant_id=tenant_id, entity_id=entity_id)
    assert pending == []


# ---------------------------------------------------------------------------
# Test 4 — below fuzzy threshold rejects loudly with audit
# ---------------------------------------------------------------------------

def test_low_confidence_rejects_loudly(seeded_registry, tenant_entity):
    """A pair whose similarity is below fuzzy_threshold rejects (no silent
    fallback to "best guess") and creates no HITL row. The result carries
    an audit trail explaining why.
    """
    from app.db import hitl_store
    from app.ingest.resolver import RecordResolver

    tenant_id, entity_id = tenant_entity
    # Discovery disabled, so a no-match goes straight to rejected.
    resolver = RecordResolver(seeded_registry, fuzzy_threshold=0.65,
                              auto_threshold=0.90, discovery_enabled=False)
    res = resolver.resolve(
        {"vendor_id": "NS-V-XX", "vendor_name": "ZZZ Unrelated GmbH"},
        domain="saas_subscription",
        pipe_id="netsuite-pipe-001",
        tenant_id=tenant_id,
        entity_id=entity_id,
        value_field="vendor_name",
        record_key_field="vendor_id",
    )
    assert res.resolution_method == "rejected"
    assert res.canonical_id is None
    assert res.hitl_queue_id is None
    assert "reason" in res.audit
    assert res.audit["best_score"] < 0.65
    # No HITL rows for this tenant.
    pending = hitl_store.get_pending(tenant_id=tenant_id, entity_id=entity_id)
    assert pending == []


# ---------------------------------------------------------------------------
# Test 5 — discovery mints a new canonical
# ---------------------------------------------------------------------------

def test_discovery_mints_new_canonical(seeded_registry, tenant_entity):
    """A record with no canonical match (and discovery enabled) yields a
    freshly-minted canonical_id at confidence 0.99 with method='discovery'.
    Subsequent records with the same value then hit it via exact match.
    """
    from app.db import hitl_store
    from app.ingest.resolver import RecordResolver

    tenant_id, entity_id = tenant_entity
    resolver = RecordResolver(seeded_registry, fuzzy_threshold=0.65,
                              auto_threshold=0.90, discovery_enabled=True)
    # Brand new vendor; no candidate scores >= fuzzy_threshold.
    res1 = resolver.resolve(
        {"vendor_id": "NS-V-NEW", "vendor_name": "Pinecone Vector"},
        domain="saas_subscription",
        pipe_id="netsuite-pipe-001",
        tenant_id=tenant_id,
        entity_id=entity_id,
        value_field="vendor_name",
        record_key_field="vendor_id",
    )
    assert res1.resolution_method == "discovery"
    assert res1.resolution_confidence == 0.99
    assert res1.canonical_id is not None
    assert res1.hitl_queue_id is None

    # Second record with the same value hits via exact.
    res2 = resolver.resolve(
        {"vendor_id": "NS-V-NEW-2", "vendor_name": "Pinecone Vector"},
        domain="saas_subscription",
        pipe_id="netsuite-pipe-001",
        tenant_id=tenant_id,
        entity_id=entity_id,
        value_field="vendor_name",
        record_key_field="vendor_id",
    )
    assert res2.resolution_method == "exact"
    assert res2.canonical_id == res1.canonical_id
    # Still no HITL rows.
    assert hitl_store.get_pending(tenant_id=tenant_id, entity_id=entity_id) == []


# ---------------------------------------------------------------------------
# Test 6 — negative: missing identity raises ValueError at resolver entry
# ---------------------------------------------------------------------------

def test_missing_tenant_raises(seeded_registry):
    """Resolver refuses to operate without tenant_id + entity_id. The
    orchestrator surfaces this as 422 at the API door (post-WP1 invariant).
    """
    from app.ingest.resolver import RecordResolver
    resolver = RecordResolver(seeded_registry)
    with pytest.raises(ValueError, match="tenant_id and entity_id required"):
        resolver.resolve(
            {"vendor_name": "Zoom"},
            domain="saas_subscription",
            pipe_id="p", tenant_id="", entity_id="harness",
            value_field="vendor_name",
        )
    with pytest.raises(ValueError, match="tenant_id and entity_id required"):
        resolver.resolve(
            {"vendor_name": "Zoom"},
            domain="saas_subscription",
            pipe_id="p", tenant_id="t", entity_id="",
            value_field="vendor_name",
        )


# ---------------------------------------------------------------------------
# Test 7 — rejected decision keeps the HITL row out of the auto-accept stream
# ---------------------------------------------------------------------------

def test_reject_decision_marks_rejected(seeded_registry, tenant_entity, monkeypatch):
    from app.db import hitl_store
    from app.ingest.resolver import RecordResolver
    from app.routers import resolver as resolver_router
    from fastapi import FastAPI

    tenant_id, entity_id = tenant_entity
    resolver = RecordResolver(seeded_registry, fuzzy_threshold=0.65, auto_threshold=0.90)
    res = resolver.resolve(
        {"vendor_id": "NS-V-1", "cost_center": "FinTeam-NA"},
        domain="cost_center", pipe_id="ns", tenant_id=tenant_id,
        entity_id=entity_id, value_field="cost_center",
        record_key_field="vendor_id",
    )

    # Don't need PG promotion on a reject — but patch to be safe.
    monkeypatch.setattr(resolver_router, "_promote_triples_to_confirmed",
                        lambda **k: 0)
    app = FastAPI()
    app.include_router(resolver_router.router)
    client = TestClient(app)
    resp = client.post("/api/aam/resolver/decisions", json={
        "hitl_queue_id": res.hitl_queue_id,
        "decision": "rejected",
        "decided_by": "harness-test",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["triples_promoted"] == 0
    final = hitl_store.get_by_id(res.hitl_queue_id)
    assert final["status"] == "rejected"


# ---------------------------------------------------------------------------
# Test 8 — pending list endpoint requires tenant_id
# ---------------------------------------------------------------------------

def test_pending_endpoint_requires_tenant(seeded_registry, tenant_entity):
    from app.routers import resolver as resolver_router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(resolver_router.router)
    client = TestClient(app)
    # Missing tenant_id -> 422
    resp = client.get("/api/aam/resolver/pending")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 9 — audit endpoint returns the trail
# ---------------------------------------------------------------------------

def test_audit_endpoint(seeded_registry, tenant_entity):
    from app.ingest.resolver import RecordResolver
    from app.routers import resolver as resolver_router
    from fastapi import FastAPI
    tenant_id, entity_id = tenant_entity
    resolver = RecordResolver(seeded_registry, fuzzy_threshold=0.65, auto_threshold=0.90)
    res = resolver.resolve(
        {"vendor_id": "NS-V-A", "cost_center": "FinTeam-NA"},
        domain="cost_center", pipe_id="ns", tenant_id=tenant_id,
        entity_id=entity_id, value_field="cost_center",
        record_key_field="vendor_id",
    )
    app = FastAPI()
    app.include_router(resolver_router.router)
    client = TestClient(app)
    resp = client.get(f"/api/aam/resolver/audit?hitl_queue_id={res.hitl_queue_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hitl_queue_id"] == res.hitl_queue_id
    assert body["status"] == "pending"
    assert len(body["audit"]) >= 1
    assert body["audit"][0]["event"] == "created"


# ---------------------------------------------------------------------------
# Test 10 — double decision rejected (409): no overwriting a finalized verdict
# ---------------------------------------------------------------------------

def test_cannot_decide_twice(seeded_registry, tenant_entity, monkeypatch):
    from app.ingest.resolver import RecordResolver
    from app.routers import resolver as resolver_router
    from fastapi import FastAPI
    tenant_id, entity_id = tenant_entity
    resolver = RecordResolver(seeded_registry, fuzzy_threshold=0.65, auto_threshold=0.90)
    res = resolver.resolve(
        {"vendor_id": "NS-V-A", "cost_center": "FinTeam-NA"},
        domain="cost_center", pipe_id="ns", tenant_id=tenant_id,
        entity_id=entity_id, value_field="cost_center",
        record_key_field="vendor_id",
    )
    monkeypatch.setattr(resolver_router, "_promote_triples_to_confirmed",
                        lambda **k: 0)
    app = FastAPI()
    app.include_router(resolver_router.router)
    client = TestClient(app)
    r1 = client.post("/api/aam/resolver/decisions", json={
        "hitl_queue_id": res.hitl_queue_id,
        "decision": "approved", "decided_by": "op-1",
    })
    assert r1.status_code == 200
    r2 = client.post("/api/aam/resolver/decisions", json={
        "hitl_queue_id": res.hitl_queue_id,
        "decision": "rejected", "decided_by": "op-2",
    })
    assert r2.status_code == 409, r2.text
