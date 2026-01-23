"""
FabricDriftDetector - Plane Connectivity Drift Detection

Unlike schema drift (data structure changes), fabric drift detects
connectivity and health issues at the Plane level.

AAM owns self-healing - does NOT delegate to Farm.

Drift Types:
- connection_lost: Plane connection dropped
- consumer_lag: Kafka consumer falling behind
- warehouse_suspended: Snowflake warehouse auto-suspended
- latency_spike: Abnormal response times
- auth_expired: Credentials expired
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
import uuid


class FabricDriftType(str, Enum):
    """Types of fabric plane drift"""
    CONNECTION_LOST = "connection_lost"
    CONSUMER_LAG = "consumer_lag"
    WAREHOUSE_SUSPENDED = "warehouse_suspended"
    LATENCY_SPIKE = "latency_spike"
    AUTH_EXPIRED = "auth_expired"
    WEBHOOK_FAILED = "webhook_failed"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_DOWN = "upstream_down"


class DriftSeverity(str, Enum):
    """Severity levels for drift events"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FabricDriftEvent(BaseModel):
    """A detected fabric plane drift event"""
    drift_id: str
    plane_type: str
    plane_vendor: str
    drift_type: FabricDriftType
    severity: DriftSeverity
    detected_at: datetime
    details: Dict[str, Any] = Field(default_factory=dict)
    auto_heal_attempted: bool = False
    auto_heal_success: Optional[bool] = None
    healed_at: Optional[datetime] = None
    acknowledged: bool = False
    suppressed: bool = False


@dataclass
class DriftThresholds:
    """Thresholds that trigger drift detection"""
    latency_ms_threshold: float = 1000.0
    consumer_lag_threshold: int = 10000
    connection_timeout_seconds: int = 30
    auth_expiry_warning_hours: int = 24


