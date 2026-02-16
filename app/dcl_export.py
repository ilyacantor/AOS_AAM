"""
AAM → DCL Export Module

Provides pipe definitions grouped by fabric plane for DCL consumption.
Uses REAL fabric plane data from AOD instead of hardcoded vendors.

Field resolution priority (highest to lowest):
  1. Observation schema_sample (real fields from adapter discovery)
  2. Declared pipe identity_keys + entity_scope (inference-generated)
  3. Category-based standard fields (metadata inference from category)
"""
import json
import logging
from typing import List, Dict, Optional

from .models import CandidateStatus
from pydantic import BaseModel
from datetime import datetime

from .services.runner_dispatch import normalize_category


def _normalize_export_category(raw_category: Optional[str], vendor: Optional[str] = None) -> str:
    """Normalize category for DCL export. Falls back to 'other' only if truly unresolvable."""
    result = normalize_category(raw_category, vendor)
    return result or "other"


from .db import (
    get_candidates_by_aod_run,
    list_candidates,
    get_fabric_planes,
    get_all_schema_samples,
)
from .db import supabase_client as sb
from .constants import CATEGORY_STANDARD_FIELDS, PLANE_STANDARD_FIELDS, INFRA_VENDOR_PLANE

_log = logging.getLogger(__name__)


class DCLConnectionSchema(BaseModel):
    """Schema for a single connection in a fabric plane.

    pipe_id is the DeclaredPipe.pipe_id (via matched_pipe_id) — the canonical
    join key that DCL uses to bind Structure (export) with Content (Farm push).
    candidate_id is preserved separately for provenance tracking.
    """
    pipe_id: str                                      # DeclaredPipe.pipe_id (via matched_pipe_id)
    candidate_id: str                                 # Original AOD candidate_id (provenance)
    source_name: str
    vendor: str
    category: str
    governance_status: Optional[str] = None
    fields: List[str] = []
    entity_scope: Optional[str] = None                # From pipe inference
    identity_keys: Optional[List[str]] = None         # From pipe inference
    transport_kind: Optional[str] = None              # From pipe inference
    modality: Optional[str] = None                    # From pipe inference
    change_semantics: Optional[str] = None            # From pipe inference
    health: str = "healthy"
    last_sync: Optional[str] = None
    asset_key: str
    aod_asset_id: Optional[str] = None


class DCLFabricPlane(BaseModel):
    """A fabric plane with its connections"""
    plane_type: str  # ipaas, warehouse, api_gateway, event_bus
    vendor: str  # Actual vendor from AOD: mulesoft, kong, snowflake, kafka, etc.
    connection_count: int
    connections: List[DCLConnectionSchema]
    health: str = "healthy"


class SkippedConnection(BaseModel):
    """A candidate that was excluded from the export because inference
    has not yet produced a DeclaredPipe (no matched_pipe_id).

    Operators see these in logs / UI so they know the pipeline isn't
    broken — it's just not ready yet.
    """
    candidate_id: str
    vendor: str
    reason: str = "pending_inference"
    discovered_at: Optional[str] = None


class DCLExportResponse(BaseModel):
    """Response for DCL export endpoint"""
    aod_run_id: Optional[str] = None
    timestamp: str
    fabric_planes: List[DCLFabricPlane]
    total_connections: int                             # Count of exported pipes only
    skipped_connections: List[SkippedConnection] = []  # Candidates without matched_pipe_id
    skipped_count: int = 0
    source: str = "aam"


# ---------------------------------------------------------------------------
# Field resolution — resolves fields for each candidate using all
# available data sources.  Batch-fetches everything upfront to avoid
# N+1 DB queries.
# ---------------------------------------------------------------------------

