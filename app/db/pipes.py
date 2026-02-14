"""
Pipe CRUD operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection, get_db

# ============================================================================
# PIPE OPERATIONS
# ============================================================================

def create_pipe(pipe_data: dict) -> dict:
    """Create a new declared pipe (pipe + initial version in one transaction)."""
    pipe_id = pipe_data.get("pipe_id", str(uuid.uuid4()))
    now = datetime.utcnow().isoformat()
    schema_hash = pipe_data.get("schema_info", {}).get("schema_hash") if pipe_data.get("schema_info") else None

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO declared_pipes (
                pipe_id, display_name, fabric_plane, modality, source_system, transport_kind,
                endpoint_ref, entity_scope, identity_keys, change_semantics,
                provenance, owner_signals, trust_labels, schema_info, freshness,
                access_info, version, schema_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pipe_id,
            pipe_data["display_name"],
            pipe_data.get("fabric_plane"),  # None is valid — means unrouted
            pipe_data["modality"],
            pipe_data["source_system"],
            pipe_data["transport_kind"],
            json.dumps(pipe_data.get("endpoint_ref", {})),
            json.dumps(pipe_data.get("entity_scope", [])),
            json.dumps(pipe_data.get("identity_keys", [])),
            pipe_data.get("change_semantics", "UNKNOWN"),
            json.dumps(pipe_data["provenance"]),
            json.dumps(pipe_data.get("owner_signals", [])),
            json.dumps(pipe_data.get("trust_labels", [])),
            json.dumps(pipe_data.get("schema_info")) if pipe_data.get("schema_info") else None,
            pipe_data.get("freshness"),
            json.dumps(pipe_data.get("access")) if pipe_data.get("access") else None,
            1,
            schema_hash,
            now,
            now
        ))

        version_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO pipe_versions (version_id, pipe_id, version, schema_hash, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (version_id, pipe_id, 1, schema_hash, json.dumps(pipe_data), now))

    return {"pipe_id": pipe_id, "version": 1, "created_at": now, "updated_at": now}


def get_pipe(pipe_id: str) -> Optional[dict]:
    """Get a pipe from declared_pipes ONLY.

    Use get_pipe_or_candidate() when you need the UI fallback that also
    checks connection_candidates (e.g. /api/pipes/{id} where pipe_id may
    actually be a candidate_id from list_candidates_as_pipes).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM declared_pipes WHERE pipe_id = ?", (pipe_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return _row_to_pipe(row)
    return None


def get_pipe_or_candidate(pipe_id: str) -> Optional[dict]:
    """Get a pipe by ID, falling back to connection_candidates.

    This exists for UI compatibility — list_candidates_as_pipes() returns
    candidate_ids as pipe_ids, so the UI may pass a candidate_id here.
    Prefer get_pipe() in non-UI code paths.
    """
    result = get_pipe(pipe_id)
    if result:
        return result

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.*, fp.plane_type as fabric_plane
        FROM connection_candidates c
        LEFT JOIN fabric_planes fp ON c.fabric_plane_id = fp.plane_id
        WHERE c.candidate_id = ?
    """, (pipe_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return _candidate_to_pipe(row)
    return None


def list_candidates_as_pipes(source_system: Optional[str] = None, fabric_plane: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """
    List candidates converted to pipe format for UI compatibility.

    IMPORTANT: This reads connection_candidates, NOT declared_pipes.
    Use list_declared_pipes() for actual pipes created during inference.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    conditions = []
    params = []
    
    if source_system:
        conditions.append("vendor_name = ?")
        params.append(source_system)
    
    if fabric_plane:
        # Filter by fabric plane type via the fabric_plane_id JOIN
        conditions.append("UPPER(fp.plane_type) = ?")
        params.append(fabric_plane.upper())
    
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"""
        SELECT c.*, fp.plane_type as fabric_plane
        FROM connection_candidates c
        LEFT JOIN fabric_planes fp ON c.fabric_plane_id = fp.plane_id
        {where_clause}
        ORDER BY c.category, c.created_at DESC
    """
    
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cursor.execute(query, params)
    
    rows = cursor.fetchall()
    conn.close()
    
    # Convert candidates to pipe format for UI compatibility
    return [_candidate_to_pipe(row) for row in rows]


