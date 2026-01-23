"""
FabricAdapter Base Class

Polymorphic interface for connecting to Fabric Planes.
AAM connects to Planes, NOT to individual SaaS applications.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel


class AdapterStatus(str, Enum):
    """Status of a Fabric Plane adapter connection"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    FAILED = "failed"
    HEALING = "healing"


class PlaneHealth(BaseModel):
    """Health status of a Fabric Plane connection"""
    status: AdapterStatus
    last_check: datetime
    latency_ms: Optional[float] = None
    error_message: Optional[str] = None
    metrics: Dict[str, Any] = {}


class PlaneDrift(BaseModel):
    """Connectivity drift event for a Fabric Plane"""
    drift_id: str
    plane_type: str
    drift_type: str  # "connection_lost", "latency_spike", "consumer_lag", "warehouse_suspended"
    detected_at: datetime
    details: Dict[str, Any] = {}
    auto_healed: bool = False
    healed_at: Optional[datetime] = None


class FabricAdapter(ABC):
    """
    Abstract base class for Fabric Plane adapters.
    
    AAM connects ONLY to Fabric Planes, not individual apps.
    Each adapter implements plane-specific connection, discovery, and self-healing.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize adapter with plane configuration.
        
        Args:
            config: Plane-specific configuration (NO SECRETS - refs only)
        """
        self.config = config
        self._status = AdapterStatus.DISCONNECTED
        self._last_health_check: Optional[datetime] = None
        self._error_message: Optional[str] = None
    
    @property
    def status(self) -> AdapterStatus:
        return self._status
    
    @property
    @abstractmethod
    def plane_type(self) -> str:
        """Return the fabric plane type (IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE)"""
        pass
    
    @property
    @abstractmethod
    def plane_vendor(self) -> str:
        """Return the vendor name (e.g., Workato, Kong, Kafka, Snowflake)"""
        pass
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to the Fabric Plane.
        
        Returns:
            True if connection successful
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """
        Gracefully disconnect from the Fabric Plane.
        
        Returns:
            True if disconnect successful
        """
        pass
    
    @abstractmethod
    async def check_health(self) -> PlaneHealth:
        """
        Check health of the Plane connection.
        
        Returns:
            PlaneHealth with current status and metrics
        """
        pass
    
    @abstractmethod
    async def discover_pipes(self) -> List[Dict[str, Any]]:
        """
        Discover available data pipes from the Plane.
        
        Returns:
            List of pipe observations (to be processed by inference)
        """
        pass
    
    @abstractmethod
    async def self_heal(self, drift: PlaneDrift) -> bool:
        """
        Attempt to self-heal a detected drift condition.
        
        AAM owns self-healing - does NOT delegate to Farm.
        
        Args:
            drift: The detected drift condition
            
        Returns:
            True if healing successful
        """
        pass
    
    @abstractmethod
    def apply_governance_policy(self, policy: Dict[str, Any]) -> bool:
        """
        Apply governance policy at the Plane level.
        
        Example: Inject "Redact-PII" header into Gateway requests
        
        Args:
            policy: Policy configuration
            
        Returns:
            True if policy applied successfully
        """
        pass
    
    def get_health(self) -> PlaneHealth:
        """Get current health status"""
        return PlaneHealth(
            status=self._status,
            last_check=self._last_health_check or datetime.utcnow(),
            error_message=self._error_message
        )
