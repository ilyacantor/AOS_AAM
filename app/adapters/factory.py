"""
Fabric Adapter Factory

Creates the appropriate adapter based on Fabric Plane type.
"""

from typing import Dict, Any, Optional
from ..models import FabricPlane
from .base import FabricAdapter
from .ipaas import IPaaSAdapter
from .gateway import GatewayAdapter
from .eventbus import EventBusAdapter
from .warehouse import WarehouseAdapter


def get_adapter_for_plane(
    fabric_plane: FabricPlane,
    config: Optional[Dict[str, Any]] = None
) -> FabricAdapter:
    """
    Factory method to create the appropriate adapter for a Fabric Plane.
    
    Args:
        fabric_plane: The fabric plane type
        config: Optional configuration for the adapter
        
    Returns:
        Appropriate FabricAdapter subclass instance
        
    Raises:
        ValueError: If fabric plane type is unknown
    """
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