def get_pipe_versions(pipe_id: str) -> list[dict]:
    """Get version history for a pipe"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM pipe_versions WHERE pipe_id = ? ORDER BY version DESC",
        (pipe_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "version_id": row["version_id"],
        "pipe_id": row["pipe_id"],
        "version": row["version"],
        "schema_hash": row["schema_hash"],
        "payload": json.loads(row["payload"]),
        "created_at": row["created_at"]
    } for row in rows]


def update_pipe_with_version(pipe_id: str, pipe_data: dict, new_schema_hash: Optional[str] = None) -> dict:
    """Update a pipe, version it, and detect drift — all in one transaction."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT version, schema_hash FROM declared_pipes WHERE pipe_id = ?", (pipe_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Pipe {pipe_id} not found")

        new_version = row["version"] + 1
        old_schema_hash = row["schema_hash"]
        now = datetime.utcnow().isoformat()

        cursor.execute("""
            UPDATE declared_pipes SET
                display_name = ?, modality = ?, source_system = ?, transport_kind = ?,
                endpoint_ref = ?, entity_scope = ?, identity_keys = ?, change_semantics = ?,
                provenance = ?, owner_signals = ?, trust_labels = ?, schema_info = ?,
                freshness = ?, access_info = ?, version = ?, schema_hash = ?, updated_at = ?
            WHERE pipe_id = ?
        """, (
            pipe_data["display_name"],
            pipe_data["modality"],
            pipe_data["source_system"],
            pipe_data["transport_kind"],
            json.dumps(pipe_data.get("endpoint_ref", {})),
            json.dumps(pipe_data.get("entity_scope", [])),
            json.dumps(pipe_data.get("identity_keys", [])),
            pipe_data.get("change_semantics", "UNKNOWN"),
            json.dumps(pipe_data["provenance"]),
            json.dumps(pipe_data.get("owner_signals", [])),
            json.dumps(pipe_data.get("trust_labels", [])),
            json.dumps(pipe_data.get("schema_info")) if pipe_data.get("schema_info") else None,
            pipe_data.get("freshness"),
            json.dumps(pipe_data.get("access")) if pipe_data.get("access") else None,
            new_version,
            new_schema_hash,
            now,
            pipe_id
        ))

        version_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO pipe_versions (version_id, pipe_id, version, schema_hash, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (version_id, pipe_id, new_version, new_schema_hash, json.dumps(pipe_data), now))

        drift_detected = False
        if old_schema_hash and new_schema_hash and old_schema_hash != new_schema_hash:
            drift_detected = True
            cursor.execute("""
                INSERT INTO drift_events (drift_id, pipe_id, drift_type, old_value, new_value, detected_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), pipe_id, "schema", old_schema_hash, new_schema_hash, now))

    return {"pipe_id": pipe_id, "version": new_version, "drift_detected": drift_detected}


def _candidate_to_pipe(row) -> dict:
    """
    Convert candidate row to pipe format for UI compatibility.
    CANONICAL: Candidates = Pipes

    Uses actual plane type and endpoint data to infer transport and modality
    instead of hardcoded defaults.
    """
    from ..plane_resolution import (
        infer_transport_from_plane_and_endpoints,
        infer_modality_from_plane_and_category,
        parse_plane_type,
    )

    keys = row.keys()

    # Extract fabric plane type: JOIN result → connected_via_plane → None
    fabric_plane = None
    if "fabric_plane" in keys and row["fabric_plane"]:
        fabric_plane = row["fabric_plane"].upper()
    if not fabric_plane and "fabric_plane_id" in keys and row["fabric_plane_id"]:
        fabric_plane = parse_plane_type(row["fabric_plane_id"])
    if not fabric_plane and "connected_via_plane" in keys and row["connected_via_plane"]:
        fabric_plane = row["connected_via_plane"].upper()

    # Infer transport and modality from actual data — NOT hardcoded
    endpoints = json.loads(row["known_endpoints"]) if row["known_endpoints"] else []
    vendor_name = row["vendor_name"]
    category = row["category"]

    transport_kind = infer_transport_from_plane_and_endpoints(
        fabric_plane, vendor_name, endpoints,
    )
    modality = infer_modality_from_plane_and_category(
        fabric_plane, category, vendor_name,
    )

    return {
        "pipe_id": row["candidate_id"],  # Candidate ID = Pipe ID
        "display_name": row["display_name"],
        "fabric_plane": fabric_plane,
        "modality": modality,
        "source_system": vendor_name,
        "transport_kind": transport_kind,
        "endpoint_ref": {"endpoints": endpoints},
        "entity_scope": [category] if category else [],
        "identity_keys": [],
        "change_semantics": "UNKNOWN",
        "provenance": {
            "discovered_by": "aod",
            "discovered_at": row["created_at"],
            "aod_run_id": row["aod_run_id"] if "aod_run_id" in keys else None
        },
        "owner_signals": [],
        "trust_labels": [row["governance_status"]] if "governance_status" in keys and row["governance_status"] else [],
        "schema_info": None,
        "freshness": None,
        "access": None,
        "version": 1,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }


def _row_to_pipe(row) -> dict:
    """Convert database row to pipe dict"""
    provenance = json.loads(row["provenance"]) if row["provenance"] else {}
    schema_info = json.loads(row["schema_info"]) if row["schema_info"] else None
    access_info = json.loads(row["access_info"]) if row["access_info"] else None

    keys = row.keys()
    fabric_plane = row["fabric_plane"] if "fabric_plane" in keys and row["fabric_plane"] else None

    return {
        "pipe_id": row["pipe_id"],
        "display_name": row["display_name"],
        "fabric_plane": fabric_plane,
        "modality": row["modality"],
        "source_system": row["source_system"],
        "transport_kind": row["transport_kind"],
        "endpoint_ref": json.loads(row["endpoint_ref"]) if row["endpoint_ref"] else {},
        "entity_scope": json.loads(row["entity_scope"]) if row["entity_scope"] else [],
        "identity_keys": json.loads(row["identity_keys"]) if row["identity_keys"] else [],
        "change_semantics": row["change_semantics"],
        "provenance": provenance,
        "owner_signals": json.loads(row["owner_signals"]) if row["owner_signals"] else [],
        "trust_labels": json.loads(row["trust_labels"]) if row["trust_labels"] else [],
        "schema_info": schema_info,
        "freshness": row["freshness"],
        "access": access_info,
        "version": row["version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }


def list_declared_pipes(source_system: Optional[str] = None, fabric_plane: Optional[str] = None) -> list[dict]:
    """List actual pipes from the declared_pipes table.

    Unlike list_candidates_as_pipes() (which returns candidates), this reads
    real pipes created during inference/matching.  Used by matching
    (Strategy 1) and the DCL export.
    """
    conn = get_connection()
    cursor = conn.cursor()

    conditions = []
    params = []
    if source_system:
        conditions.append("source_system = ?")
        params.append(source_system)
    if fabric_plane:
        conditions.append("UPPER(fabric_plane) = ?")
        params.append(fabric_plane.upper())

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    cursor.execute(
        f"SELECT * FROM declared_pipes{where} ORDER BY created_at DESC",
        params,
    )
    rows = cursor.fetchall()
    conn.close()
    return [_row_to_pipe(row) for row in rows]


