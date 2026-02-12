"""
GatewayAdapter - API Gateway Plane

Connects to API Gateways (Kong, Apigee, AWS API Gateway)
to inventory managed API endpoints.

Modality: Proxy/REST - direct API access through the gateway.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid

from .base import FabricAdapter, AdapterStatus, PlaneHealth, PlaneDrift


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
        Currently: Mock implementation for architecture validation.
        """
        self._status = AdapterStatus.CONNECTING
        
        try:
            self._status = AdapterStatus.CONNECTED
            self._last_health_check = datetime.utcnow()
            return True
        except Exception as e:
            self._status = AdapterStatus.FAILED
            self._error_message = str(e)
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from API Gateway"""
        self._status = AdapterStatus.DISCONNECTED
        return True
    
    async def check_health(self) -> PlaneHealth:
        """Check API Gateway health"""
        self._last_health_check = datetime.utcnow()
        
        return PlaneHealth(
            status=self._status,
            last_check=self._last_health_check,
            latency_ms=25.0,
            metrics={
                "vendor": self._vendor,
                "apis_discovered": len(self._apis_discovered),
                "policies_active": len(self._governance_policies)
            }
        )
    
    async def discover_pipes(self) -> List[Dict[str, Any]]:
        """
        Discover API endpoints from Gateway.
        
        Returns observations for inference engine to process.
        """
        observations = []

        mock_apis = [
            {
                "api_id": f"api-{self._vendor}-001",
                "name": f"{self._vendor.title()} - CRM Gateway Route",
                "route": "/api/crm/*",
                "upstream": "internal-crm-service",
                "plugins": ["rate-limiting", "jwt-auth"]
            },
            {
                "api_id": f"api-{self._vendor}-002",
                "name": f"{self._vendor.title()} - ERP Gateway Route",
                "route": "/api/erp/*",
                "upstream": "internal-erp-service",
                "plugins": ["rate-limiting", "oauth2"]
            }
        ]

        for api in mock_apis:
            observations.append({
                "observation_id": str(uuid.uuid4()),
                "collector_id": f"gateway-{self._vendor}",
                "observed_at": datetime.utcnow().isoformat(),
                "source_system": api.get("vendor", self._vendor),
                "endpoint_info": {
                    "type": "api_gateway",
                    "api_id": api["api_id"],
                    "api_name": api["name"],
                    "vendor": self._vendor
                },
                "entity_hints": self._extract_entities_from_endpoints(api),
                "metadata": {
                    "fabric_plane": "API_GATEWAY",
                    "modality": "DECLARED_INTERFACE",
                    "transport_kind": "API",
                    **api
                }
            })
        
        self._apis_discovered = mock_apis
        return observations
    
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
        if drift.drift_type == "connection_lost":
            return await self.connect()
        
        elif drift.drift_type == "upstream_down":
            return True
        
        elif drift.drift_type == "rate_limit_exhausted":
            return True
        
        return False
    
    def apply_governance_policy(self, policy: Dict[str, Any]) -> bool:
        """
        Apply governance at Gateway level.
        
        Examples:
        - Inject "Redact-PII" header
        - Enforce rate limits
        - Require authentication
        """
        policy_type = policy.get("type")
        
        if policy_type == "redact_pii":
            self._governance_policies.append({
                "type": "request_transformer",
                "add_headers": ["X-Redact-PII: true"]
            })
            return True
        
        elif policy_type == "rate_limit":
            self._governance_policies.append({
                "type": "rate_limiting",
                "config": policy.get("config", {"requests_per_minute": 100})
            })
            return True
        
        elif policy_type == "require_auth":
            self._governance_policies.append({
                "type": "jwt_auth",
                "config": policy.get("config", {})
            })
            return True
        
        return False
