"""
Pipe CRUD operations
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from . import supabase_client as sb

# ============================================================================
# PIPE OPERATIONS
# ============================================================================

def create_pipe(pipe_data: dict) -> dict:
    """Create a new declared pipe (pipe + initial version)."""
    pipe_id = pipe_data.get("pipe_id", str(uuid.uuid4()))
    now = datetime.utcnow().isoformat()
    schema_hash = pipe_data.get("schema_info", {}).get("schema_hash") if pipe_data.get("schema_info") else None

    sb.insert("declared_pipes", {
        "pipe_id": pipe_id,
        "display_name": pipe_data["display_name"],
        "fabric_plane": pipe_data.get("fabric_plane"),
        "modality": pipe_data["modality"],
        "source_system": pipe_data["source_system"],
        "transport_kind": pipe_data["transport_kind"],
        "endpoint_ref": json.dumps(pipe_data.get("endpoint_ref", {})),
        "entity_scope": json.dumps(pipe_data.get("entity_scope", [])),
        "identity_keys": json.dumps(pipe_data.get("identity_keys", [])),
        "change_semantics": pipe_data.get("change_semantics", "UNKNOWN"),
        "provenance": json.dumps(pipe_data["provenance"]),
        "owner_signals": json.dumps(pipe_data.get("owner_signals", [])),
        "trust_labels": json.dumps(pipe_data.get("trust_labels", [])),
        "schema_info": json.dumps(pipe_data.get("schema_info")) if pipe_data.get("schema_info") else None,
        "freshness": pipe_data.get("freshness"),
        "access_info": json.dumps(pipe_data.get("access")) if pipe_data.get("access") else None,
        "version": 1,
        "schema_hash": schema_hash,
        "created_at": now,
        "updated_at": now,
    })

    version_id = str(uuid.uuid4())
    sb.insert("pipe_versions", {
        "version_id": version_id,
        "pipe_id": pipe_id,
        "version": 1,
        "schema_hash": schema_hash,
        "payload": json.dumps(pipe_data),
        "created_at": now,
    })

    return {"pipe_id": pipe_id, "version": 1, "created_at": now, "updated_at": now}


def get_pipe(pipe_id: str) -> Optional[dict]:
    """
    Get a pipe by ID.
    CANONICAL: Pipes = Candidates, so check candidates first.
    """
    candidate = sb.select(
        "connection_candidates",
        filters={"candidate_id": pipe_id},
        single=True,
    )

    if candidate:
        fabric_plane = None
        if candidate.get("fabric_plane_id"):
            fp = sb.select(
                "fabric_planes",
                filters={"plane_id": candidate["fabric_plane_id"]},
                single=True,
            )
            if fp:
                fabric_plane = fp.get("plane_type")
        candidate["fabric_plane"] = fabric_plane
        return _candidate_to_pipe(candidate)

    pipe = sb.select(
        "declared_pipes",
        filters={"pipe_id": pipe_id},
        single=True,
    )
    if pipe:
        return _row_to_pipe(pipe)
    return None


def list_pipes(source_system: Optional[str] = None, fabric_plane: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """
    List pipes with optional filters.

    CANONICAL DEFINITION: Pipes = Candidates
    This function queries connection_candidates (the source of truth).
    """
    filters = {}
    if source_system:
        filters["vendor_name"] = source_system

    rows = sb.select(
        "connection_candidates",
        filters=filters if filters else None,
        order="category.asc,created_at.desc",
        limit=limit,
    )

    if not rows:
        return []

    plane_ids = {r["fabric_plane_id"] for r in rows if r.get("fabric_plane_id")}
    plane_map = {}
    if plane_ids:
        planes = sb.select("fabric_planes")
        plane_map = {p["plane_id"]: p.get("plane_type") for p in planes}

    results = []
    for r in rows:
        fp_id = r.get("fabric_plane_id")
        r["fabric_plane"] = plane_map.get(fp_id) if fp_id else None
        pipe = _candidate_to_pipe(r)
        if fabric_plane and pipe["fabric_plane"].upper() != fabric_plane.upper():
            continue
        results.append(pipe)

    return results


def get_pipe_versions(pipe_id: str) -> list[dict]:
    """Get version history for a pipe"""
    rows = sb.select(
        "pipe_versions",
        filters={"pipe_id": pipe_id},
        order="version.desc",
    )

    return [{
        "version_id": row["version_id"],
        "pipe_id": row["pipe_id"],
        "version": row["version"],
        "schema_hash": row["schema_hash"],
        "payload": json.loads(row["payload"]),
        "created_at": row["created_at"],
    } for row in rows]


def update_pipe_with_version(pipe_id: str, pipe_data: dict, new_schema_hash: Optional[str] = None) -> dict:
    """Update a pipe, version it, and detect drift."""
    row = sb.select(
        "declared_pipes",
        filters={"pipe_id": pipe_id},
        single=True,
    )
    if not row:
        raise ValueError(f"Pipe {pipe_id} not found")

    new_version = row["version"] + 1
    old_schema_hash = row.get("schema_hash")
    now = datetime.utcnow().isoformat()

    sb.update("declared_pipes", {
        "display_name": pipe_data["display_name"],
        "modality": pipe_data["modality"],
        "source_system": pipe_data["source_system"],
        "transport_kind": pipe_data["transport_kind"],
        "endpoint_ref": json.dumps(pipe_data.get("endpoint_ref", {})),
        "entity_scope": json.dumps(pipe_data.get("entity_scope", [])),
        "identity_keys": json.dumps(pipe_data.get("identity_keys", [])),
        "change_semantics": pipe_data.get("change_semantics", "UNKNOWN"),
        "provenance": json.dumps(pipe_data["provenance"]),
        "owner_signals": json.dumps(pipe_data.get("owner_signals", [])),
        "trust_labels": json.dumps(pipe_data.get("trust_labels", [])),
        "schema_info": json.dumps(pipe_data.get("schema_info")) if pipe_data.get("schema_info") else None,
        "freshness": pipe_data.get("freshness"),
        "access_info": json.dumps(pipe_data.get("access")) if pipe_data.get("access") else None,
        "version": new_version,
        "schema_hash": new_schema_hash,
        "updated_at": now,
    }, filters={"pipe_id": pipe_id})

    version_id = str(uuid.uuid4())
    sb.insert("pipe_versions", {
        "version_id": version_id,
        "pipe_id": pipe_id,
        "version": new_version,
        "schema_hash": new_schema_hash,
        "payload": json.dumps(pipe_data),
        "created_at": now,
    })

    drift_detected = False
    if old_schema_hash and new_schema_hash and old_schema_hash != new_schema_hash:
        drift_detected = True
        sb.insert("drift_events", {
            "drift_id": str(uuid.uuid4()),
            "pipe_id": pipe_id,
            "drift_type": "schema",
            "old_value": old_schema_hash,
            "new_value": new_schema_hash,
            "detected_at": now,
        })

    return {"pipe_id": pipe_id, "version": new_version, "drift_detected": drift_detected}


def _candidate_to_pipe(row) -> dict:
    """
    Convert candidate row to pipe format for UI compatibility.
    CANONICAL: Candidates = Pipes

    Derives transport_kind, modality, and trust_labels from the inferred
    fabric plane rather than hardcoding defaults.
    """
    fabric_plane = None
    if row.get("fabric_plane"):
        fabric_plane = row["fabric_plane"].upper()
    if not fabric_plane and row.get("connected_via_plane"):
        fabric_plane = row["connected_via_plane"].upper()
    if not fabric_plane:
        fabric_plane = "UNMAPPED"

    transport_kind = "API"
    modality = "DECLARED_INTERFACE"
    if fabric_plane == "EVENT_BUS":
        transport_kind = "EVENT_STREAM"
        modality = "PASSIVE_SUBSCRIPTION"
    elif fabric_plane == "DATA_WAREHOUSE":
        transport_kind = "TABLE"
    elif fabric_plane == "IPAAS":
        transport_kind = "WEBHOOK"
        modality = "CONTROL_PLANE"

    trust_labels = []
    if row.get("governance_status"):
        trust_labels.append(row["governance_status"])
    match_reason = row.get("match_reason") or ""
    if "aod_explicit" in match_reason:
        trust_labels.append("inferred:aod_explicit")
    elif "infra_vendor_identity" in match_reason or "Vendor match, inferred" in match_reason:
        trust_labels.append("inferred:vendor_identity")
    elif "display_name_hint" in match_reason:
        trust_labels.append("inferred:display_name_hint")
    elif "evidence_signal" in match_reason:
        trust_labels.append("inferred:evidence_signal")
    elif "needs_operator_review" in match_reason:
        trust_labels.append("needs_operator_review")

    provenance = {
        "discovered_by": "aod",
        "discovered_at": row.get("created_at"),
        "aod_run_id": row.get("aod_run_id"),
    }
    if match_reason:
        provenance["routing_source"] = match_reason

    return {
        "pipe_id": row["candidate_id"],
        "matched_pipe_id": row.get("matched_pipe_id"),
        "display_name": row["display_name"],
        "fabric_plane": fabric_plane,
        "modality": modality,
        "source_system": row["vendor_name"],
        "transport_kind": transport_kind,
        "endpoint_ref": {"endpoints": json.loads(row["known_endpoints"]) if row.get("known_endpoints") else []},
        "entity_scope": [row["category"]] if row.get("category") else [],
        "identity_keys": [],
        "change_semantics": "UNKNOWN",
        "provenance": provenance,
        "owner_signals": [],
        "trust_labels": trust_labels,
        "schema_info": None,
        "freshness": None,
        "access": None,
        "version": 1,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _row_to_pipe(row) -> dict:
    """Convert database row to pipe dict"""
    provenance = json.loads(row["provenance"]) if row.get("provenance") else {}
    schema_info = json.loads(row["schema_info"]) if row.get("schema_info") else None
    access_info = json.loads(row["access_info"]) if row.get("access_info") else None

    fabric_plane = row.get("fabric_plane") or "UNKNOWN"

    return {
        "pipe_id": row["pipe_id"],
        "display_name": row["display_name"],
        "fabric_plane": fabric_plane,
        "modality": row["modality"],
        "source_system": row["source_system"],
        "transport_kind": row["transport_kind"],
        "endpoint_ref": json.loads(row["endpoint_ref"]) if row.get("endpoint_ref") else {},
        "entity_scope": json.loads(row["entity_scope"]) if row.get("entity_scope") else [],
        "identity_keys": json.loads(row["identity_keys"]) if row.get("identity_keys") else [],
        "change_semantics": row.get("change_semantics"),
        "provenance": provenance,
        "owner_signals": json.loads(row["owner_signals"]) if row.get("owner_signals") else [],
        "trust_labels": json.loads(row["trust_labels"]) if row.get("trust_labels") else [],
        "schema_info": schema_info,
        "freshness": row.get("freshness"),
        "access": access_info,
        "version": row.get("version"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
