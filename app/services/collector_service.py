"""
Collector Service — orchestrates collector execution and observation processing.
"""
from ..logger import get_logger
from ..db import (
    create_observation,
    create_collector_run,
    complete_collector_run,
    list_candidates,
)
from ..pii_redaction import redact_pii_from_observation

_log = get_logger("services.collector")


def _build_vendor_candidate_map() -> dict[str, str]:
    """Build a vendor_name (lowercase) → candidate_id lookup from all candidates.

    Single DB call upfront so observations can be linked to the candidate
    they belong to.  Adapters report source_system (often the vendor name);
    matching it here lights up Priority 1 in the DCL export cascade.
    """
    try:
        candidates = list_candidates()
        mapping: dict[str, str] = {}
        for c in candidates:
            vendor = (c.get("vendor_name") or "").strip().lower()
            if vendor and c.get("candidate_id"):
                mapping[vendor] = c["candidate_id"]
        return mapping
    except Exception as exc:
        _log.warning("Could not build vendor→candidate map: %s", exc)
        return {}


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

    # Pre-fetch candidate lookup so observations get linked
    vendor_to_candidate = _build_vendor_candidate_map()

    all_observations = []
    adapters_collected = []

    for plane_type, adapter in adapter_registry.items():
        health = await adapter.check_health()
        if health.status != AdapterStatus.CONNECTED:
            _log.warning(
                "Adapter %s (%s) skipped — status=%s, not CONNECTED. "
                "No observations will be collected from this plane.",
                plane_type,
                getattr(adapter, "plane_vendor", "?"),
                health.status,
            )
            continue

        observations = await adapter.discover_pipes()

        for obs in observations:
            source = obs.get("source_system", adapter.plane_vendor)
            # Link observation to candidate by matching source_system
            # against known vendor names.
            matched_candidate = vendor_to_candidate.get(
                (source or "").strip().lower()
            )

            obs_data = {
                "observation_id": obs.get("observation_id"),
                "collector_id": collector_id,
                "candidate_id": matched_candidate,
                "source_system": source,
                "endpoint_info": obs.get("endpoint_info", {}),
                "entity_hints": obs.get("entity_hints", []),
                "schema_sample": obs.get("schema_sample"),
                "metadata": {
                    "plane_type": plane_type,
                    "vendor": adapter.plane_vendor,
                },
            }
            obs_data = redact_pii_from_observation(obs_data)
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
