"""Factory wiring — vendor -> (MCPClient, HTTPTransport).

Critical property: same code path for Workato and Boomi. The factory returns
identical tuple shapes for every supported vendor.
"""

from __future__ import annotations

import os

import pytest

from app.adapters.factory import get_mcp_pair_for_vendor, supported_vendors
from app.mcp.client import MCPClient
from app.mcp.shims import BoomiShim, WorkatoShim
from app.transport.http import HTTPTransport


def test_supported_vendors_includes_both():
    assert "workato" in supported_vendors()
    assert "boomi" in supported_vendors()


@pytest.mark.parametrize("vendor,expected_shim", [("workato", WorkatoShim), ("boomi", BoomiShim)])
def test_factory_returns_mcp_client_and_http_transport(monkeypatch, vendor, expected_shim):
    monkeypatch.setenv("HARNESS_MODE", "stub")
    monkeypatch.setenv("HARNESS_IPAAS_BASE_URL", "http://stub")
    discovery, transport = get_mcp_pair_for_vendor(vendor)
    assert isinstance(discovery, MCPClient)
    assert isinstance(transport, HTTPTransport)
    assert isinstance(discovery.shim, expected_shim)
    assert discovery.vendor == vendor


def test_factory_loud_fails_on_unknown_vendor(monkeypatch):
    monkeypatch.setenv("HARNESS_MODE", "stub")
    monkeypatch.setenv("HARNESS_IPAAS_BASE_URL", "http://stub")
    with pytest.raises(ValueError):
        get_mcp_pair_for_vendor("salesforce")


def test_factory_loud_fails_on_stub_mode_without_base_url(monkeypatch):
    monkeypatch.setenv("HARNESS_MODE", "stub")
    monkeypatch.delenv("HARNESS_IPAAS_BASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        get_mcp_pair_for_vendor("workato")
