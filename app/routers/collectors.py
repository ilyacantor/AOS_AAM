"""
Collectors Router — collector execution and observation processing.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from ..db import (
    list_collectors,
    get_unprocessed_observations,
    mark_observation_processed,
    create_collector_run,
    complete_collector_run,
    get_collector_run,
    list_collector_runs,
    create_pipe,
)
from ..inference import infer_pipes_from_observations
from ..pii_redaction import redact_pii_from_observation
from ..services.collector_service import run_adapter_collector

router = APIRouter(tags=["Collectors"])


@router.get("/api/aam/collectors")
async def get_collectors():
    """List all collectors."""
    collectors = list_collectors()
    return {"collectors": collectors, "count": len(collectors)}


@router.post("/api/aam/infer")
async def infer_pipes():
    """Process pending observations and create pipes."""
    from ..main import preset_loader

    observations = get_unprocessed_observations()
    if not observations:
        return {"message": "No pending observations", "pipes_created": 0, "pipes": []}

    policies = preset_loader.get_governance_policies()
    pii_policy = policies.get("pii_redaction", "optional")

    redacted_observations = []
    redaction_applied = 0
    for obs in observations:
        redacted_obs = redact_pii_from_observation(obs, policy=pii_policy)
        redacted_observations.append(redacted_obs)
        if redacted_obs.get("metadata", {}).get("pii_redacted"):
            redaction_applied += 1

    inferred_pipes = infer_pipes_from_observations(redacted_observations)

    created_pipes = []
    for pipe in inferred_pipes:
        action = pipe.pop("_action", "create")
        if action == "create":
            result = create_pipe(pipe)
            pipe["pipe_id"] = result["pipe_id"]
            pipe["version"] = result["version"]
            created_pipes.append(pipe)

    for obs in observations:
        mark_observation_processed(obs["observation_id"])

    return {
        "message": "Inference complete",
        "observations_processed": len(observations),
        "pipes_created": len(created_pipes),
        "pipes": created_pipes,
        "pii_redaction_policy": pii_policy,
        "observations_redacted": redaction_applied,
    }


@router.post("/api/collect/adapter/run")
async def run_adapter(request=None):
    """Run adapter collector against connected fabric planes."""
    from ..main import preset_loader, adapter_registry

    collector_id = "adapter-collector-001"
    run_id = create_collector_run(collector_id)

    try:
        if not adapter_registry:
            complete_collector_run(run_id, "failed", 0, "No adapters connected")
            raise HTTPException(
                status_code=400,
                detail="No adapters connected. Connect adapters first via /api/adapters/{plane_type}/connect",
            )
        result = await run_adapter_collector(collector_id, run_id, adapter_registry, preset_loader)
        return {"run_id": run_id, "collector": "adapter", **result}
    except HTTPException:
        raise
    except Exception as e:
        complete_collector_run(run_id, "failed", 0, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/collect/runs")
async def get_collector_runs(
    collector_id: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
):
    """List collector runs."""
    runs = list_collector_runs(collector_id=collector_id, limit=limit)
    return {"runs": runs, "count": len(runs)}


@router.get("/api/collect/runs/{run_id}")
async def get_single_collector_run(run_id: str):
    """Get a specific collector run."""
    run = get_collector_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
