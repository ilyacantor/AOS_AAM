"""
Presets Router — enterprise maturity preset configuration and seed data.
"""
import json
import os
import random
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from ..models import FabricPlane
from ..preset_config import EnterpriseMaturity
from ..db import (
    create_pipe,
    create_candidate,
    create_drift_event,
    clear_all_data,
    get_pipe_stats,
    list_candidates,
    get_connection,
)

PRESETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "samples", "presets")

# Preset config router
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


# Seed data router
seed_router = APIRouter(prefix="/api/presets", tags=["Presets"])


@seed_router.get("")
async def list_presets():
    """List available enterprise maturity presets."""
    presets = []
    if os.path.exists(PRESETS_DIR):
        for filename in os.listdir(PRESETS_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(PRESETS_DIR, filename)
                with open(filepath, "r") as f:
                    data = json.load(f)
                    presets.append({
                        "preset_id": data.get("preset_id", filename.replace(".json", "")),
                        "name": data.get("name", filename),
                        "description": data.get("description", ""),
                        "pipe_count": len(data.get("pipes", [])),
                        "candidate_count": len(data.get("candidates", [])),
                    })
    return {"presets": presets, "count": len(presets)}


@seed_router.get("/{preset_id}")
async def get_preset(preset_id: str):
    """Get details of a specific preset."""
    filepath = os.path.join(PRESETS_DIR, f"{preset_id}.json")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Preset not found")
    with open(filepath, "r") as f:
        data = json.load(f)
    return data


@seed_router.post("/{preset_id}/load")
async def load_preset(preset_id: str, clear_existing: bool = Query(True)):
    """Load a preset — populates database with sample data."""
    filepath = os.path.join(PRESETS_DIR, f"{preset_id}.json")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Preset not found")

    with open(filepath, "r") as f:
        data = json.load(f)

    if clear_existing:
        clear_all_data()

    pipes_created = 0
    candidates_created = 0
    drift_events_created = 0
    created_pipe_ids = []

    for pipe_data in data.get("pipes", []):
        provenance = {
            "discovered_by": f"preset:{preset_id}",
            "discovered_at": datetime.utcnow().isoformat(),
            "lineage_hints": [f"preset:{preset_id}"],
        }
        pipe_data["provenance"] = provenance
        result = create_pipe(pipe_data)
        created_pipe_ids.append(result["pipe_id"])
        pipes_created += 1

    for candidate_data in data.get("candidates", []):
        create_candidate(candidate_data)
        candidates_created += 1

    drift_samples = [
        ("schema", "field: user_id (integer)", "field: user_id (string)", "high", "Field type changed"),
        ("schema", "fields: [id, name, email]", "fields: [id, name, email, phone]", "low", "New field added"),
        ("freshness", "last_update: 2024-01-15", "last_update: 2023-12-01", "critical", "Data not updated for 45 days"),
        ("contract", "rate_limit: 1000/min", "rate_limit: 100/min", "high", "API rate limit reduced"),
        ("schema", "nullable: false", "nullable: true", "medium", "Field nullability changed"),
        ("freshness", "sync_interval: 1h", "sync_interval: 24h", "medium", "Sync frequency reduced"),
        ("contract", "auth: api_key", "auth: oauth2", "high", "Authentication method changed"),
    ]

    pipes_with_drift = random.sample(created_pipe_ids, min(len(created_pipe_ids) // 3 + 1, len(created_pipe_ids)))
    for pipe_id in pipes_with_drift:
        drift_type, old_val, new_val, severity, description = random.choice(drift_samples)
        drift_id = create_drift_event(pipe_id, drift_type, old_val, new_val, {"description": description})
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE drift_events SET severity = ? WHERE drift_id = ?", (severity, drift_id))
        conn.commit()
        conn.close()
        drift_events_created += 1

    return {
        "preset_id": preset_id,
        "name": data.get("name"),
        "pipes_created": pipes_created,
        "candidates_created": candidates_created,
        "drift_events_created": drift_events_created,
        "message": f"Preset '{data.get('name')}' loaded successfully",
    }
