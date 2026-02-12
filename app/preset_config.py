"""
PresetConfigLoader - Enterprise Maturity Pattern Configuration

Defines how AAM behaves based on the client's enterprise integration maturity.
Each preset routes to different Fabric Plane adapters and enforces different policies.

Presets:
- Preset 6 (Scrappy): Direct Point-to-Point via GatewayAdapter
- Preset 8 (iPaaS-Centric): Forces routing via IPaaSAdapter
- Preset 9 (Platform-Oriented): Prioritizes EventBusAdapter
- Preset 11 (Warehouse-Centric): WarehouseAdapter as Source of Truth
"""

from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass
from .models import FabricPlane


class EnterpriseMaturity(str, Enum):
    """Enterprise integration maturity levels"""
    SCRAPPY = "early_scrappy"
    IPAAS_CENTRIC = "ipaas_centric"
    PLATFORM_ORIENTED = "platform_oriented"
    WAREHOUSE_CENTRIC = "warehouse_centric"


@dataclass
class PresetConfig:
    """Configuration for an enterprise preset"""
    preset_id: str
    name: str
    description: str
    primary_plane: FabricPlane
    allowed_planes: List[FabricPlane]
    direct_app_access: bool
    policies: Dict[str, Any]
    adapter_config: Dict[str, Any]


class PresetConfigLoader:
    """
    Loads and manages enterprise preset configurations.
    
    Determines AAM behavior based on client maturity:
    - Which Fabric Planes are allowed
    - Whether direct app access is permitted
    - What governance policies to enforce
    - How to route connection candidates
    """
    
    PRESETS: Dict[EnterpriseMaturity, PresetConfig] = {
        EnterpriseMaturity.SCRAPPY: PresetConfig(
            preset_id="early_scrappy",
            name="Early/Scrappy Startup",
            description="Point-to-point, direct API calls. No iPaaS or streaming infrastructure.",
            primary_plane=FabricPlane.API_GATEWAY,
            allowed_planes=[FabricPlane.API_GATEWAY],
            direct_app_access=True,  # ONLY preset that allows direct app connections
            policies={
                "require_governance": False,
                "allow_unmanaged_apis": True,
                "pii_redaction": "optional"
            },
            adapter_config={
                "scrappy_mode": True,
                "vendor": "direct"
            }
        ),
        
        EnterpriseMaturity.IPAAS_CENTRIC: PresetConfig(
            preset_id="ipaas_centric",
            name="iPaaS-Centric Organization",
            description="Workato/MuleSoft control plane. Blocks direct API calls.",
            primary_plane=FabricPlane.IPAAS,
            allowed_planes=[FabricPlane.IPAAS, FabricPlane.API_GATEWAY],
            direct_app_access=False,  # Must go through iPaaS
            policies={
                "require_governance": True,
                "route_via_ipaas": True,
                "allow_unmanaged_apis": False,
                "pii_redaction": "required"
            },
            adapter_config={
                "vendor": "workato",
                "require_recipe_approval": True
            }
        ),
        
        EnterpriseMaturity.PLATFORM_ORIENTED: PresetConfig(
            preset_id="platform_oriented",
            name="Platform-Oriented (Event-Driven)",
            description="Kafka/EventBridge backbone. High-volume streaming ingestion.",
            primary_plane=FabricPlane.EVENT_BUS,
            allowed_planes=[FabricPlane.EVENT_BUS, FabricPlane.API_GATEWAY, FabricPlane.IPAAS],
            direct_app_access=False,
            policies={
                "require_governance": True,
                "prefer_streaming": True,
                "schema_registry_required": True,
                "pii_redaction": "required"
            },
            adapter_config={
                "vendor": "kafka",
                "consumer_group": "aam-platform-observer",
                "enable_schema_registry": True
            }
        ),
        
        EnterpriseMaturity.WAREHOUSE_CENTRIC: PresetConfig(
            preset_id="warehouse_centric",
            name="Warehouse-Centric (Analytics-First)",
            description="Snowflake/BigQuery as source of truth. Reverse ETL patterns.",
            primary_plane=FabricPlane.DATA_WAREHOUSE,
            allowed_planes=[FabricPlane.DATA_WAREHOUSE, FabricPlane.EVENT_BUS, FabricPlane.IPAAS],
            direct_app_access=False,
            policies={
                "require_governance": True,
                "warehouse_is_sot": True,
                "reverse_etl_enabled": True,
                "pii_redaction": "required",
                "column_masking": True
            },
            adapter_config={
                "vendor": "snowflake",
                "warehouse": "AAM_WAREHOUSE",
                "treat_as_sot": True
            }
        )
    }
    
    def __init__(self, current_preset: EnterpriseMaturity = EnterpriseMaturity.SCRAPPY):
        self._current_preset = current_preset
    
    @property
    def current_config(self) -> PresetConfig:
        """Get the current preset configuration"""
        return self.PRESETS[self._current_preset]
    
    def set_preset(self, preset: EnterpriseMaturity) -> None:
        """Change the active preset"""
        if preset not in self.PRESETS:
            raise ValueError(f"Unknown preset: {preset}")
        self._current_preset = preset
    
    def get_preset_config(self, preset_id: str) -> Optional[PresetConfig]:
        """Get configuration for a specific preset by ID"""
        for maturity, config in self.PRESETS.items():
            if config.preset_id == preset_id:
                return config
        return None
    
    def is_plane_allowed(self, plane: FabricPlane) -> bool:
        """Check if a fabric plane is allowed in current preset"""
        return plane in self.current_config.allowed_planes
    
    def is_direct_access_allowed(self) -> bool:
        """Check if direct app access is allowed (only Scrappy mode)"""
        return self.current_config.direct_app_access
    
    def get_routing_decision(self, candidate_category: str) -> FabricPlane:
        """
        Return the preset's primary fabric plane.

        NOTE: This no longer routes by application category (CRM, ERP, etc.).
        The app category tells you nothing about which integration infrastructure
        the enterprise deployed.  The preset's primary plane is returned as a
        default when AOD doesn't provide an explicit plane hint.
        """
        return self.current_config.primary_plane
    
    def get_governance_policies(self) -> Dict[str, Any]:
        """Get governance policies for current preset"""
        return self.current_config.policies
    
    def should_block_direct_api(self, vendor: str) -> bool:
        """
        Check if direct API access should be blocked for a vendor.
        
        In non-Scrappy modes, direct app connections are blocked.
        Candidate must be routed through appropriate Fabric Plane.
        """
        if self._current_preset == EnterpriseMaturity.SCRAPPY:
            return False  # Scrappy allows direct access
        
        return True
    
    def validate_candidate_routing(self, candidate_vendor: str, target_plane: FabricPlane) -> tuple[bool, str]:
        """
        Validate that a candidate can be routed to a target plane.
        
        Returns:
            (is_valid, reason)
        """
        if target_plane not in self.current_config.allowed_planes:
            return (False, f"Plane {target_plane} not allowed in {self._current_preset.value} mode")
        
        if target_plane == FabricPlane.API_GATEWAY:
            if not self.is_direct_access_allowed():
                return (False, f"Direct API access blocked in {self._current_preset.value} mode")
        
        return (True, "Routing allowed")
    
    def list_all_presets(self) -> List[Dict[str, Any]]:
        """List all available presets with summary info"""
        return [
            {
                "preset_id": config.preset_id,
                "name": config.name,
                "description": config.description,
                "primary_plane": config.primary_plane.value,
                "direct_app_access": config.direct_app_access
            }
            for config in self.PRESETS.values()
        ]
