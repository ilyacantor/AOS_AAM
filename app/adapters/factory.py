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


def get_adapter_for_preset(preset_id: str, config: Optional[Dict[str, Any]] = None) -> FabricAdapter:
    """
    Get the primary adapter for an enterprise preset.
    
    Preset routing:
    - early_scrappy (6): GatewayAdapter with scrappy_mode=True
    - ipaas_centric (8): IPaaSAdapter (blocks direct API calls)
    - platform_oriented (9): EventBusAdapter (prioritizes streaming)
    - warehouse_centric (11): WarehouseAdapter (authoritative Source of Truth)
    
    Args:
        preset_id: The enterprise preset identifier
        config: Optional additional configuration
        
    Returns:
        Appropriate FabricAdapter for the preset
    """
    config = config or {}
    
    preset_routing = {
        "early_scrappy": (GatewayAdapter, {"scrappy_mode": True}),
        "ipaas_centric": (IPaaSAdapter, {"vendor": "workato"}),
        "platform_oriented": (EventBusAdapter, {"vendor": "kafka"}),
        "warehouse_centric": (WarehouseAdapter, {"vendor": "snowflake"}),
    }
    
    if preset_id not in preset_routing:
        return GatewayAdapter({"scrappy_mode": True})
    
    adapter_class, default_config = preset_routing[preset_id]
    merged_config = {**default_config, **config}
    return adapter_class(merged_config)
