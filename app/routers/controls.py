"""
Controls API Router — triple write ledger, operating mode, drift detection, triple health.

Exposes the backend data that the operator dashboard (Build Item 6) consumes.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from psycopg2 import sql as psql

from ..db import supabase_client as sb
from ..db.ledger import list_entries, get_entries_for_run, get_summary
from ..utils.operating_mode import get_operating_mode, OperatingMode
from ..drift.orchestrator import DriftOrchestrator

_log = logging.getLogger("aam.routers.controls")

router = APIRouter(tags=["Controls"])

# Module-level drift orchestrator
_drift_orchestrator = DriftOrchestrator()


def get_drift_orchestrator() -> DriftOrchestrator:
    """Return the module-level drift orchestrator."""
    return _drift_orchestrator


# ---------------------------------------------------------------------------
# Operating Mode
# ---------------------------------------------------------------------------

@router.get("/api/aam/mode")
def get_mode():
    """Return the current operating mode."""
    mode = get_operating_mode()
    superseded = []
    if mode == OperatingMode.SYNTHETIC:
        superseded = [
            {"control": "JobManifest dispatch", "reason": "Superseded by MCP discovery in PRODUCTION_SE"},
            {"control": "Runner job creation", "reason": "Superseded by MCP discovery in PRODUCTION_SE"},
            {"control": "Collector operations", "reason": "Superseded by MCP discovery in PRODUCTION_SE"},
            {"control": "Self-healing checks", "reason": "Superseded by MCP discovery in PRODUCTION_SE"},
        ]
    return {
        "mode": mode.value,
        "superseded_controls": superseded,
    }


# ---------------------------------------------------------------------------
# Triple Write Ledger
# ---------------------------------------------------------------------------

@router.get("/api/aam/triple-ledger")
def get_ledger(
    entity_id: Optional[str] = Query(None),
    trigger: Optional[str] = Query(None),
    write_path: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
):
    """Recent ledger entries, filterable."""
    entries = list_entries(
        entity_id=entity_id,
        trigger=trigger,
        write_path=write_path,
        status=status,
        limit=limit,
    )
    return {"entries": entries, "count": len(entries)}


@router.get("/api/aam/triple-ledger/summary")
def get_ledger_summary():
    """Aggregated ledger summary."""
    return get_summary()


@router.get("/api/aam/triple-ledger/{run_id}")
def get_ledger_for_run(run_id: str):
    """All entries for a specific run."""
    entries = get_entries_for_run(run_id)
    return {"entries": entries, "count": len(entries), "run_id": run_id}


# ---------------------------------------------------------------------------
# Triple Health
# ---------------------------------------------------------------------------

@router.get("/api/aam/triple-health")
def get_triple_health(entity_id: Optional[str] = Query(None)):
    """Triple health: count, coverage, freshness, run comparison."""
    try:
        # Resolve entity_id if not provided
        if not entity_id:
            handoffs = sb.select("aod_handoff_log", order="processed_at.desc", limit=1)
            if handoffs:
                from ..converters.triple_converter import resolve_entity_id
                entity_id = resolve_entity_id(
                    handoffs[0].get("snapshot_name"),
                    handoffs[0].get("aod_run_id"),
                )
            if not entity_id:
                return {
                    "entity_id": None,
                    "total_count": 0,
                    "coverage": {},
                    "freshness": {"status": "unknown", "latest_write": None},
                    "run_comparison": None,
                    "message": "No entity_id resolved — no AOD handoff snapshot found",
                }

        # Total AAM triple count
        count_query = psql.SQL(
            "SELECT COUNT(*) as cnt FROM {table} WHERE {source} = %s AND {eid} = %s"
        ).format(
            table=sb._ident("semantic_triples"),
            source=sb._ident("source_system"),
            eid=sb._ident("entity_id"),
        )
        count_rows = sb._execute_composed(count_query, ("AAM", entity_id))
        total_count = count_rows[0]["cnt"] if count_rows else 0

        # Concept coverage
        coverage_query = psql.SQL(
            "SELECT DISTINCT split_part({concept}, '.', 1) || '.' || split_part({concept}, '.', 2) "
            "as prefix FROM {table} WHERE {source} = %s AND {eid} = %s"
        ).format(
            concept=sb._ident("concept"),
            table=sb._ident("semantic_triples"),
            source=sb._ident("source_system"),
            eid=sb._ident("entity_id"),
        )
        coverage_rows = sb._execute_composed(coverage_query, ("AAM", entity_id))
        present_prefixes = {r["prefix"] for r in coverage_rows if r.get("prefix")}
        expected_prefixes = ["mapping.pipe", "mapping.connection", "mapping.drift", "mapping.fabric"]
        coverage = {
            p: "present" if p in present_prefixes else "missing"
            for p in expected_prefixes
        }

        # Freshness
        fresh_query = psql.SQL(
            "SELECT MAX({created}) as latest FROM {table} WHERE {source} = %s AND {eid} = %s"
        ).format(
            created=sb._ident("created_at"),
            table=sb._ident("semantic_triples"),
            source=sb._ident("source_system"),
            eid=sb._ident("entity_id"),
        )
        fresh_rows = sb._execute_composed(fresh_query, ("AAM", entity_id))
        latest_write = fresh_rows[0]["latest"] if fresh_rows and fresh_rows[0]["latest"] else None

        freshness_status = "unknown"
        if latest_write:
            if isinstance(latest_write, str):
                latest_dt = datetime.fromisoformat(latest_write.replace("Z", "+00:00").replace("+00:00", ""))
            else:
                latest_dt = latest_write
            if hasattr(latest_dt, 'tzinfo') and latest_dt.tzinfo is not None:
                latest_dt = latest_dt.replace(tzinfo=None)
            age_hours = (datetime.utcnow() - latest_dt).total_seconds() / 3600
            if age_hours < 1:
                freshness_status = "green"
            elif age_hours < 24:
                freshness_status = "yellow"
            else:
                freshness_status = "red"

        # Run comparison (latest vs previous)
        run_query = psql.SQL(
            "SELECT {run_id}, COUNT(*) as cnt FROM {table} "
            "WHERE {source} = %s AND {eid} = %s "
            "GROUP BY {run_id} ORDER BY MAX({created}) DESC LIMIT 2"
        ).format(
            run_id=sb._ident("run_id"),
            table=sb._ident("semantic_triples"),
            source=sb._ident("source_system"),
            eid=sb._ident("entity_id"),
            created=sb._ident("created_at"),
        )
        run_rows = sb._execute_composed(run_query, ("AAM", entity_id))
        run_comparison = None
        if len(run_rows) >= 2:
            run_comparison = {
                "latest_run_id": run_rows[0]["run_id"],
                "latest_count": run_rows[0]["cnt"],
                "previous_run_id": run_rows[1]["run_id"],
                "previous_count": run_rows[1]["cnt"],
                "delta": run_rows[0]["cnt"] - run_rows[1]["cnt"],
            }
        elif len(run_rows) == 1:
            run_comparison = {
                "latest_run_id": run_rows[0]["run_id"],
                "latest_count": run_rows[0]["cnt"],
                "previous_run_id": None,
                "previous_count": 0,
                "delta": run_rows[0]["cnt"],
            }

        return {
            "entity_id": entity_id,
            "total_count": total_count,
            "coverage": coverage,
            "freshness": {
                "status": freshness_status,
                "latest_write": str(latest_write) if latest_write else None,
            },
            "run_comparison": run_comparison,
        }

    except Exception as exc:
        _log.error("Triple health query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Triple health query failed: {exc}")


# ---------------------------------------------------------------------------
# Drift Detection
# ---------------------------------------------------------------------------

@router.get("/api/aam/drift-status")
def get_drift_status(entity_id: Optional[str] = Query(None)):
    """Latest drift check results and timestamps."""
    orch = get_drift_orchestrator()
    last_checks = orch.get_last_check_times()
    signal_names = orch.get_signal_names()

    # Get mapping.drift.* triples from PG for active drift events
    drift_events: list[dict] = []
    try:
        if not entity_id:
            handoffs = sb.select("aod_handoff_log", order="processed_at.desc", limit=1)
            if handoffs:
                from ..converters.triple_converter import resolve_entity_id
                entity_id = resolve_entity_id(
                    handoffs[0].get("snapshot_name"),
                    handoffs[0].get("aod_run_id"),
                )

        if entity_id:
            drift_query = psql.SQL(
                "SELECT {concept}, {prop}, {val}, {period}, {run_id}, {created} "
                "FROM {table} WHERE {source} = %s AND {eid} = %s "
                "AND {concept} LIKE %s ORDER BY {created} DESC LIMIT 50"
            ).format(
                concept=sb._ident("concept"),
                prop=sb._ident("property"),
                val=sb._ident("value"),
                period=sb._ident("period"),
                run_id=sb._ident("run_id"),
                created=sb._ident("created_at"),
                table=sb._ident("semantic_triples"),
                source=sb._ident("source_system"),
                eid=sb._ident("entity_id"),
            )
            rows = sb._execute_composed(drift_query, ("AAM", entity_id, "mapping.drift%"))
            drift_events = [dict(r) for r in rows]
    except Exception as exc:
        _log.error("Drift status query failed: %s", exc)

    return {
        "signals": signal_names,
        "last_check_times": last_checks,
        "active_events": drift_events,
        "entity_id": entity_id,
        "has_checked": bool(last_checks),
    }


@router.post("/api/aam/drift-check")
def trigger_drift_check(entity_id: Optional[str] = Query(None)):
    """Manually trigger a drift check."""
    orch = get_drift_orchestrator()

    if not entity_id:
        handoffs = sb.select("aod_handoff_log", order="processed_at.desc", limit=1)
        if handoffs:
            from ..converters.triple_converter import resolve_entity_id
            entity_id = resolve_entity_id(
                handoffs[0].get("snapshot_name"),
                handoffs[0].get("aod_run_id"),
            )
    if not entity_id:
        raise HTTPException(status_code=400, detail="Cannot resolve entity_id — no AOD handoff found")

    # Get latest run_id for this entity
    run_query = psql.SQL(
        "SELECT DISTINCT {run_id} FROM {table} "
        "WHERE {source} = %s AND {eid} = %s "
        "ORDER BY {run_id} DESC LIMIT 1"
    ).format(
        run_id=sb._ident("run_id"),
        table=sb._ident("semantic_triples"),
        source=sb._ident("source_system"),
        eid=sb._ident("entity_id"),
    )
    run_rows = sb._execute_composed(run_query, ("AAM", entity_id))
    if not run_rows:
        raise HTTPException(status_code=404, detail="No AAM triples found for this entity")

    latest_run_id = run_rows[0]["run_id"]
    events = orch.detect_all(entity_id, latest_run_id)

    # Write drift events as mapping.drift.* triples
    if events:
        try:
            from ..converters.triple_converter import convert_drift_to_triples, generate_run_id
            from ..db.triple_writer import write_triples

            drift_run_uuid, drift_run_tag = generate_run_id()
            all_triples = []
            for evt in events:
                drift_dict = {
                    "drift_type": evt.drift_type,
                    "severity": evt.severity,
                    "pipe_id": None,
                    "detected_at": evt.detection_timestamp.isoformat(),
                }
                all_triples.extend(convert_drift_to_triples(
                    drift_dict, entity_id, drift_run_uuid, drift_run_tag,
                ))
            if all_triples:
                write_triples(all_triples)
                _log.info("Wrote %d drift triples for %d events", len(all_triples), len(events))
        except Exception as exc:
            _log.error("Drift triple write failed (non-fatal): %s", exc)

    return {
        "entity_id": entity_id,
        "run_id": latest_run_id,
        "events": [
            {
                "drift_type": e.drift_type,
                "severity": e.severity,
                "affected_entity": e.affected_entity,
                "affected_concept": e.affected_concept,
                "details": e.details,
                "detection_timestamp": e.detection_timestamp.isoformat(),
            }
            for e in events
        ],
        "event_count": len(events),
        "last_check_times": orch.get_last_check_times(),
    }
