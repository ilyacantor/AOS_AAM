"""
AAM Triple Converter — transforms AAM operational data into EAV semantic triples.

Converts DeclaredPipes, connections, drift events, and fabric planes into
rows for the semantic_triples table in Postgres. Each property of each
AAM object becomes one triple row.

Concept prefixes (per platform spec §4.1):
  mapping.pipe        — DeclaredPipe attributes
  mapping.connection  — Matched connection attributes
  mapping.drift       — Drift event attributes
  mapping.fabric      — Fabric plane attributes

DESIGN:
  - Deterministic mappings, no LLM inference.
  - Skip properties with None/empty values (no null triples).
  - entity_id is a required parameter — fail loudly if missing.
  - source_system is always "AAM".
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

_log = logging.getLogger("aam.converters.triple")

# ---------------------------------------------------------------------------
# Confidence tier thresholds
# ---------------------------------------------------------------------------

def _tier_from_score(score: float) -> str:
    if score >= 0.95:
        return "exact"
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Run ID generation
# ---------------------------------------------------------------------------

def generate_run_id() -> tuple[str, str]:
    """Generate a unique run identifier for a batch of triples.

    Returns:
        (run_uuid, source_run_tag) where run_uuid is a UUID string for the
        PG run_id column and source_run_tag is the human-readable tag.
    """
    nonce = uuid.uuid4().hex[:8]
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    source_run_tag = f"aam_triples_{ts}_{nonce}"
    run_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, source_run_tag))
    return run_uuid, source_run_tag


# ---------------------------------------------------------------------------
# Entity ID resolution
# ---------------------------------------------------------------------------

def resolve_entity_id(
    snapshot_name: Optional[str],
    aod_run_id: Optional[str],
) -> Optional[str]:
    """Resolve entity_id from the AOD handoff context.

    Priority: snapshot_name > aod_run_id.  Returns None if neither is
    available — the caller must skip triple conversion with a WARNING.
    """
    if snapshot_name and str(snapshot_name).strip():
        return str(snapshot_name).strip()
    if aod_run_id and str(aod_run_id).strip():
        return str(aod_run_id).strip()
    return None


def _to_tenant_uuid(entity_id: str) -> str:
    """Convert entity_id string to a UUID suitable for the tenant_id column.

    If the string is already a valid UUID, return it as-is.
    Otherwise, derive a deterministic UUID5 from it.
    """
    try:
        uuid.UUID(entity_id)
        return entity_id
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, entity_id))


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _should_skip(value: Any) -> bool:
    """Return True if the value should NOT produce a triple."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


def _serialize_value(value: Any) -> Any:
    """Prepare a value for the JSONB column.

    Lists and dicts are kept as-is (json.dumps handles them in the writer).
    Booleans are kept as booleans.  Everything else becomes a string.
    """
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    return str(value)


# ---------------------------------------------------------------------------
# Triple construction helper
# ---------------------------------------------------------------------------

def _make_triple(
    *,
    entity_id: str,
    concept: str,
    prop: str,
    value: Any,
    run_id: str,
    source_run_tag: str,
    source_table: str,
    source_field: str,
    pipe_id: Optional[str] = None,
    confidence_score: float = 0.85,
    confidence_tier: str = "high",
    period: Optional[str] = None,
) -> dict:
    """Build one triple dict matching the semantic_triples column layout."""
    tenant_uuid = _to_tenant_uuid(entity_id)
    return {
        "tenant_id": tenant_uuid,
        "entity_id": entity_id,
        "concept": concept,
        "property": prop,
        "value": _serialize_value(value),
        "period": period,
        "currency": "USD",
        "unit": None,
        "source_system": "AAM",
        "source_table": source_table,
        "source_field": source_field,
        "pipe_id": pipe_id,
        "run_id": run_id,
        "source_run_tag": source_run_tag,
        "confidence_score": confidence_score,
        "confidence_tier": confidence_tier,
        "canonical_id": None,
        "resolution_method": None,
        "resolution_confidence": None,
    }


# ---------------------------------------------------------------------------
# DeclaredPipe → mapping.pipe
# ---------------------------------------------------------------------------

_PIPE_PROPERTIES = [
    # (property_name, source_field, confidence_score)
    ("modality", "modality", 0.85),
    ("transport_kind", "transport_kind", 0.85),
    ("fabric_plane", "fabric_plane", 0.85),
    ("entity_scope", "entity_scope", 0.85),
    ("identity_keys", "identity_keys", 0.85),
    ("source_system", "source_system", 0.95),
    ("display_name", "display_name", 0.95),
]


def convert_pipe_to_triples(
    pipe: dict,
    entity_id: str,
    run_id: str,
    source_run_tag: str,
) -> list[dict]:
    """Convert a DeclaredPipe dict to semantic triples."""
    triples = []
    pipe_id = pipe.get("pipe_id")

    for prop_name, field, conf in _PIPE_PROPERTIES:
        raw = pipe.get(field)
        # Handle JSON-encoded strings from the DB
        if isinstance(raw, str) and field in ("entity_scope", "identity_keys"):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        if _should_skip(raw):
            continue
        triples.append(_make_triple(
            entity_id=entity_id,
            concept="mapping.pipe",
            prop=prop_name,
            value=raw,
            run_id=run_id,
            source_run_tag=source_run_tag,
            source_table="declared_pipes",
            source_field=field,
            pipe_id=pipe_id,
            confidence_score=conf,
            confidence_tier=_tier_from_score(conf),
        ))

    # schema_hash from nested schema_info
    schema_info = pipe.get("schema_info")
    if isinstance(schema_info, str):
        try:
            schema_info = json.loads(schema_info)
        except (json.JSONDecodeError, TypeError):
            schema_info = None
    if isinstance(schema_info, dict):
        sh = schema_info.get("schema_hash")
        if not _should_skip(sh):
            triples.append(_make_triple(
                entity_id=entity_id,
                concept="mapping.pipe",
                prop="schema_hash",
                value=sh,
                run_id=run_id,
                source_run_tag=source_run_tag,
                source_table="declared_pipes",
                source_field="schema_hash",
                pipe_id=pipe_id,
                confidence_score=0.85,
                confidence_tier="high",
            ))

    return triples


