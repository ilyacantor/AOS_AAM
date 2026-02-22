"""
GatewayAdapter - API Gateway Plane

Connects to API Gateways (Kong, Apigee, AWS API Gateway)
to inventory managed API endpoints.

Modality: Proxy/REST - direct API access through the gateway.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base import FabricAdapter, AdapterStatus, PlaneHealth, PlaneDrift

_log = logging.getLogger("aam.adapter.gateway")


class GatewayAdapter(FabricAdapter):
    """
    Adapter for API Gateway Fabric Plane.

    Connects to API gateway management planes to:
    - Discover registered API endpoints
    - Monitor API health and latency
    - Apply governance policies (rate limiting, PII redaction)
    - Self-heal connection disruptions

    Supported vendors: Kong, Apigee, AWS API Gateway, Azure APIM
    """

    SUPPORTED_VENDORS = ["kong", "apigee", "aws_apigateway", "azure_apim"]

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._vendor = config.get("vendor", "kong").lower()
        self._apis_discovered: List[Dict] = []
        self._governance_policies: List[Dict] = []

    @property
    def plane_type(self) -> str:
        return "API_GATEWAY"

    @property
    def plane_vendor(self) -> str:
        return self._vendor

    async def connect(self) -> bool:
        """Connect to API Gateway management plane."""
        raise NotImplementedError(
            f"GatewayAdapter.connect() not implemented for vendor '{self._vendor}'. "
            "Implement real gateway authentication before calling connect()."
        )

    async def disconnect(self) -> bool:
        """Disconnect from API Gateway"""
        self._status = AdapterStatus.DISCONNECTED
        return True

    async def check_health(self) -> PlaneHealth:
        """Check API Gateway health."""
        raise NotImplementedError(
            f"GatewayAdapter.check_health() not implemented for vendor '{self._vendor}'."
        )

    async def discover_pipes(self) -> List[Dict[str, Any]]:
        """Discover API endpoints from Gateway."""
        raise NotImplementedError(
            f"GatewayAdapter.discover_pipes() not implemented for vendor '{self._vendor}'."
        )

    def _extract_entities_from_endpoints(self, api: Dict) -> List[str]:
        """Extract entity hints from API endpoint paths"""
        entities = []
        endpoints = api.get("endpoints", [])
        for ep in endpoints:
            parts = ep.split("/")
            for part in parts:
                if part and not part.startswith("v") and part not in ["sobjects", "objects", "api"]:
                    entities.append(part)
        return entities

    async def self_heal(self, drift: PlaneDrift) -> bool:
        """Self-heal API Gateway connection issues."""
        raise NotImplementedError(
            f"GatewayAdapter.self_heal() not implemented for vendor '{self._vendor}'. "
            f"Drift type: {drift.drift_type}"
        )

    def apply_governance_policy(self, policy: Dict[str, Any]) -> bool:
        """Apply governance at Gateway level."""
        raise NotImplementedError(
            f"GatewayAdapter.apply_governance_policy() not implemented for vendor '{self._vendor}'."
        )
