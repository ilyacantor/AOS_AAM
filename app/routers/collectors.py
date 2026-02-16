"""
Collectors Router — collector execution and observation processing.
"""
import json
import logging
import uuid
from datetime import datetime

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
from ..db import supabase_client as sb
from ..inference import infer_pipes_from_observations
from ..pii_redaction import redact_pii_from_observation
from ..services.collector_service import run_adapter_collector
from ..services.matching_service import (
    match_candidate as match_candidate_service,
    infer_fabric_plane_for_candidate,
)

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

    Performance: pre-fetches all data upfront (2-3 HTTP calls total),
    runs inference in-memory, then batch-writes results.
    """
    pipes_from_obs = 0
    pipes_from_candidates = 0
    match_failures = []

    # ---- Path 1: adapter observations (legacy) ----
    observations = get_unprocessed_observations()
    if observations:
        redacted_observations = []
        for obs in observations:
            redacted_observations.append(redact_pii_from_observation(obs, policy="optional"))

        inferred_pipes = infer_pipes_from_observations(redacted_observations)
        for pipe in inferred_pipes:
            create_pipe(pipe)
            pipes_from_obs += 1

        for obs in observations:
            mark_observation_processed(obs["observation_id"])

    # ---- Path 2: unmatched AOD candidates (batch-optimized) ----
    # Pre-fetch ALL data in 2 HTTP calls instead of ~10 per candidate
    all_candidates = list_candidates()
    planes = sb.select("fabric_planes")
    plane_type_to_id = {}
    for p in planes:
        pt = p.get("plane_type")
        if pt and p.get("plane_id"):
            plane_type_to_id[pt] = p["plane_id"]

    unmatched = [
        c for c in all_candidates
        if not c.get("matched_pipe_id") and c.get("status") not in ("deferred",)
    ]

    if not unmatched:
        total_pipes = pipes_from_obs
        if total_pipes == 0 and not observations:
            return {"message": "Nothing to process — no observations or unmatched candidates", "pipes_created": 0}
        return {
            "message": "Inference complete",
            "pipes_created": total_pipes,
            "from_observations": pipes_from_obs,
            "from_candidates": 0,
            "candidates_unmatched": 0,
            "unmatched_reasons": [],
        }

    # Build vendor→existing_candidate lookup from already-matched candidates
    vendor_to_pipe: dict[str, str] = {}
    for c in all_candidates:
        if c.get("matched_pipe_id"):
            vendor_to_pipe[c["vendor_name"].lower()] = c["matched_pipe_id"]

    # Run inference in-memory for all unmatched candidates
    now = datetime.utcnow().isoformat()
    new_pipes: list[dict] = []
    new_versions: list[dict] = []
    candidate_updates: list[dict] = []

    for candidate in unmatched:
        cid = candidate["candidate_id"]
        vendor = (candidate.get("vendor_name") or "").strip()
        vendor_lower = vendor.lower()

        # Governance check (pure computation)
        execution_allowed = candidate.get("execution_allowed", True)
        action_type = candidate.get("action_type", "provision")
        if not execution_allowed or action_type == "inventory_only":
            match_failures.append({"candidate_id": cid, "reason": "Blocked by AOD governance"})
            continue

        try:
            # Inference cascade (pure computation — no DB calls)
            inferred_plane, confidence, routing_source = infer_fabric_plane_for_candidate(candidate)
            if not inferred_plane:
                inferred_plane = "API_GATEWAY"
                confidence = 0.0
                routing_source = "needs_operator_review"

            # Check for existing pipe by vendor (in-memory lookup)
            pipe_id = vendor_to_pipe.get(vendor_lower)
            if pipe_id:
                match_reason = f"Matched existing pipe ({routing_source})"
                score = max(confidence, 0.9)
            else:
                # Create new pipe — collect for batch insert
                pipe_id = str(uuid.uuid4())
                vendor_to_pipe[vendor_lower] = pipe_id

                transport_kind = "API"
                modality = "DECLARED_INTERFACE"
                if inferred_plane == "EVENT_BUS":
                    transport_kind = "EVENT_STREAM"
                    modality = "PASSIVE_SUBSCRIPTION"
                elif inferred_plane == "DATA_WAREHOUSE":
                    transport_kind = "TABLE"
                elif inferred_plane == "IPAAS":
                    transport_kind = "WEBHOOK"
                    modality = "CONTROL_PLANE"

                trust_labels = []
                if routing_source == "aod_explicit":
                    trust_labels.append("inferred:aod_explicit")
                elif routing_source == "needs_operator_review":
                    trust_labels.append("needs_operator_review")
                else:
                    trust_labels.append(f"inferred:{routing_source}")

                lineage = [f"candidate:{cid}", f"routed_via:{inferred_plane}",
                           f"routing_source:{routing_source}", f"confidence:{confidence}"]
                if candidate.get("aod_run_id"):
                    lineage.append(f"aod_run:{candidate['aod_run_id']}")

                provenance = {"discovered_by": "auto-match", "discovered_at": now, "lineage_hints": lineage}

                new_pipes.append({
                    "pipe_id": pipe_id,
                    "display_name": candidate.get("display_name") or vendor,
                    "fabric_plane": inferred_plane,
                    "modality": modality,
                    "source_system": vendor,
                    "transport_kind": transport_kind,
                    "endpoint_ref": json.dumps({}),
                    "entity_scope": json.dumps([]),
                    "identity_keys": json.dumps([]),
                    "change_semantics": "UNKNOWN",
                    "provenance": json.dumps(provenance),
                    "owner_signals": json.dumps([]),
                    "trust_labels": json.dumps(trust_labels),
                    "schema_info": None,
                    "freshness": None,
                    "access_info": None,
                    "version": 1,
                    "schema_hash": None,
                    "created_at": now,
                    "updated_at": now,
                })
                new_versions.append({
                    "version_id": str(uuid.uuid4()),
                    "pipe_id": pipe_id,
                    "version": 1,
                    "schema_hash": None,
                    "payload": json.dumps({"source_system": vendor, "fabric_plane": inferred_plane}),
                    "created_at": now,
                })

                match_reason = f"Created pipe ({vendor}) on {inferred_plane} ({routing_source}, conf={confidence})"
                score = confidence

            # Collect candidate update
            fabric_plane_id = plane_type_to_id.get(inferred_plane)
            update = {
                "candidate_id": cid,
                "matched_pipe_id": pipe_id,
                "match_score": score,
                "match_reason": match_reason,
                "status": "connected",
                "connected_via_plane": inferred_plane,
                "updated_at": now,
            }
            if fabric_plane_id:
                update["fabric_plane_id"] = fabric_plane_id
            candidate_updates.append(update)
            pipes_from_candidates += 1

        except Exception as exc:
            match_failures.append({"candidate_id": cid, "reason": str(exc)})
            _log.debug("Candidate %s not matched: %s", cid, exc)

    # Batch-write: pipes, versions, candidate updates
    if new_pipes:
        sb.insert_many("declared_pipes", new_pipes)
    if new_versions:
        sb.insert_many("pipe_versions", new_versions)
    # Fire all candidate updates concurrently (threaded) — 30 calls in
    # parallel instead of 30 sequential calls.
    update_pairs = []
    for upd in candidate_updates:
        cid = upd.pop("candidate_id")
        update_pairs.append(({"candidate_id": cid}, upd))
    sb.update_many_concurrent("connection_candidates", update_pairs)

    total_pipes = pipes_from_obs + pipes_from_candidates

    return {
        "message": "Inference complete",
        "pipes_created": total_pipes,
        "from_observations": pipes_from_obs,
        "from_candidates": pipes_from_candidates,
        "candidates_unmatched": len(match_failures),
        "unmatched_reasons": match_failures[:10],
    }


@router.post("/api/collect/adapter/run")
async def run_adapter(request=None):
    """Run adapter collector against connected fabric planes."""
    from ..main import adapter_registry

    collector_id = "adapter-collector-001"
    run_id = create_collector_run(collector_id)

    try:
        if not adapter_registry:
            complete_collector_run(run_id, "failed", 0, "No adapters connected")
            raise HTTPException(
                status_code=400,
                detail="No adapters connected. Connect adapters first via /api/adapters/{plane_type}/connect",
            )
        result = await run_adapter_collector(collector_id, run_id, adapter_registry)
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
