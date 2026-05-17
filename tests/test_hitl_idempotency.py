"""Tests for the DISP #24 follow-up HITL idempotency fix.

Pre-fix: insert_pending / insert_auto_applied wrote N rows for N calls
with the same (tenant, domain, left_value, right_value) tuple. B6 5x
produced 9140 pending rows for 912 distinct pairs (~10× duplication),
and SQLite scans against that table cascaded test failures.

Post-fix: dedup_key column + partial unique index + INSERT OR IGNORE.
N calls collapse to one row; subsequent calls return the existing
hitl_queue_id and append a 'reseen' audit event.
"""
from __future__ import annotations

import os
import uuid

import pytest


@pytest.fixture(autouse=True)
def _isolated_hitl_db(tmp_path, monkeypatch):
    """Force a per-test SQLite path before any hitl_store import side-effect."""
    db_path = str(tmp_path / "test_aam_hitl.db")
    monkeypatch.setenv("AAM_HITL_DB_PATH", db_path)
    import importlib
    from app.db import hitl_store as hs
    monkeypatch.setattr(hs, "_DB_PATH", db_path)
    hs.init_hitl_db()
    yield hs


def _seed_args(tenant_id, **overrides):
    args = dict(
        tenant_id=tenant_id, entity_id="test-entity", domain="customer",
        left_pipe_id="left-pipe", left_record_key="left-rec",
        left_value="Acme Corp",
        right_pipe_id=None, right_record_key=None,
        right_value="Acme Corp Inc.",
        confidence=0.72, proposed_canonical_id=str(uuid.uuid4()),
    )
    args.update(overrides)
    return args


def test_insert_pending_is_idempotent_for_same_pair(_isolated_hitl_db):
    hs = _isolated_hitl_db
    tenant_id = str(uuid.uuid4())
    qid1 = hs.insert_pending(**_seed_args(tenant_id))
    qid2 = hs.insert_pending(**_seed_args(tenant_id))
    qid3 = hs.insert_pending(**_seed_args(tenant_id))
    assert qid1 == qid2 == qid3, "same pair must return the same hitl_queue_id"
    all_rows = hs.list_all(tenant_id=tenant_id, limit=100)
    assert len(all_rows) == 1, f"expected 1 row, got {len(all_rows)}"


def test_insert_pending_different_pairs_create_distinct_rows(_isolated_hitl_db):
    hs = _isolated_hitl_db
    tenant_id = str(uuid.uuid4())
    qid_a = hs.insert_pending(**_seed_args(tenant_id, left_value="Acme A"))
    qid_b = hs.insert_pending(**_seed_args(tenant_id, left_value="Acme B"))
    assert qid_a != qid_b
    assert len(hs.list_all(tenant_id=tenant_id, limit=100)) == 2


def test_insert_pending_normalizes_whitespace_and_case(_isolated_hitl_db):
    hs = _isolated_hitl_db
    tenant_id = str(uuid.uuid4())
    qid1 = hs.insert_pending(**_seed_args(tenant_id, left_value="ACME  Corp"))
    qid2 = hs.insert_pending(**_seed_args(tenant_id, left_value="acme corp"))
    assert qid1 == qid2, "whitespace + case differences should collapse"
    assert len(hs.list_all(tenant_id=tenant_id, limit=100)) == 1


def test_insert_pending_different_status_is_distinct(_isolated_hitl_db):
    """A pair can exist as both pending AND auto_applied (different lifecycle)."""
    hs = _isolated_hitl_db
    tenant_id = str(uuid.uuid4())
    pending_qid = hs.insert_pending(**_seed_args(tenant_id))
    auto_qid = hs.insert_auto_applied(
        tenant_id=tenant_id, entity_id="test-entity", domain="customer",
        left_pipe_id="left-pipe", left_record_key="left-rec",
        left_value="Acme Corp",
        right_pipe_id=None, right_record_key=None,
        right_value="Acme Corp Inc.",
        confidence=0.95, canonical_id=str(uuid.uuid4()), match_rule="fuzzy",
    )
    assert pending_qid != auto_qid
    rows = hs.list_all(tenant_id=tenant_id, limit=100)
    statuses = sorted(r["status"] for r in rows)
    assert statuses == ["auto_applied", "pending"], statuses


def test_insert_auto_applied_is_idempotent(_isolated_hitl_db):
    hs = _isolated_hitl_db
    tenant_id = str(uuid.uuid4())
    canonical_id = str(uuid.uuid4())
    args = dict(
        tenant_id=tenant_id, entity_id="test-entity", domain="customer",
        left_pipe_id="left-pipe", left_record_key="left-rec",
        left_value="Acme Corp", right_pipe_id=None, right_record_key=None,
        right_value="Acme Corp Inc.", confidence=0.95,
        canonical_id=canonical_id, match_rule="fuzzy",
    )
    qid1 = hs.insert_auto_applied(**args)
    qid2 = hs.insert_auto_applied(**args)
    qid3 = hs.insert_auto_applied(**args)
    assert qid1 == qid2 == qid3
    auto = hs.list_auto_applied(tenant_id=tenant_id, limit=100)
    assert len(auto) == 1


def test_reseen_audit_event_appended_on_idempotent_reinsert(_isolated_hitl_db):
    """Each re-insert must add a 'reseen' audit row — operator can see frequency."""
    hs = _isolated_hitl_db
    tenant_id = str(uuid.uuid4())
    qid = hs.insert_pending(**_seed_args(tenant_id))
    hs.insert_pending(**_seed_args(tenant_id))
    hs.insert_pending(**_seed_args(tenant_id))
    audit = hs.get_audit(qid)
    events = [e["event"] for e in audit]
    assert events.count("created") == 1
    assert events.count("reseen") == 2, f"expected 2 reseen events, got {events}"


def test_b6_replay_does_not_duplicate(_isolated_hitl_db):
    """Simulate the B6 failure mode: 5 webhook runs, same 100 pairs each time."""
    hs = _isolated_hitl_db
    tenant_id = str(uuid.uuid4())
    pairs = [(f"left-{i}", f"right-{i}") for i in range(100)]
    for _run in range(5):
        for left, right in pairs:
            hs.insert_pending(
                tenant_id=tenant_id, entity_id="finops-demo-co",
                domain="customer", left_pipe_id=None, left_record_key=None,
                left_value=left, right_pipe_id=None, right_record_key=None,
                right_value=right, confidence=0.72,
                proposed_canonical_id=str(uuid.uuid4()),
            )
    all_rows = hs.list_all(tenant_id=tenant_id, limit=1000)
    assert len(all_rows) == 100, (
        f"5 runs × 100 pairs should collapse to 100 rows, got {len(all_rows)}"
    )


def test_tenant_isolation(_isolated_hitl_db):
    """Same pair under different tenants must NOT collapse."""
    hs = _isolated_hitl_db
    t1 = str(uuid.uuid4())
    t2 = str(uuid.uuid4())
    qid1 = hs.insert_pending(**_seed_args(t1))
    qid2 = hs.insert_pending(**_seed_args(t2))
    assert qid1 != qid2
    assert len(hs.list_all(tenant_id=t1, limit=100)) == 1
    assert len(hs.list_all(tenant_id=t2, limit=100)) == 1