# ---------------------------------------------------------------------------
# Connection (matched candidate) → mapping.connection
# ---------------------------------------------------------------------------

def convert_connection_to_triples(
    candidate: dict,
    entity_id: str,
    run_id: str,
    source_run_tag: str,
) -> list[dict]:
    """Convert a matched connection candidate to semantic triples."""
    triples = []
    pipe_id = candidate.get("matched_pipe_id")
    match_score = candidate.get("match_score", 0.5)
    if isinstance(match_score, str):
        try:
            match_score = float(match_score)
        except (ValueError, TypeError):
            match_score = 0.5
    tier = _tier_from_score(match_score)

    props = [
        ("source_system", candidate.get("vendor_name") or candidate.get("source_system"), "vendor_name"),
        ("connection_type", candidate.get("category"), "category"),
        ("status", candidate.get("status", "connected"), "status"),
        ("connected_via_plane", candidate.get("connected_via_plane"), "connected_via_plane"),
    ]

    for prop_name, value, src_field in props:
        if _should_skip(value):
            continue
        triples.append(_make_triple(
            entity_id=entity_id,
            concept="mapping.connection",
            prop=prop_name,
            value=value,
            run_id=run_id,
            source_run_tag=source_run_tag,
            source_table="connection_candidates",
            source_field=src_field,
            pipe_id=pipe_id,
            confidence_score=match_score,
            confidence_tier=tier,
        ))

    return triples


# ---------------------------------------------------------------------------
# Drift Event → mapping.drift
# ---------------------------------------------------------------------------

def convert_drift_to_triples(
    drift: dict,
    entity_id: str,
    run_id: str,
    source_run_tag: str,
) -> list[dict]:
    """Convert a drift event to semantic triples."""
    triples = []
    drift_type = drift.get("drift_type", "unknown")
    pipe_id = drift.get("pipe_id")
    detected_at = drift.get("detected_at")

    # Schema drift is deterministic (hash comparison) → exact confidence
    if drift_type == "schema":
        conf = 1.0
        tier = "exact"
    else:
        conf = 0.85
        tier = "high"

    props = [
        ("drift_type", drift_type, "drift_type"),
        ("severity", drift.get("severity", "medium"), "severity"),
        ("affected_pipe", pipe_id, "pipe_id"),
    ]

    for prop_name, value, src_field in props:
        if _should_skip(value):
            continue
        triples.append(_make_triple(
            entity_id=entity_id,
            concept="mapping.drift",
            prop=prop_name,
            value=value,
            run_id=run_id,
            source_run_tag=source_run_tag,
            source_table="drift_events",
            source_field=src_field,
            pipe_id=pipe_id,
            confidence_score=conf,
            confidence_tier=tier,
            period=str(detected_at) if detected_at else None,
        ))

    return triples


# ---------------------------------------------------------------------------
# Fabric Plane → mapping.fabric
# ---------------------------------------------------------------------------

def convert_fabric_plane_to_triples(
    plane: dict,
    entity_id: str,
    run_id: str,
    source_run_tag: str,
) -> list[dict]:
    """Convert a fabric plane record to semantic triples."""
    triples = []

    props = [
        ("plane_type", plane.get("plane_type"), "plane_type"),
        ("vendor", plane.get("vendor"), "vendor"),
        ("health_status", plane.get("is_healthy"), "is_healthy"),
    ]

    for prop_name, value, src_field in props:
        if _should_skip(value):
            continue
        triples.append(_make_triple(
            entity_id=entity_id,
            concept="mapping.fabric",
            prop=prop_name,
            value=value,
            run_id=run_id,
            source_run_tag=source_run_tag,
            source_table="fabric_planes",
            source_field=src_field,
            confidence_score=0.90,
            confidence_tier="high",
        ))

    return triples


# ---------------------------------------------------------------------------
# Batch conversion — post-inference
# ---------------------------------------------------------------------------

def convert_inference_batch(
    new_pipes: list[dict],
    candidate_updates: list[dict],
    planes: list[dict],
    entity_id: str,
    run_id: str,
    source_run_tag: str,
) -> list[dict]:
    """Convert all post-inference data to triples in one call.

    Called after pipe inference completes. Combines pipe, connection,
    and fabric plane triples into a single list for batch write.
    """
    all_triples: list[dict] = []

    for pipe in new_pipes:
        all_triples.extend(convert_pipe_to_triples(pipe, entity_id, run_id, source_run_tag))

    for candidate in candidate_updates:
        all_triples.extend(convert_connection_to_triples(candidate, entity_id, run_id, source_run_tag))

    for plane in planes:
        all_triples.extend(convert_fabric_plane_to_triples(plane, entity_id, run_id, source_run_tag))

    _log.info(
        "convert_inference_batch: pipes=%d connections=%d planes=%d → %d triples",
        len(new_pipes), len(candidate_updates), len(planes), len(all_triples),
    )
    return all_triples
