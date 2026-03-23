"""
Layer 1 Data Drift Signals — pluggable drift detection against the PG triple store.

Each signal implements the DriftSignal protocol and returns a list of DriftEvent
objects. Signals query the PG triple store read-only via AAM's existing psycopg2
connection pool.

Four Layer 1 signals:
  SchemaDrift    — concept+property pairs changed between runs
  FreshnessDrift — time since last AAM write exceeds threshold
  CoverageDrift  — concept prefixes missing compared to baseline
  VolumeDrift    — triple count per prefix deviated >20% from baseline
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from psycopg2 import sql as psql

from ..db import supabase_client as sb

_log = logging.getLogger("aam.drift.signals")


@dataclass
class DriftEvent:
    """A detected drift condition."""
    drift_type: str          # schema | freshness | coverage | volume
    severity: str            # HIGH | MEDIUM | LOW
    affected_entity: str
    affected_concept: str    # which concept prefix is affected
    details: dict            # signal-specific details
    detection_timestamp: datetime = field(default_factory=datetime.utcnow)


@runtime_checkable
class DriftSignal(Protocol):
    """Interface for drift detection signals."""
    def detect(self, entity_id: str, run_id: str) -> list[DriftEvent]:
        ...


class SchemaDrift:
    """Compare concept+property pairs across consecutive run_ids for same entity.

    New properties = expansion (LOW). Missing properties = contraction (HIGH).
    """

    def detect(self, entity_id: str, run_id: str) -> list[DriftEvent]:
        events: list[DriftEvent] = []
        try:
            # Get previous run_id for this entity
            prev_query = psql.SQL(
                "SELECT DISTINCT {run_id} FROM {table} "
                "WHERE {source} = %s AND {eid} = %s AND {run_id} != %s "
                "ORDER BY {run_id} DESC LIMIT 1"
            ).format(
                run_id=sb._ident("run_id"),
                table=sb._ident("semantic_triples"),
                source=sb._ident("source_system"),
                eid=sb._ident("entity_id"),
            )
            prev_rows = sb._execute_composed(prev_query, ("AAM", entity_id, run_id))
            if not prev_rows:
                return events  # No previous run — no drift possible
            prev_run_id = prev_rows[0]["run_id"]

            # Current concept+property pairs
            current_query = psql.SQL(
                "SELECT DISTINCT {concept}, {prop} FROM {table} "
                "WHERE {run_id} = %s AND {source} = %s AND {eid} = %s"
            ).format(
                concept=sb._ident("concept"),
                prop=sb._ident("property"),
                table=sb._ident("semantic_triples"),
                run_id=sb._ident("run_id"),
                source=sb._ident("source_system"),
                eid=sb._ident("entity_id"),
            )
            current_pairs = sb._execute_composed(current_query, (run_id, "AAM", entity_id))
            current_set = {(r["concept"], r["property"]) for r in current_pairs}

            # Previous concept+property pairs
            prev_pairs = sb._execute_composed(current_query, (prev_run_id, "AAM", entity_id))
            prev_set = {(r["concept"], r["property"]) for r in prev_pairs}

            # Contractions (HIGH)
            missing = prev_set - current_set
            for concept, prop in missing:
                prefix = concept.split(".")[0] + "." + concept.split(".")[1] if "." in concept else concept
                events.append(DriftEvent(
                    drift_type="schema",
                    severity="HIGH",
                    affected_entity=entity_id,
                    affected_concept=prefix,
                    details={
                        "change": "contraction",
                        "missing_property": prop,
                        "concept": concept,
                        "previous_run_id": prev_run_id,
                        "current_run_id": run_id,
                    },
                ))

            # Expansions (LOW)
            added = current_set - prev_set
            for concept, prop in added:
                prefix = concept.split(".")[0] + "." + concept.split(".")[1] if "." in concept else concept
                events.append(DriftEvent(
                    drift_type="schema",
                    severity="LOW",
                    affected_entity=entity_id,
                    affected_concept=prefix,
                    details={
                        "change": "expansion",
                        "new_property": prop,
                        "concept": concept,
                        "previous_run_id": prev_run_id,
                        "current_run_id": run_id,
                    },
                ))

        except Exception as exc:
            _log.error("SchemaDrift.detect failed for entity=%s run=%s: %s", entity_id, run_id, exc)
        return events


class FreshnessDrift:
    """Check time since last AAM write to PG.

    Default threshold: MEDIUM if >24h stale.
    """
    STALE_THRESHOLD_HOURS = 24

    def detect(self, entity_id: str, run_id: str) -> list[DriftEvent]:
        events: list[DriftEvent] = []
        try:
            query = psql.SQL(
                "SELECT MAX({created}) as latest FROM {table} "
                "WHERE {source} = %s AND {eid} = %s"
            ).format(
                created=sb._ident("created_at"),
                table=sb._ident("semantic_triples"),
                source=sb._ident("source_system"),
                eid=sb._ident("entity_id"),
            )
            rows = sb._execute_composed(query, ("AAM", entity_id))
            if not rows or rows[0]["latest"] is None:
                events.append(DriftEvent(
                    drift_type="freshness",
                    severity="HIGH",
                    affected_entity=entity_id,
                    affected_concept="mapping.*",
                    details={"reason": "No AAM triples found for this entity"},
                ))
                return events

            latest = rows[0]["latest"]
            if isinstance(latest, str):
                latest = datetime.fromisoformat(latest.replace("Z", "+00:00").replace("+00:00", ""))

            # Make both naive for comparison
            now = datetime.utcnow()
            if hasattr(latest, 'tzinfo') and latest.tzinfo is not None:
                latest = latest.replace(tzinfo=None)

            age = now - latest
            if age > timedelta(hours=self.STALE_THRESHOLD_HOURS):
                events.append(DriftEvent(
                    drift_type="freshness",
                    severity="MEDIUM",
                    affected_entity=entity_id,
                    affected_concept="mapping.*",
                    details={
                        "hours_stale": round(age.total_seconds() / 3600, 1),
                        "threshold_hours": self.STALE_THRESHOLD_HOURS,
                        "latest_write": latest.isoformat(),
                    },
                ))

        except Exception as exc:
            _log.error("FreshnessDrift.detect failed for entity=%s: %s", entity_id, exc)
        return events


class CoverageDrift:
    """Count distinct concept prefixes per entity per run.

    Compare to baseline run. Missing domains = HIGH.
    """

    def detect(self, entity_id: str, run_id: str) -> list[DriftEvent]:
        events: list[DriftEvent] = []
        try:
            # Get concept prefixes for current run
            query = psql.SQL(
                "SELECT DISTINCT split_part({concept}, '.', 1) || '.' || split_part({concept}, '.', 2) "
                "as prefix FROM {table} "
                "WHERE {source} = %s AND {eid} = %s AND {run_id} = %s"
            ).format(
                concept=sb._ident("concept"),
                table=sb._ident("semantic_triples"),
                source=sb._ident("source_system"),
                eid=sb._ident("entity_id"),
                run_id=sb._ident("run_id"),
            )
            current_rows = sb._execute_composed(query, ("AAM", entity_id, run_id))
            current_prefixes = {r["prefix"] for r in current_rows if r.get("prefix")}

            # Get baseline (previous run)
            prev_query = psql.SQL(
                "SELECT DISTINCT {run_id} FROM {table} "
                "WHERE {source} = %s AND {eid} = %s AND {run_id} != %s "
                "ORDER BY {run_id} DESC LIMIT 1"
            ).format(
                run_id=sb._ident("run_id"),
                table=sb._ident("semantic_triples"),
                source=sb._ident("source_system"),
                eid=sb._ident("entity_id"),
            )
            prev_rows = sb._execute_composed(prev_query, ("AAM", entity_id, run_id))
            if not prev_rows:
                return events  # No baseline
            prev_run_id = prev_rows[0]["run_id"]

            baseline_rows = sb._execute_composed(query, ("AAM", entity_id, prev_run_id))
            baseline_prefixes = {r["prefix"] for r in baseline_rows if r.get("prefix")}

            missing = baseline_prefixes - current_prefixes
            for prefix in missing:
                events.append(DriftEvent(
                    drift_type="coverage",
                    severity="HIGH",
                    affected_entity=entity_id,
                    affected_concept=prefix,
                    details={
                        "missing_prefix": prefix,
                        "baseline_run_id": prev_run_id,
                        "current_run_id": run_id,
                        "baseline_prefixes": sorted(baseline_prefixes),
                        "current_prefixes": sorted(current_prefixes),
                    },
                ))

        except Exception as exc:
            _log.error("CoverageDrift.detect failed for entity=%s run=%s: %s", entity_id, run_id, exc)
        return events


class VolumeDrift:
    """Count triples per concept prefix per run.

    >20% deviation from baseline = MEDIUM.
    """
    DEVIATION_THRESHOLD = 0.20

    def detect(self, entity_id: str, run_id: str) -> list[DriftEvent]:
        events: list[DriftEvent] = []
        try:
            count_query = psql.SQL(
                "SELECT split_part({concept}, '.', 1) || '.' || split_part({concept}, '.', 2) "
                "as prefix, COUNT(*) as cnt FROM {table} "
                "WHERE {source} = %s AND {eid} = %s AND {run_id} = %s "
                "GROUP BY prefix"
            ).format(
                concept=sb._ident("concept"),
                table=sb._ident("semantic_triples"),
                source=sb._ident("source_system"),
                eid=sb._ident("entity_id"),
                run_id=sb._ident("run_id"),
            )
            current_rows = sb._execute_composed(count_query, ("AAM", entity_id, run_id))
            current_counts = {r["prefix"]: r["cnt"] for r in current_rows if r.get("prefix")}

            # Get baseline (previous run)
            prev_query = psql.SQL(
                "SELECT DISTINCT {run_id} FROM {table} "
                "WHERE {source} = %s AND {eid} = %s AND {run_id} != %s "
                "ORDER BY {run_id} DESC LIMIT 1"
            ).format(
                run_id=sb._ident("run_id"),
                table=sb._ident("semantic_triples"),
                source=sb._ident("source_system"),
                eid=sb._ident("entity_id"),
            )
            prev_rows = sb._execute_composed(prev_query, ("AAM", entity_id, run_id))
            if not prev_rows:
                return events
            prev_run_id = prev_rows[0]["run_id"]

            baseline_rows = sb._execute_composed(count_query, ("AAM", entity_id, prev_run_id))
            baseline_counts = {r["prefix"]: r["cnt"] for r in baseline_rows if r.get("prefix")}

            for prefix, current_count in current_counts.items():
                baseline_count = baseline_counts.get(prefix)
                if baseline_count is None or baseline_count == 0:
                    continue
                deviation = abs(current_count - baseline_count) / baseline_count
                if deviation > self.DEVIATION_THRESHOLD:
                    direction = "increase" if current_count > baseline_count else "decrease"
                    events.append(DriftEvent(
                        drift_type="volume",
                        severity="MEDIUM",
                        affected_entity=entity_id,
                        affected_concept=prefix,
                        details={
                            "direction": direction,
                            "current_count": current_count,
                            "baseline_count": baseline_count,
                            "deviation_pct": round(deviation * 100, 1),
                            "threshold_pct": round(self.DEVIATION_THRESHOLD * 100, 1),
                            "baseline_run_id": prev_run_id,
                            "current_run_id": run_id,
                        },
                    ))

        except Exception as exc:
            _log.error("VolumeDrift.detect failed for entity=%s run=%s: %s", entity_id, run_id, exc)
        return events
