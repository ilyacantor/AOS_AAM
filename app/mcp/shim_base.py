"""Vendor Shim Base — abstract base for vendors that lack a native MCP server.

A shim presents the vendor's native REST API as MCP tool output JSON so AAM's
universal MCP client and translator work unchanged. Subclasses implement two
methods: list_discovery_tools() and invoke_tool(name, params).

Demo path: WorkatoShim and BoomiShim both subclass this. Same code path —
factory selects the shim instance by vendor name, and downstream code never
branches on vendor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VendorShimBase(ABC):
    """Abstract base for vendor-specific shims that present native APIs as MCP."""

    def __init__(self, vendor_name: str, endpoint: str, auth: dict[str, Any] | None = None):
        if not vendor_name or not vendor_name.strip():
            raise ValueError("VendorShimBase requires non-empty vendor_name")
        if not endpoint or not endpoint.strip():
            raise ValueError(f"VendorShimBase requires non-empty endpoint (vendor={vendor_name})")
        self.vendor_name = vendor_name
        self.endpoint = endpoint.rstrip("/")
        self.auth = auth or {}

    @abstractmethod
    def list_discovery_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions in MCP format.

        Each entry: {"name": str, "description": str, "input_schema": dict}.
        The universal MCP client treats these identically to native MCP tools.
        """

    @abstractmethod
    def invoke_tool(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke a discovery tool. Return MCP tool output JSON.

        Output shape: {"content": [...], "isError": bool, "structured": dict}.
        The translator reads structured.items[*] to build DeclaredPipes.
        Raises on transport / auth failure — no silent fallback.
        """

    def health_check(self) -> dict[str, Any]:
        """Default health check — subclasses may override."""
        return {"vendor": self.vendor_name, "endpoint": self.endpoint, "status": "reachable"}
