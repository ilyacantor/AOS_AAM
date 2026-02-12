"""
Presets Router — enterprise maturity preset configuration.
"""
from fastapi import APIRouter, HTTPException

from ..models import FabricPlane
from ..preset_config import EnterpriseMaturity

config_router = APIRouter(prefix="/api/preset-config", tags=["Preset Config"])


@config_router.get("")
async def get_current_preset_config():
    """Get the current enterprise preset configuration."""
    from ..main import preset_loader
    config = preset_loader.current_config
    return {
        "preset_id": config.preset_id,
        "name": config.name,
        "description": config.description,
        "primary_plane": config.primary_plane.value,
        "allowed_planes": [p.value for p in config.allowed_planes],
        "direct_access_allowed": config.direct_app_access,
        "policies": config.policies,
    }


@config_router.post("/{preset_name}/activate")
async def activate_preset(preset_name: str):
    """Activate an enterprise preset."""
    from ..main import preset_loader, adapter_registry

    preset_map = {
        "scrappy": EnterpriseMaturity.SCRAPPY,
        "early_scrappy": EnterpriseMaturity.SCRAPPY,
        "ipaas_centric": EnterpriseMaturity.IPAAS_CENTRIC,
        "ipaas-centric": EnterpriseMaturity.IPAAS_CENTRIC,
        "platform_oriented": EnterpriseMaturity.PLATFORM_ORIENTED,
        "platform-oriented": EnterpriseMaturity.PLATFORM_ORIENTED,
        "warehouse_centric": EnterpriseMaturity.WAREHOUSE_CENTRIC,
        "warehouse-centric": EnterpriseMaturity.WAREHOUSE_CENTRIC,
    }
    preset = preset_map.get(preset_name.lower())
    if not preset:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset: {preset_name}. Valid: scrappy, ipaas_centric, platform_oriented, warehouse_centric",
        )

    preset_loader.set_preset(preset)

    for adapter in adapter_registry.values():
        await adapter.disconnect()
    adapter_registry.clear()

    config = preset_loader.current_config
    return {
        "activated": preset_name,
        "preset_id": config.preset_id,
        "name": config.name,
        "primary_plane": config.primary_plane.value,
        "allowed_planes": [p.value for p in config.allowed_planes],
        "direct_access_allowed": config.direct_app_access,
        "adapters_cleared": True,
    }


@config_router.get("/all")
async def list_all_preset_configs():
    """List all available enterprise preset configurations."""
    from ..main import preset_loader
    return {"presets": preset_loader.list_all_presets()}


@config_router.post("/validate-routing")
async def validate_routing(vendor: str, target_plane: str):
    """Validate if a routing decision is allowed under current preset."""
    from ..main import preset_loader

    try:
        plane_enum = FabricPlane(target_plane.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid plane: {target_plane}")

    allowed, reason = preset_loader.validate_candidate_routing(vendor, plane_enum)
    return {
        "vendor": vendor,
        "target_plane": target_plane,
        "allowed": allowed,
        "reason": reason,
        "current_preset": preset_loader.current_config.name,
    }
