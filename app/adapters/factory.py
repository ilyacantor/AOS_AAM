"""Fabric Adapter Factory.

Two functions:
  get_adapter_for_plane(plane, config)         — legacy plane-based factory, unchanged.
  get_mcp_pair_for_vendor(vendor, config)      — MCP-first factory for the demo.

The vendor factory returns (discovery_client, transport_client) where
discovery_client is an MCPClient wrapping a vendor shim and transport_client
is an HTTPTransport. Downstream code never branches on vendor — that is the
"same code path" property the demo enforces.

HARNESS_MODE switch:
  HARNESS_MODE=stub          -> route to local ipaas_stub on HARNESS_IPAAS_BASE_URL
  HARNESS_MODE unset / "live" -> route to real vendor base URL from config
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..mcp.client import MCPClient
from ..mcp.shim_base import VendorShimBase
from ..mcp.shims import BoomiShim, WorkatoShim
from ..models import FabricPlane
from ..transport.http import HTTPTransport
from .base import FabricAdapter
from .eventbus import EventBusAdapter
from .gateway import GatewayAdapter
from .ipaas import IPaaSAdapter
from .warehouse import WarehouseAdapter

# Single dispatch table — vendor -> shim class. No if/elif on vendor name.
_SHIM_REGISTRY: dict[str, type[VendorShimBase]] = {
    "workato": WorkatoShim,
    "boomi": BoomiShim,
}


def get_adapter_for_plane(
    fabric_plane: FabricPlane,
    config: Optional[Dict[str, Any]] = None,
) -> FabricAdapter:
    """Legacy plane-based factory. Unchanged."""
    config = config or {}
    adapter_map = {
        FabricPlane.IPAAS: IPaaSAdapter,
        FabricPlane.API_GATEWAY: GatewayAdapter,
        FabricPlane.EVENT_BUS: EventBusAdapter,
        FabricPlane.DATA_WAREHOUSE: WarehouseAdapter,
    }
    adapter_class = adapter_map.get(fabric_plane)
    if adapter_class is None:
        raise ValueError(f"Unknown fabric plane: {fabric_plane}")
    return adapter_class(config)


def _resolve_endpoint(vendor: str, instance_config: dict[str, Any]) -> str:
    """Return the base URL for a vendor — stub or live."""
    mode = (os.environ.get("HARNESS_MODE") or "").strip().lower()
    if mode == "stub":
        base = os.environ.get("HARNESS_IPAAS_BASE_URL", "").strip()
        if not base:
            raise RuntimeError(
                "HARNESS_MODE=stub set but HARNESS_IPAAS_BASE_URL is empty. "
                "Set it to the URL of the running ipaas_stub (e.g., http://127.0.0.1:8902)."
            )
        return base.rstrip("/")
    base = instance_config.get("endpoint") or instance_config.get("base_url")
    if not base:
        raise RuntimeError(
            f"Live vendor endpoint missing for vendor={vendor}. "
            "Set instance_config.endpoint or set HARNESS_MODE=stub."
        )
    return str(base).rstrip("/")


def get_mcp_pair_for_vendor(
    vendor: str,
    instance_config: Optional[Dict[str, Any]] = None,
) -> tuple[MCPClient, HTTPTransport]:
    """MCP-first factory. Returns (discovery_client, transport_client).

    Same return type for every vendor in _SHIM_REGISTRY. Downstream code
    consumes the tuple identically.
    """
    if not vendor or not vendor.strip():
        raise ValueError("get_mcp_pair_for_vendor: vendor is required")
    instance_config = instance_config or {}
    shim_cls = _SHIM_REGISTRY.get(vendor.strip().lower())
    if shim_cls is None:
        raise ValueError(
            f"get_mcp_pair_for_vendor: unsupported vendor='{vendor}'. "
            f"Supported: {sorted(_SHIM_REGISTRY.keys())}"
        )
    endpoint = _resolve_endpoint(vendor, instance_config)
    auth = dict(instance_config.get("auth") or {"api_key": "demo-key"})
    shim = shim_cls(endpoint=endpoint, auth=auth)
    discovery = MCPClient(vendor=vendor, shim=shim, auth_method="api_key", auth_credentials=auth)
    transport = HTTPTransport(base_url=endpoint, auth_method="api_key", auth_credentials=auth)
    return discovery, transport


def supported_vendors() -> list[str]:
    return sorted(_SHIM_REGISTRY.keys())