def _build_field_maps(candidate_ids: set[str], vendor_names: set[str]) -> dict:
    """Pre-fetch all field data in bulk.  Returns a dict with lookup maps.

    Returns:
        {
            "by_candidate_id": {candidate_id: [field_names]},
            "by_source_system": {source_system_lower: [field_names]},
            "by_pipe_id": {pipe_id: [field_names]},
        }
    """
    maps: dict = {
        "by_candidate_id": {},
        "by_source_system": {},
        "by_pipe_id": {},
        "pipe_metadata": {},   # pipe_id → {entity_scope, identity_keys, ...}
    }

    # --- Source 1: Observation schema_samples (single DB call) ---
    try:
        obs_samples = get_all_schema_samples()
        for sample in obs_samples:
            cid = sample.get("candidate_id")
            src = (sample.get("source_system") or "").lower()
            fields = sample["field_names"]

            if cid and cid in candidate_ids:
                existing = maps["by_candidate_id"].get(cid, [])
                merged = list(dict.fromkeys(existing + fields))  # dedupe preserving order
                maps["by_candidate_id"][cid] = merged

            if src:
                existing = maps["by_source_system"].get(src, [])
                merged = list(dict.fromkeys(existing + fields))
                maps["by_source_system"][src] = merged
    except Exception as exc:
        _log.warning("Failed to fetch observation schema samples: %s", exc)

    # --- Source 2: Declared pipes (identity_keys + entity_scope + metadata) ---
    try:
        rows = sb.select(
            "declared_pipes",
            columns="pipe_id,identity_keys,entity_scope,transport_kind,modality,change_semantics",
        )
        for row in rows:
            pid = row.get("pipe_id")
            if not pid:
                continue

            # Parse JSON arrays
            ik_raw = row.get("identity_keys")
            ik_parsed: list = []
            if ik_raw:
                ik_parsed = json.loads(ik_raw) if isinstance(ik_raw, str) else ik_raw
                if not isinstance(ik_parsed, list):
                    ik_parsed = []

            es_raw = row.get("entity_scope")
            es_parsed: list = []
            if es_raw:
                es_parsed = json.loads(es_raw) if isinstance(es_raw, str) else es_raw
                if not isinstance(es_parsed, list):
                    es_parsed = []

            # Field list for cascade priority 3
            fields: list[str] = list(dict.fromkeys(ik_parsed + es_parsed))
            if fields:
                maps["by_pipe_id"][pid] = fields

            # Pipe metadata for export enrichment
            maps["pipe_metadata"][pid] = {
                "entity_scope": ", ".join(es_parsed) if es_parsed else None,
                "identity_keys": ik_parsed or None,
                "transport_kind": row.get("transport_kind"),
                "modality": row.get("modality"),
                "change_semantics": row.get("change_semantics"),
            }
    except Exception as exc:
        _log.warning("Failed to fetch declared pipe fields: %s", exc)

    return maps


def _resolve_fields(candidate: dict, field_maps: dict) -> List[str]:
    """Resolve field names for a single candidate using the priority cascade.

    Priority:
      1. Observation linked by candidate_id  (real adapter schema)
      2. Observation matched by source_system ↔ vendor_name  (fuzzy match)
      3. Declared pipe identity_keys + entity_scope via matched_pipe_id
      4. Vendor→plane mapping fields  (infrastructure vendors in "other" category)
      5. Category-based standard fields  (metadata inference)
    """
    cid = candidate.get("candidate_id", "")
    vendor = (candidate.get("vendor_name") or "").lower()
    matched_pipe = candidate.get("matched_pipe_id")
    category = (candidate.get("category") or "other").lower()

    # Priority 1: Direct observation link
    fields = field_maps["by_candidate_id"].get(cid)
    if fields:
        return fields

    # Priority 2: Source system match
    fields = field_maps["by_source_system"].get(vendor)
    if fields:
        return fields

    # Priority 3: Declared pipe fields
    if matched_pipe:
        fields = field_maps["by_pipe_id"].get(matched_pipe)
        if fields:
            return fields

    # Priority 4: Vendor→plane mapping (infrastructure vendors like Kong,
    # Snowflake, Kafka categorised as "other" by AOD).
    plane_type = INFRA_VENDOR_PLANE.get(vendor)
    if plane_type:
        fields = PLANE_STANDARD_FIELDS.get(plane_type)
        if fields:
            return list(fields)

    # Priority 5: Category standard fields
    fields = CATEGORY_STANDARD_FIELDS.get(category)
    if fields:
        return list(fields)  # Return a copy

    return []


