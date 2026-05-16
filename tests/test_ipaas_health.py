"""4-state IPaaS health-check unit tests (WS-1 Block 1.4).

Eight tests: 4 health states × 2 vendors. Each test mocks the vendor REST endpoint
with httpx.MockTransport and asserts that IPaaSAdapter.check_health() returns the
correct health_state per WS-1 Block 1.3:

    reachable    — HTTP 200
    degraded     — HTTP 5xx or timeout
    unreachable  — connection refused / DNS failure
    auth_expired — HTTP 401/403 or missing env-var auth config

Operator-visible outcome: Fabrics-tab health badges render one of {reachable,
degraded, unreachable, auth_expired} per vendor card per the dispatch's 4-state
vocabulary; the badge value is read from this method.
"""
from __future__ import annotations

import asyncio
from typing import Callable
from unittest.mock import patch

import httpx
import pytest

from app.adapters.base import AdapterStatus
from app.adapters.ipaas import IPaaSAdapter


# ---------- env fixture: set every required var so absent-env is opt-in only ----------

@pytest.fixture(autouse=True)
def _ipaas_env(monkeypatch):
    monkeypatch.setenv("WORKATO_BASE_URL", "http://test-workato.local")
    monkeypatch.setenv("WORKATO_API_TOKEN", "test-workato-token")
    monkeypatch.setenv("BOOMI_BASE_URL", "http://test-boomi.local")
    monkeypatch.setenv("BOOMI_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("BOOMI_USERNAME", "test-user")
    monkeypatch.setenv("BOOMI_API_TOKEN", "test-boomi-token")


# ---------- transport helpers ----------

def _mock_async_client_factory(handler: Callable[[httpx.Request], httpx.Response]):
    """Return a patch context manager that swaps httpx.AsyncClient to one with a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    return patch.object(httpx.AsyncClient, "__init__", _init)


def _raises_handler(exc: BaseException):
    def _h(request: httpx.Request) -> httpx.Response:
        raise exc
    return _h


def _status_handler(status_code: int, body: str = ""):
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, text=body)
    return _h


def _run(coro):
    return asyncio.run(coro)


# ---------- workato — 4 states ----------

def test_workato_reachable():
    adapter = IPaaSAdapter({"vendor": "workato"})
    with _mock_async_client_factory(_status_handler(200, '{"result": []}')):
        result = _run(adapter.check_health())
    assert result.health_state == "reachable"
    assert result.status == AdapterStatus.CONNECTED
    assert result.error_message is None


def test_workato_degraded_5xx():
    adapter = IPaaSAdapter({"vendor": "workato"})
    with _mock_async_client_factory(_status_handler(503, "service unavailable")):
        result = _run(adapter.check_health())
    assert result.health_state == "degraded"
    assert result.status == AdapterStatus.DEGRADED
    assert "503" in (result.error_message or "")


def test_workato_unreachable_connect_error():
    adapter = IPaaSAdapter({"vendor": "workato"})
    with _mock_async_client_factory(_raises_handler(httpx.ConnectError("connection refused"))):
        result = _run(adapter.check_health())
    assert result.health_state == "unreachable"
    assert result.status == AdapterStatus.DISCONNECTED
    assert "connection refused" in (result.error_message or "").lower()


def test_workato_auth_expired_401():
    adapter = IPaaSAdapter({"vendor": "workato"})
    with _mock_async_client_factory(_status_handler(401, "unauthorized")):
        result = _run(adapter.check_health())
    assert result.health_state == "auth_expired"
    assert result.status == AdapterStatus.FAILED
    assert "401" in (result.error_message or "")


# ---------- boomi — 4 states ----------

def test_boomi_reachable():
    adapter = IPaaSAdapter({"vendor": "boomi"})
    with _mock_async_client_factory(_status_handler(200, "[]")):
        result = _run(adapter.check_health())
    assert result.health_state == "reachable"
    assert result.status == AdapterStatus.CONNECTED
    assert result.error_message is None


def test_boomi_degraded_timeout():
    adapter = IPaaSAdapter({"vendor": "boomi"})
    with _mock_async_client_factory(_raises_handler(httpx.ReadTimeout("read timeout"))):
        result = _run(adapter.check_health())
    assert result.health_state == "degraded"
    assert result.status == AdapterStatus.DEGRADED
    assert "timeout" in (result.error_message or "").lower()


def test_boomi_unreachable_dns():
    adapter = IPaaSAdapter({"vendor": "boomi"})
    with _mock_async_client_factory(_raises_handler(httpx.ConnectError("name or service not known"))):
        result = _run(adapter.check_health())
    assert result.health_state == "unreachable"
    assert result.status == AdapterStatus.DISCONNECTED


def test_boomi_auth_expired_403():
    adapter = IPaaSAdapter({"vendor": "boomi"})
    with _mock_async_client_factory(_status_handler(403, "forbidden")):
        result = _run(adapter.check_health())
    assert result.health_state == "auth_expired"
    assert result.status == AdapterStatus.FAILED
    assert "403" in (result.error_message or "")


# ---------- env-missing case (auth_expired via missing config) ----------

def test_workato_auth_expired_missing_env(monkeypatch):
    monkeypatch.delenv("WORKATO_API_TOKEN", raising=False)
    adapter = IPaaSAdapter({"vendor": "workato"})
    # No HTTP mock needed — RuntimeError raised before any client call.
    result = _run(adapter.check_health())
    assert result.health_state == "auth_expired"
    assert result.status == AdapterStatus.FAILED
    assert "WORKATO_API_TOKEN" in (result.error_message or "")
