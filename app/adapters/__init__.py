"""
AAM Fabric Plane Adapters

AAM connects ONLY to Fabric Planes that aggregate data, NOT to individual SaaS apps.

The 4 Fabric Planes:
1. IPAAS: (Workato, MuleSoft) -> Control plane for integration flows
2. API_GATEWAY: (Kong, Apigee) -> Direct managed API access
3. EVENT_BUS: (Kafka, EventBridge) -> Streaming backbone
4. DATA_WAREHOUSE: (Snowflake, BigQuery) -> Source of Truth storage

AAM owns Self-Healing of Plane connections.
"""

from .base import FabricAdapter, AdapterStatus, PlaneHealth
from .ipaas import IPaaSAdapter
from .gateway import GatewayAdapter
from .eventbus import EventBusAdapter
from .warehouse import WarehouseAdapter
from .factory import get_adapter_for_plane

# WP12b: registry of fabric vendors with real implementations end-to-end
# (adapter + webhook handler + UI surface). The /aam/fabrics UI iterates
# this set; adding a new vendor = implement + handler + add slug here.
IMPLEMENTED_VENDORS: set[str] = {"workato", "boomi"}

__all__ = [
    "FabricAdapter",
    "AdapterStatus",
    "PlaneHealth",
    "IPaaSAdapter",
    "GatewayAdapter",
    "EventBusAdapter",
    "WarehouseAdapter",
    "get_adapter_for_plane",
    "IMPLEMENTED_VENDORS",
]
