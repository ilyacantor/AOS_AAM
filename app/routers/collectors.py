"""
Collectors Router — collector execution and observation processing.
"""
import logging

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from ..db import (
    list_collectors,
    list_candidates,
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
from ..services.matching_service import match_candidate as match_candidate_service

_log = logging.getLogger("aam.infer")

router = APIRouter(tags=["Collectors"])


@router.get("/api/aam/collectors")
async def get_collectors():
    """List all collectors."""
    collectors = list_collectors()
    return {"collectors": collectors, "count": len(collectors)}


@router.post("/api/aam/infer")
async def infer_pipes():
    """Process pending observations AND unmatched AOD candidates into pipes.

    Two data paths feed this endpoint:
      1. Adapter-collected observations (observations table, processed=0)
      2. AOD handoff candidates that haven't been matched yet

    Previously only path 1 was wired, so clicking "Run Inference" after an
    AOD handoff always returned 0 pipes.
    """
    from ..main import preset_loader

    pipes_from_obs = 0
    pipes_from_candidates = 0
    match_failures = []

    # ---- Path 1: adapter observations (legacy) ----
    observations = get_unprocessed_observations()
    if observations:
        policies = preset_loader.get_governance_policies()
        pii_policy = policies.get("pii_redaction", "optional")

        redacted_observations = []
        for obs in observations:
            redacted_observations.append(redact_pii_from_observation(obs, policy=pii_policy))

        inferred_pipes = infer_pipes_from_observations(redacted_observations)
        for pipe in inferred_pipes:
            create_pipe(pipe)
            pipes_from_obs += 1

        for obs in observations:
            mark_observation_processed(obs["observation_id"])

    # ---- Path 2: unmatched AOD candidates ----
    unmatched = [
        c for c in list_candidates()
        if not c.get("matched_pipe_id") and c.get("status") not in ("deferred",)
    ]
    for candidate in unmatched:
        cid = candidate["candidate_id"]
        try:
            result = match_candidate_service(cid, None, preset_loader)
            if result.get("matched_pipe_id"):
                pipes_from_candidates += 1
        except (ValueError, PermissionError) as exc:
            match_failures.append({"candidate_id": cid, "reason": str(exc)})
            _log.debug("Candidate %s not matched: %s", cid, exc)

    total_pipes = pipes_from_obs + pipes_from_candidates

    if total_pipes == 0 and not observations and not unmatched:
        return {"message": "Nothing to process — no observations or unmatched candidates", "pipes_created": 0}

    return {
        "message": "Inference complete",
        "pipes_created": total_pipes,
        "from_observations": pipes_from_obs,
        "from_candidates": pipes_from_candidates,
        "candidates_unmatched": len(match_failures),
        "unmatched_reasons": match_failures[:10],  # first 10 for diagnostics
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
