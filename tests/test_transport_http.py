"""Unit tests for HTTPTransport — auth injection + fetch_records shape."""

from __future__ import annotations

import json

import pytest

from app.transport.http import HTTPTransport, HTTPTransportError, TransportRecord


def _fake_request(captured: dict):
    def _request(method, url, headers, body):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["body"] = json.loads(body) if body else None
        return {
            "source_system": "Salesforce",
            "vendor": "Workato",
            "records": [
                {"id": "rec-1", "account_id": "ACC-1", "account_name": "X"},
                {"id": "rec-2", "account_id": "ACC-2", "account_name": "Y"},
            ],
        }
    return _request


def test_fetch_records_returns_transport_records():
    captured: dict = {}
    transport = HTTPTransport(
        base_url="http://stub",
        auth_method="api_key",
        auth_credentials={"api_key": "k1"},
        request_fn=_fake_request(captured),
    )
    out = transport.fetch_records(pipe_id="p-1", path="/workato/api/recipes/wk-1/callable")
    assert len(out) == 2
    assert all(isinstance(r, TransportRecord) for r in out)
    assert out[0].pipe_id == "p-1"
    assert out[0].record_key == "rec-1"
    assert out[0].source_system == "Salesforce"
    # Transport strips only _-prefixed metadata keys; "id" remains in payload.
    assert out[0].payload["account_id"] == "ACC-1"
    assert out[0].payload["id"] == "rec-1"


def test_fetch_records_loud_fails_on_missing_records_field():
    def bad_request(*_args, **_kwargs):
        return {"oops": "no records"}
    transport = HTTPTransport(base_url="http://stub", request_fn=bad_request, retry_budget=1)
    with pytest.raises(HTTPTransportError):
        transport.fetch_records(pipe_id="p-1", path="/x")


def test_auth_headers_api_key():
    transport = HTTPTransport(
        base_url="http://stub", auth_method="api_key",
        auth_credentials={"api_key": "abc"}, request_fn=lambda *a, **k: {"records": []},
    )
    captured: dict = {}
    transport._request_fn = _fake_request(captured)
    transport.fetch_records(pipe_id="p", path="/x")
    assert captured["headers"]["X-API-Key"] == "abc"


def test_auth_headers_oauth2_bearer():
    captured: dict = {}
    transport = HTTPTransport(
        base_url="http://stub", auth_method="oauth2_bearer",
        auth_credentials={"token": "tok"}, request_fn=_fake_request(captured),
    )
    transport.fetch_records(pipe_id="p", path="/x")
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_unsupported_auth_method_raises():
    with pytest.raises(HTTPTransportError):
        HTTPTransport(base_url="http://stub", auth_method="kerberos")