class FabricDriftDetector:
    """
    Detects connectivity drift on Fabric Planes.
    
    This is different from schema drift - it detects when:
    - A plane connection is lost or degraded
    - Consumer lag is too high (EventBus)
    - Warehouse is suspended (DataWarehouse)
    - Latency spikes beyond threshold
    
    AAM owns self-healing of these drift conditions.
    Farm is NOT involved - it's strictly a Test Oracle.
    """
    
    def __init__(self, thresholds: Optional[DriftThresholds] = None):
        self._thresholds = thresholds or DriftThresholds()
        self._drift_events: List[FabricDriftEvent] = []
        self._heal_history: List[Dict[str, Any]] = []
    
    def detect_connection_drift(
        self,
        plane_type: str,
        plane_vendor: str,
        is_connected: bool,
        error_message: Optional[str] = None
    ) -> Optional[FabricDriftEvent]:
        """Detect if a plane connection is lost"""
        if not is_connected:
            drift = FabricDriftEvent(
                drift_id=str(uuid.uuid4()),
                plane_type=plane_type,
                plane_vendor=plane_vendor,
                drift_type=FabricDriftType.CONNECTION_LOST,
                severity=DriftSeverity.CRITICAL,
                detected_at=datetime.utcnow(),
                details={"error": error_message or "Connection lost"}
            )
            self._drift_events.append(drift)
            return drift
        return None
    
    def detect_latency_drift(
        self,
        plane_type: str,
        plane_vendor: str,
        latency_ms: float
    ) -> Optional[FabricDriftEvent]:
        """Detect abnormal latency on a plane"""
        if latency_ms > self._thresholds.latency_ms_threshold:
            severity = DriftSeverity.MEDIUM
            if latency_ms > self._thresholds.latency_ms_threshold * 3:
                severity = DriftSeverity.HIGH
            if latency_ms > self._thresholds.latency_ms_threshold * 5:
                severity = DriftSeverity.CRITICAL
            
            drift = FabricDriftEvent(
                drift_id=str(uuid.uuid4()),
                plane_type=plane_type,
                plane_vendor=plane_vendor,
                drift_type=FabricDriftType.LATENCY_SPIKE,
                severity=severity,
                detected_at=datetime.utcnow(),
                details={
                    "latency_ms": latency_ms,
                    "threshold_ms": self._thresholds.latency_ms_threshold
                }
            )
            self._drift_events.append(drift)
            return drift
        return None
    
    def detect_consumer_lag_drift(
        self,
        plane_vendor: str,
        consumer_lag: int,
        consumer_group: str
    ) -> Optional[FabricDriftEvent]:
        """Detect Kafka consumer falling behind"""
        if consumer_lag > self._thresholds.consumer_lag_threshold:
            severity = DriftSeverity.MEDIUM
            if consumer_lag > self._thresholds.consumer_lag_threshold * 5:
                severity = DriftSeverity.HIGH
            if consumer_lag > self._thresholds.consumer_lag_threshold * 10:
                severity = DriftSeverity.CRITICAL
            
            drift = FabricDriftEvent(
                drift_id=str(uuid.uuid4()),
                plane_type="EVENT_BUS",
                plane_vendor=plane_vendor,
                drift_type=FabricDriftType.CONSUMER_LAG,
                severity=severity,
                detected_at=datetime.utcnow(),
                details={
                    "consumer_lag": consumer_lag,
                    "consumer_group": consumer_group,
                    "threshold": self._thresholds.consumer_lag_threshold
                }
            )
            self._drift_events.append(drift)
            return drift
        return None
    
    def detect_warehouse_suspended(
        self,
        plane_vendor: str,
        warehouse_name: str,
        is_suspended: bool
    ) -> Optional[FabricDriftEvent]:
        """Detect Snowflake/BigQuery warehouse suspension"""
        if is_suspended:
            drift = FabricDriftEvent(
                drift_id=str(uuid.uuid4()),
                plane_type="DATA_WAREHOUSE",
                plane_vendor=plane_vendor,
                drift_type=FabricDriftType.WAREHOUSE_SUSPENDED,
                severity=DriftSeverity.HIGH,
                detected_at=datetime.utcnow(),
                details={
                    "warehouse": warehouse_name,
                    "action_required": "wake_warehouse"
                }
            )
            self._drift_events.append(drift)
            return drift
        return None
    
    async def attempt_self_heal(
        self,
        drift: FabricDriftEvent,
        adapter
    ) -> bool:
        """
        Attempt to self-heal a drift condition.
        
        AAM owns self-healing - Farm is NOT involved.
        
        Args:
            drift: The drift event to heal
            adapter: The FabricAdapter to use for healing
            
        Returns:
            True if healing was successful
        """
        drift.auto_heal_attempted = True
        
        try:
            from .adapters.base import PlaneDrift
            
            plane_drift = PlaneDrift(
                drift_id=drift.drift_id,
                plane_type=drift.plane_type,
                drift_type=drift.drift_type.value,
                detected_at=drift.detected_at,
                details=drift.details
            )
            
            success = await adapter.self_heal(plane_drift)
            
            drift.auto_heal_success = success
            if success:
                drift.healed_at = datetime.utcnow()
            
            self._heal_history.append({
                "drift_id": drift.drift_id,
                "drift_type": drift.drift_type.value,
                "attempted_at": datetime.utcnow().isoformat(),
                "success": success
            })
            
            return success
            
        except Exception as e:
            drift.auto_heal_success = False
            self._heal_history.append({
                "drift_id": drift.drift_id,
                "drift_type": drift.drift_type.value,
                "attempted_at": datetime.utcnow().isoformat(),
                "success": False,
                "error": str(e)
            })
            return False
    
    def acknowledge_drift(self, drift_id: str) -> bool:
        """Acknowledge a drift event (operator workflow)"""
        for drift in self._drift_events:
            if drift.drift_id == drift_id:
                drift.acknowledged = True
                return True
        return False
    
    def suppress_drift(self, drift_id: str) -> bool:
        """Suppress a drift event (stop alerting)"""
        for drift in self._drift_events:
            if drift.drift_id == drift_id:
                drift.suppressed = True
                return True
        return False
    
    def get_active_drifts(self) -> List[FabricDriftEvent]:
        """Get all unresolved drift events"""
        return [
            d for d in self._drift_events
            if not d.suppressed and d.healed_at is None
        ]
    
    def get_drift_by_plane(self, plane_type: str) -> List[FabricDriftEvent]:
        """Get drift events for a specific plane type"""
        return [d for d in self._drift_events if d.plane_type == plane_type]
    
    def get_heal_history(self) -> List[Dict[str, Any]]:
        """Get history of self-healing attempts"""
        return self._heal_history
    
    def get_drift_stats(self) -> Dict[str, Any]:
        """Get statistics about drift events"""
        total = len(self._drift_events)
        healed = len([d for d in self._drift_events if d.healed_at])
        active = len(self.get_active_drifts())
        
        by_type = {}
        for drift in self._drift_events:
            t = drift.drift_type.value
            by_type[t] = by_type.get(t, 0) + 1
        
        by_plane = {}
        for drift in self._drift_events:
            p = drift.plane_type
            by_plane[p] = by_plane.get(p, 0) + 1
        
        return {
            "total_drifts": total,
            "healed": healed,
            "active": active,
            "heal_success_rate": healed / total if total > 0 else 0,
            "by_type": by_type,
            "by_plane": by_plane
        }