def build_dcl_export(aod_run_id: Optional[str] = None) -> DCLExportResponse:
    """
    Build DCL export from AAM candidates using REAL fabric planes from AOD.

    Groups candidates by fabric plane and formats for DCL consumption.
    If aod_run_id is provided, filters to that run. Otherwise, uses all candidates.
    """
    # Fetch real fabric planes from database
    fabric_planes_db = get_fabric_planes(aod_run_id)

    # Fetch candidates
    if aod_run_id:
        candidates = get_candidates_by_aod_run(aod_run_id)
    else:
        # Get all candidates with status 'connected' or 'triaged'
        all_candidates = list_candidates()
        candidates = [c for c in all_candidates if c.get("status") in [CandidateStatus.CONNECTED, CandidateStatus.TRIAGED, CandidateStatus.NEW]]

    # Pre-fetch field data in bulk (3 DB calls total, not N per candidate)
    candidate_ids = {c.get("candidate_id", "") for c in candidates}
    vendor_names = {(c.get("vendor_name") or "").lower() for c in candidates}
    field_maps = _build_field_maps(candidate_ids, vendor_names)

    # Group candidates by fabric plane (using fabric_plane_id linkage)
    planes_dict: Dict[str, Dict] = {}
    for plane_db in fabric_planes_db:
        plane_id = plane_db["plane_id"]
        planes_dict[plane_id] = {
            "plane": plane_db,
            "candidates": []
        }

    # Assign candidates to their fabric plane using fabric_plane_id,
    # with fallback to connected_via_plane (set by inference).
    unlinked_candidates = []
    for candidate in candidates:
        fabric_plane_id = candidate.get("fabric_plane_id")

        if fabric_plane_id and fabric_plane_id in planes_dict:
            # Direct linkage exists
            planes_dict[fabric_plane_id]["candidates"].append(candidate)
        else:
            # Fallback: group by connected_via_plane type (set by inference)
            connected = (candidate.get("connected_via_plane") or "").upper()
            placed = False
            if connected and connected != "UNMAPPED":
                for pid, data in planes_dict.items():
                    if data["plane"]["plane_type"] == connected:
                        data["candidates"].append(candidate)
                        placed = True
                        break
            if not placed:
                unlinked_candidates.append(candidate)

    for candidate in unlinked_candidates:
        _log.debug("Candidate %s (%s) has no fabric plane link — skipping DCL grouping",
                   candidate.get("vendor_name"), candidate.get("category"))

    # Build fabric plane objects for DCL.
    # Only export candidates with matched_pipe_id (fully inferred).
    # Candidates without matched_pipe_id go into skipped_connections.
    fabric_planes_output = []
    total_connections = 0
    skipped: list[SkippedConnection] = []

    for plane_id, data in planes_dict.items():
        plane = data["plane"]
        candidates_list = data["candidates"]

        if not candidates_list:
            continue

        # Sort candidates by updated_at descending so when we deduplicate
        # by pipe_id below, the first one seen is the most recent.
        candidates_list.sort(
            key=lambda c: c.get("updated_at") or c.get("created_at") or "",
            reverse=True,
        )

        connections = []
        seen_pipe_ids: set[str] = set()
        for candidate in candidates_list:
            cid = candidate.get("candidate_id", "")
            matched_pipe_id = candidate.get("matched_pipe_id")

            if not matched_pipe_id:
                skipped.append(SkippedConnection(
                    candidate_id=cid,
                    vendor=candidate.get("vendor_name", "Unknown"),
                    reason="pending_inference",
                    discovered_at=candidate.get("created_at") or candidate.get("updated_at"),
                ))
                continue

            # pipe_id is a primary key in DCL's PipeDefinitionStore —
            # export only one connection per unique pipe_id, keeping
            # the most recently updated candidate.
            if matched_pipe_id in seen_pipe_ids:
                skipped.append(SkippedConnection(
                    candidate_id=cid,
                    vendor=candidate.get("vendor_name", "Unknown"),
                    reason="duplicate_pipe_id",
                    discovered_at=candidate.get("created_at") or candidate.get("updated_at"),
                ))
                continue
            seen_pipe_ids.add(matched_pipe_id)

            resolved_fields = _resolve_fields(candidate, field_maps)

            pipe_meta = field_maps["pipe_metadata"].get(matched_pipe_id, {})

            connection = DCLConnectionSchema(
                pipe_id=matched_pipe_id,
                candidate_id=cid,
                source_name=candidate.get("display_name", "Unknown"),
                vendor=candidate.get("vendor_name", "Unknown"),
                category=_normalize_export_category(candidate.get("category"), candidate.get("vendor_name")),
                governance_status=candidate.get("governance_status"),
                fields=resolved_fields,
                entity_scope=pipe_meta.get("entity_scope"),
                identity_keys=pipe_meta.get("identity_keys"),
                transport_kind=pipe_meta.get("transport_kind"),
                modality=pipe_meta.get("modality"),
                change_semantics=pipe_meta.get("change_semantics"),
                health="unknown",
                last_sync=candidate.get("updated_at"),
                asset_key=candidate.get("asset_key", ""),
                aod_asset_id=candidate.get("aod_asset_id"),
            )
            connections.append(connection)

        if connections:
            fabric_plane_obj = DCLFabricPlane(
                plane_type=plane["plane_type"],
                vendor=plane["vendor"],
                connection_count=len(connections),
                connections=connections,
                health="healthy" if plane["is_healthy"] else "degraded"
            )
            fabric_planes_output.append(fabric_plane_obj)
            total_connections += len(connections)

    if skipped:
        _log.info(
            "DCL export: %d connections exported, %d skipped (pending inference)",
            total_connections, len(skipped),
        )

    return DCLExportResponse(
        aod_run_id=aod_run_id,
        timestamp=datetime.utcnow().isoformat() + "Z",
        fabric_planes=fabric_planes_output,
        total_connections=total_connections,
        skipped_connections=skipped,
        skipped_count=len(skipped),
        source="aam",
    )
