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
        """
        Connect to API Gateway management plane.

        In production: Would authenticate to gateway admin API.
        Currently: Stub — no real connection.
        """
        _log.warning("Not implemented — no real connection")
        return False

    async def disconnect(self) -> bool:
        """Disconnect from API Gateway"""
        self._status = AdapterStatus.DISCONNECTED
        return True

    async def check_health(self) -> PlaneHealth:
        """Check API Gateway health"""
        _log.warning("Not implemented — no real connection")
        return PlaneHealth(
            status=AdapterStatus.DISCONNECTED,
            last_check=datetime.utcnow(),
        )

    async def discover_pipes(self) -> List[Dict[str, Any]]:
        """
        Discover API endpoints from Gateway.

        Returns observations for inference engine to process.
        """
        _log.warning("Not implemented — no real connection")
        return []

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
        """
        Self-heal API Gateway connection issues.

        Healing strategies:
        - connection_lost: Reconnect to gateway admin API
        - upstream_down: Mark upstream unhealthy, trigger failover
        - rate_limit_exhausted: Request limit increase or queue requests
        """
        return False

    def apply_governance_policy(self, policy: Dict[str, Any]) -> bool:
        """
        Apply governance at Gateway level.

        Examples:
        - Inject "Redact-PII" header
        - Enforce rate limits
        - Require authentication
        """
        return False
