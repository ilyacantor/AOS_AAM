"""
Collectors Router — collector execution and observation processing.
"""
import json
import logging
import time
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
from ..constants import CATEGORY_STANDARD_FIELDS, PLANE_STANDARD_FIELDS, INFRA_VENDOR_PLANE
from ..utils.operating_mode import get_operating_mode, OperatingMode

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
    _t_start = time.perf_counter()
    pipes_from_obs = 0
    pipes_from_candidates = 0
    match_failures = []

    # ---- Path 1: adapter observations (legacy) ----
    _t0 = time.perf_counter()
    observations = get_unprocessed_observations()
    if observations:
        redacted_observations = []
        for obs in observations:
            redacted_observations.append(redact_pii_from_observation(obs))

        inferred_pipes = infer_pipes_from_observations(redacted_observations)
        for pipe in inferred_pipes:
            create_pipe(pipe)
            pipes_from_obs += 1

        for obs in observations:
            mark_observation_processed(obs["observation_id"])

    _t_fetch_obs = time.perf_counter() - _t0

    # ---- Path 2: unmatched AOD candidates (batch-optimized) ----
    # Pre-fetch ALL data in 2 HTTP calls instead of ~10 per candidate
    _t0 = time.perf_counter()
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

    # Pre-fetch existing pipes so we can detect which ones need schema enrichment
    _t_fetch_cands = time.perf_counter() - _t0
    _t0 = time.perf_counter()
    existing_pipes_rows = sb.select("declared_pipes")
    existing_pipes_by_id: dict[str, dict] = {
        p["pipe_id"]: p for p in existing_pipes_rows if p.get("pipe_id")
    }

    # Run inference in-memory for all unmatched candidates
    _t_fetch_pipes = time.perf_counter() - _t0
    _t0 = time.perf_counter()
    now = datetime.utcnow().isoformat()
    new_pipes: list[dict] = []
    new_versions: list[dict] = []
    candidate_updates: list[dict] = []
    pipe_enrichments: list[tuple[dict, dict]] = []  # (filter, update_data)

    for candidate in unmatched:
        cid = candidate["candidate_id"]
        vendor = (candidate.get("vendor_name") or "").strip()
        vendor_lower = vendor.lower()

        # Governance check (pure computation)
        # Only explicit "provision" permits auto-connect. Any unknown or
        # unexpected action_type blocks — fail-safe against contract drift.
        execution_allowed = candidate.get("execution_allowed", True)
        action_type = candidate.get("action_type", "provision")
        if not execution_allowed or action_type != "provision":
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

                # --- Enrich existing pipe if it lacks schema content ---
                existing_pipe = existing_pipes_by_id.get(pipe_id)
                if existing_pipe:
                    ep_es = existing_pipe.get("entity_scope")
                    ep_ik = existing_pipe.get("identity_keys")
                    ep_si = existing_pipe.get("schema_info")
                    ep_es_list = json.loads(ep_es) if isinstance(ep_es, str) else (ep_es or [])
                    ep_ik_list = json.loads(ep_ik) if isinstance(ep_ik, str) else (ep_ik or [])
                    ep_si_dict = json.loads(ep_si) if isinstance(ep_si, str) else ep_si

                    needs_enrichment = (
                        not (isinstance(ep_es_list, list) and len(ep_es_list) > 0)
                        or not (isinstance(ep_ik_list, list) and len(ep_ik_list) > 0)
                        or not (isinstance(ep_si_dict, dict) and bool(ep_si_dict))
                    )

                    if needs_enrichment:
                        cat_lower = (candidate.get("category") or "other").lower()
                        enrich_fields: list[str] = []
                        if cat_lower == "other":
                            plane_for_vendor = INFRA_VENDOR_PLANE.get(vendor_lower)
                            if plane_for_vendor:
                                enrich_fields = list(PLANE_STANDARD_FIELDS.get(plane_for_vendor, []))
                        if not enrich_fields:
                            enrich_fields = list(CATEGORY_STANDARD_FIELDS.get(cat_lower, []))

                        if enrich_fields:
                            new_es = [f for f in enrich_fields if not f.endswith("_id")]
                            new_ik = [f for f in enrich_fields if f.endswith("_id")]
                            pipe_enrichments.append((
                                {"pipe_id": pipe_id},
                                {
                                    "entity_scope": json.dumps(new_es),
                                    "identity_keys": json.dumps(new_ik),
                                    "schema_info": json.dumps({"schema_version": "category_inferred"}),
                                    "updated_at": now,
                                },
                            ))
                            _log.info(
                                "Enriching existing pipe %s (%s) with %d fields from %s",
                                pipe_id, vendor, len(enrich_fields),
                                "plane_standard" if cat_lower == "other" else f"category:{cat_lower}",
                            )
            else:
                # Create new pipe — collect for batch insert.
                # Deterministic UUID: same (vendor, plane) always produces the
                # same pipe_id, surviving resets and re-inference cycles.
                pipe_id = str(uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"aam.pipe.{vendor_lower}.{inferred_plane}",
                ))
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

                # Derive entity_scope and identity_keys from category
                # and fabric plane.  Infrastructure vendors categorised
                # as "other" by AOD get plane-specific fields via
                # INFRA_VENDOR_PLANE lookup.
                cat_lower = (candidate.get("category") or "other").lower()
                inferred_fields: list[str] = []
                if cat_lower == "other":
                    plane_for_vendor = INFRA_VENDOR_PLANE.get(vendor_lower)
                    if plane_for_vendor:
                        inferred_fields = list(PLANE_STANDARD_FIELDS.get(plane_for_vendor, []))
                if not inferred_fields:
                    inferred_fields = list(CATEGORY_STANDARD_FIELDS.get(cat_lower, []))
                # entity_scope: non-key fields (semantic entities the pipe covers)
                entity_scope = [f for f in inferred_fields if not f.endswith("_id")]
                # identity_keys: fields that look like primary/foreign keys
                identity_keys = [f for f in inferred_fields if f.endswith("_id")]

                new_pipes.append({
                    "pipe_id": pipe_id,
                    "display_name": candidate.get("display_name") or vendor,
                    "fabric_plane": inferred_plane,
                    "modality": modality,
                    "source_system": vendor,
                    "transport_kind": transport_kind,
                    "endpoint_ref": json.dumps({}),
                    "entity_scope": json.dumps(entity_scope),
                    "identity_keys": json.dumps(identity_keys),
                    "change_semantics": "UNKNOWN",
                    "provenance": json.dumps(provenance),
                    "owner_signals": json.dumps([]),
                    "trust_labels": json.dumps(trust_labels),
                    "schema_info": json.dumps({"schema_version": "category_inferred"}) if inferred_fields else None,
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

    # Batch-write: pipes, versions, candidate updates, pipe enrichments
    _t_inference = time.perf_counter() - _t0
    _t0 = time.perf_counter()
    if new_pipes:
        sb.insert_many("declared_pipes", new_pipes)
    if new_versions:
        sb.insert_many("pipe_versions", new_versions)
    if pipe_enrichments:
        sb.update_many_concurrent("declared_pipes", pipe_enrichments)
        _log.info("Enriched %d existing pipes with schema content", len(pipe_enrichments))
    # Fire all candidate updates concurrently (threaded) — 30 calls in
    # parallel instead of 30 sequential calls.
    update_pairs = []
    for upd in candidate_updates:
        cid = upd.pop("candidate_id")
        update_pairs.append(({"candidate_id": cid}, upd))
    sb.update_many_concurrent("connection_candidates", update_pairs)

    _t_batch_write = time.perf_counter() - _t0

    total_pipes = pipes_from_obs + pipes_from_candidates

    # --- EAV triple conversion (non-fatal) ---
    _t0 = time.perf_counter()
    _t_handoff = 0.0
    _t_convert = 0.0
    _t_write = 0.0
    triple_write_result = None
    mode = get_operating_mode()
    try:
        from ..converters.triple_converter import (
            convert_inference_batch, generate_run_id, resolve_entity_id,
        )
        from ..db.triple_writer import write_triples_with_ledger

        # Resolve entity_id from most recent AOD handoff
        _th = time.perf_counter()
        handoffs = sb.select("aod_handoff_log", order="processed_at.desc", limit=1)
        _t_handoff = time.perf_counter() - _th
        snapshot_name = handoffs[0].get("snapshot_name") if handoffs else None
        aod_rid = handoffs[0].get("aod_run_id") if handoffs else None
        entity_id = resolve_entity_id(snapshot_name, aod_rid)

        if entity_id and (new_pipes or update_pairs):
            run_uuid, run_tag = generate_run_id()
            # Build connection data for triple conversion from update_pairs + original candidates
            cid_to_candidate = {c["candidate_id"]: c for c in unmatched}
            connection_data = []
            for filter_d, update_d in update_pairs:
                cid = filter_d["candidate_id"]
                orig = cid_to_candidate.get(cid, {})
                connection_data.append({
                    **update_d,
                    "vendor_name": orig.get("vendor_name"),
                    "category": orig.get("category"),
                })
            _tc = time.perf_counter()
            triple_dicts = convert_inference_batch(
                new_pipes, connection_data, planes, entity_id, run_uuid, run_tag,
            )
            _t_convert = time.perf_counter() - _tc
            if triple_dicts:
                _tw = time.perf_counter()
                triple_write_result = write_triples_with_ledger(
                    triple_dicts,
                    run_id=run_uuid,
                    entity_id=entity_id,
                    trigger="pipe_inference",
                )
                _t_write = time.perf_counter() - _tw
                _log.info("AAM_TRIPLE_WRITE: %d triples written (run=%s)", triple_write_result["triple_count"], run_tag)
        elif not entity_id and (new_pipes or update_pairs):
            _log.warning(
                "AAM_TRIPLE_SKIP: entity_id not resolved — no AOD handoff snapshot_name. "
                "%d pipes and %d connections will NOT produce triples.",
                len(new_pipes), len(update_pairs),
            )
    except Exception as exc:
        _log.error("AAM_TRIPLE_ERROR: pipe inference triple conversion failed (non-fatal): %s", exc)
    _t_triples = time.perf_counter() - _t0

    _t_total = time.perf_counter() - _t_start
    _log.info(
        "INFER_TIMING: total=%.1fs | fetch_obs=%.1fs fetch_cands=%.1fs "
        "fetch_pipes=%.1fs inference=%.1fs batch_write=%.1fs triples=%.1fs "
        "(handoff=%.2fs convert=%.4fs write=%.2fs)",
        _t_total, _t_fetch_obs, _t_fetch_cands, _t_fetch_pipes,
        _t_inference, _t_batch_write, _t_triples,
        _t_handoff, _t_convert, _t_write,
    )

    # Build response — includes triple write ledger entry and mode
    response = {
        "message": "Inference complete",
        "mode": mode.value,
        "run_id": triple_write_result["ledger_id"] if triple_write_result else None,
        "pipes_created": total_pipes,
        "from_observations": pipes_from_obs,
        "from_candidates": pipes_from_candidates,
        "candidates_unmatched": len(match_failures),
        "unmatched_reasons": match_failures[:10],
        "triple_write": triple_write_result,
        "dispatch": None,  # No dispatch in SYNTHETIC mode
    }

    return response


@router.post("/api/collect/adapter/run")
async def run_adapter(request=None):
    """Run adapter collector against connected fabric planes."""
    mode = get_operating_mode()
    if mode == OperatingMode.SYNTHETIC:
        _log.info("Skipping collector run: superseded by MCP discovery in PRODUCTION_SE")
        return {"message": "Collectors superseded in SYNTHETIC mode", "mode": mode.value}

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
