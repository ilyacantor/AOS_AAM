"""Unit tests for app.ingest.dcl_pusher.

Tests cover:
  - happy-path push returns parsed result
  - 4xx error raises DCLPushError immediately, no retry
  - 5xx error retries with backoff, then raises if exhausted
  - 5xx then success: success returned, retry path taken
  - network error retries then raises
  - empty triples returns 0-count result without HTTP call
  - batch slicing: >batch_size triggers append=true on subsequent batches
"""

from __future__ import annotations

import httpx
import pytest

from app.ingest.dcl_pusher import (
    DCLPushError,
    DCLPushRequest,
    DCLPusher,
    make_dcl_ingest_id,
)


_SAMPLE_TRIPLE = {
    "entity_id": "test-entity",
    "concept": "vendor.name",
    "property": "name",
    "value": "Acme Corp",
    "source_system": "netsuite",
    "confidence_score": 0.95,
    "confidence_tier": "exact",
}


def _make_req(triples_count: int = 1, **overrides) -> DCLPushRequest:
    triples = [dict(_SAMPLE_TRIPLE) for _ in range(triples_count)]
    kw = dict(
        tenant_id="00000000-0000-0000-0000-000000000001",
        entity_id="test-entity",
        dcl_ingest_id=make_dcl_ingest_id(),
        triples=triples,
        run_mode="Dev",
    )
    kw.update(overrides)
    return DCLPushRequest(**kw)


def test_make_dcl_ingest_id_is_a_uuid():
    """make_dcl_ingest_id always returns a parseable UUID string."""
    import uuid as _u
    s = make_dcl_ingest_id()
    parsed = _u.UUID(s)  # raises if not a UUID
    assert str(parsed) == s


def test_push_empty_triples_returns_zero_count():
    """Empty triples short-circuits — no HTTP call required."""
    p = DCLPusher(base_url="http://dcl.invalid")
    req = _make_req(triples_count=0)
    result = p.push(req)
    assert result.triples_written == 0
    assert result.batch_count == 0
    assert result.dcl_ingest_id == req.dcl_ingest_id


def test_push_happy_path(monkeypatch):
    """201 from DCL is parsed; triples_written comes from the response body."""
    captured = {}

    class _OK:
        status_code = 201
        text = '{"triples_written": 7, "dcl_ingest_id": "x"}'
        def json(self):
            return {"triples_written": 7}

    def _post(self, url, *, json):
        captured["url"] = url
        captured["body"] = json
        return _OK()

    monkeypatch.setattr(httpx.Client, "post", _post)
    p = DCLPusher(base_url="http://dcl.invalid")
    req = _make_req(triples_count=3, source_run_tag="aam_test")
    result = p.push(req)
    assert result.triples_written == 7
    assert result.batch_count == 1
    # First batch is sent without ?append=true
    assert "append=true" not in captured["url"]
    assert captured["body"]["tenant_id"] == req.tenant_id
    assert captured["body"]["dcl_ingest_id"] == req.dcl_ingest_id
    assert captured["body"]["source_run_tag"] == "aam_test"
    assert len(captured["body"]["triples"]) == 3


def test_push_4xx_raises_immediately_no_retry(monkeypatch):
    """Validation errors must surface immediately; retrying a 422 is pointless."""
    call_count = {"n": 0}

    class _Bad:
        status_code = 422
        text = '{"error":"UNMAPPED_DOMAIN","message":"domain x not mapped"}'

    def _post(self, url, *, json):
        call_count["n"] += 1
        return _Bad()

    monkeypatch.setattr(httpx.Client, "post", _post)
    p = DCLPusher(base_url="http://dcl.invalid")
    with pytest.raises(DCLPushError) as exc_info:
        p.push(_make_req(triples_count=1))
    assert call_count["n"] == 1, "4xx must not retry"
    assert exc_info.value.status_code == 422
    assert "UNMAPPED_DOMAIN" in str(exc_info.value)


def test_push_5xx_retries_then_raises(monkeypatch):
    """5xx retries up to max_retries+1 attempts, then raises."""
    call_count = {"n": 0}

    class _Down:
        status_code = 503
        text = '{"detail":{"error":"INGEST_DB_ERROR","message":"db down"}}'

    def _post(self, url, *, json):
        call_count["n"] += 1
        return _Down()

    monkeypatch.setattr(httpx.Client, "post", _post)
    p = DCLPusher(base_url="http://dcl.invalid", max_retries=2)
    with pytest.raises(DCLPushError) as exc_info:
        p.push(_make_req(triples_count=1))
    assert call_count["n"] == 3  # initial + 2 retries
    assert "db down" in str(exc_info.value)


def test_push_5xx_then_success(monkeypatch):
    """A transient 5xx that recovers on retry returns the success count."""
    calls = {"n": 0}

    class _Down:
        status_code = 503
        text = "transient"

    class _OK:
        status_code = 201
        text = '{"triples_written": 1}'
        def json(self):
            return {"triples_written": 1}

    def _post(self, url, *, json):
        calls["n"] += 1
        if calls["n"] < 2:
            return _Down()
        return _OK()

    monkeypatch.setattr(httpx.Client, "post", _post)
    p = DCLPusher(base_url="http://dcl.invalid", max_retries=3)
    result = p.push(_make_req(triples_count=1))
    assert result.triples_written == 1
    assert calls["n"] == 2


def test_push_network_error_retries_then_raises(monkeypatch):
    """ConnectError exhausts retries then raises with an actionable message."""
    calls = {"n": 0}

    def _post(self, url, *, json):
        calls["n"] += 1
        raise httpx.ConnectError("connection refused", request=None)

    monkeypatch.setattr(httpx.Client, "post", _post)
    p = DCLPusher(base_url="http://dcl.invalid", max_retries=2)
    with pytest.raises(DCLPushError) as exc_info:
        p.push(_make_req(triples_count=1))
    assert calls["n"] == 3
    msg = str(exc_info.value)
    assert "ConnectError" in msg or "connection refused" in msg
    assert "no direct-PG fallback" in msg


def test_push_batches_use_append_true_after_batch_zero(monkeypatch):
    """When triples exceed batch_size, batches 1..N must send ?append=true so
    they land on the same dcl_ingest_id.
    """
    seen_urls = []

    class _OK:
        status_code = 201
        text = '{"triples_written": 2}'
        def json(self):
            return {"triples_written": 2}

    def _post(self, url, *, json):
        seen_urls.append(url)
        return _OK()

    monkeypatch.setattr(httpx.Client, "post", _post)
    p = DCLPusher(base_url="http://dcl.invalid", batch_size=2)
    req = _make_req(triples_count=5)
    result = p.push(req)
    # 5 triples / batch_size 2 = 3 batches (2, 2, 1)
    assert result.batch_count == 3
    assert len(seen_urls) == 3
    assert "append=true" not in seen_urls[0]
    assert "append=true" in seen_urls[1]
    assert "append=true" in seen_urls[2]
