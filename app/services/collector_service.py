"""
Collector Service — orchestrates collector execution and observation processing.
"""
from ..logger import get_logger
from ..db import (
    create_observation,
    create_collector_run,
    complete_collector_run,
)
from ..pii_redaction import redact_pii_from_observation

_log = get_logger("services.collector")


async def run_adapter_collector(
    collector_id: str,
    run_id: str,
    adapter_registry: dict,
) -> dict:
    """
    Run all connected adapters, collect observations, and apply PII redaction.
    Returns a result dict with observations_created, adapters_collected, etc.
    """
    from ..models import AdapterStatus

    all_observations = []
    adapters_collected = []

    for plane_type, adapter in adapter_registry.items():
        health = await adapter.check_health()
        if health.status != AdapterStatus.CONNECTED:
            continue

        observations = await adapter.discover_pipes()

        for obs in observations:
            obs_data = {
                "observation_id": obs.get("observation_id"),
                "collector_id": collector_id,
                "candidate_id": None,
                "source_system": obs.get("source_system", adapter.plane_vendor),
                "endpoint_info": obs.get("endpoint_info", {}),
                "entity_hints": obs.get("entity_hints", []),
                "schema_sample": obs.get("schema_sample"),
                "metadata": {
                    "plane_type": plane_type,
                    "vendor": adapter.plane_vendor,
                },
            }
            obs_data = redact_pii_from_observation(obs_data, policy="optional")
            create_observation(obs_data)
            all_observations.append(obs_data)

        adapters_collected.append(plane_type)

    complete_collector_run(run_id, "completed", len(all_observations))
    return {
        "run_id": run_id,
        "status": "completed",
        "observations_created": len(all_observations),
        "adapters_collected": adapters_collected,
        "observations": all_observations,
    }
