"""
AAM (Adaptive API Mesh) - Database Layer

SQLite database for:
- Connection candidates (from AOD)
- Declared pipes (for DCL)
- Pipe versions and drift events
- Collector observations
"""
import sqlite3
import json
from datetime import datetime
from typing import Optional
import uuid

DATABASE = "aam.db"


def get_connection():
    """Get database connection with row factory"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def _add_column_if_not_exists(cursor, table_name: str, column_name: str, column_def: str):
    """Add a column to a table if it doesn't exist"""
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def init_db():
    """Initialize database schema"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Connection Candidates (input from AOD)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS connection_candidates (
            candidate_id TEXT PRIMARY KEY,
            asset_key TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            category TEXT NOT NULL,
            governance_status TEXT,
            findings TEXT,
            sor_tagging TEXT,
            evidence_refs TEXT,
            signals_summary TEXT,
            known_endpoints TEXT,
            preferred_modality TEXT,
            priority_score REAL,
            status TEXT DEFAULT 'connected',
            matched_pipe_id TEXT,
            match_score REAL,
            match_reason TEXT,
            deferred_reason TEXT,
            -- AOD Handoff Fields --
            execution_allowed INTEGER DEFAULT 1,
            action_type TEXT DEFAULT 'provision',
            blocking_findings TEXT,
            connected_via_plane TEXT,
            aod_run_id TEXT,
            aod_asset_id TEXT,
            -- Timestamps --
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # AOD Policy Manifest (governance rules from AOD)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aod_policy_manifest (
            policy_id TEXT PRIMARY KEY,
            policy_version TEXT NOT NULL,
            governance_rules TEXT,
            blocking_finding_types TEXT,
            fabric_plane_routing TEXT,
            auto_provision_categories TEXT,
            require_human_review TEXT,
            is_active INTEGER DEFAULT 1,
            received_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # AOD Handoff Log (track batch handoffs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aod_handoff_log (
            handoff_id TEXT PRIMARY KEY,
            aod_run_id TEXT NOT NULL,
            candidates_received INTEGER NOT NULL,
            candidates_accepted INTEGER NOT NULL,
            candidates_rejected INTEGER NOT NULL,
            rejected_reasons TEXT,
            policy_version TEXT,
            handoff_timestamp TEXT NOT NULL,
            processed_at TEXT NOT NULL
        )
    """)
    
    # Collectors
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collectors (
            collector_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            collector_type TEXT NOT NULL,
            description TEXT,
            enabled INTEGER DEFAULT 1,
            config TEXT,
            last_run TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    # Observations (raw data from collectors)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            observation_id TEXT PRIMARY KEY,
            collector_id TEXT NOT NULL,
            candidate_id TEXT,
            observed_at TEXT NOT NULL,
            source_system TEXT NOT NULL,
            endpoint_info TEXT NOT NULL,
            entity_hints TEXT,
            schema_sample TEXT,
            metadata TEXT,
            processed INTEGER DEFAULT 0,
            FOREIGN KEY (collector_id) REFERENCES collectors(collector_id),
            FOREIGN KEY (candidate_id) REFERENCES connection_candidates(candidate_id)
        )
    """)
    
    # Declared Pipes (output for DCL)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS declared_pipes (
            pipe_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            fabric_plane TEXT NOT NULL DEFAULT 'API_GATEWAY',
            modality TEXT NOT NULL,
            source_system TEXT NOT NULL,
            transport_kind TEXT NOT NULL,
            endpoint_ref TEXT,
            entity_scope TEXT,
            identity_keys TEXT,
            change_semantics TEXT DEFAULT 'UNKNOWN',
            provenance TEXT NOT NULL,
            owner_signals TEXT,
            trust_labels TEXT,
            schema_info TEXT,
            freshness TEXT,
            access_info TEXT,
            version INTEGER DEFAULT 1,
            schema_hash TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    # Pipe Versions (version history)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipe_versions (
            version_id TEXT PRIMARY KEY,
            pipe_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            schema_hash TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (pipe_id) REFERENCES declared_pipes(pipe_id)
        )
    """)
    
    # Drift Events
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drift_events (
            drift_id TEXT PRIMARY KEY,
            pipe_id TEXT NOT NULL,
            drift_type TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            details TEXT,
            detected_at TEXT NOT NULL,
            FOREIGN KEY (pipe_id) REFERENCES declared_pipes(pipe_id)
        )
    """)
    
    # Tee Requests
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tee_requests (
            tee_id TEXT PRIMARY KEY,
            pipe_id TEXT NOT NULL,
            target_system TEXT NOT NULL,
            tee_type TEXT NOT NULL,
            configuration TEXT,
            status TEXT DEFAULT 'requested',
            requested_at TEXT NOT NULL,
            approved_at TEXT,
            verified_at TEXT,
            FOREIGN KEY (pipe_id) REFERENCES declared_pipes(pipe_id)
        )
    """)
    
    # Collector Runs (track collector execution history)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS collector_runs (
            run_id TEXT PRIMARY KEY,
            collector_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            observations_count INTEGER DEFAULT 0,
            error_message TEXT,
            FOREIGN KEY (collector_id) REFERENCES collectors(collector_id)
        )
    """)
    
    # Add new columns to drift_events table (v1 Practical Interface)
    _add_column_if_not_exists(cursor, "drift_events", "severity", "TEXT DEFAULT 'medium'")
    _add_column_if_not_exists(cursor, "drift_events", "status", "TEXT DEFAULT 'open'")
    _add_column_if_not_exists(cursor, "drift_events", "acknowledged_at", "TEXT")
    _add_column_if_not_exists(cursor, "drift_events", "acknowledged_by", "TEXT")
    _add_column_if_not_exists(cursor, "drift_events", "suppressed_at", "TEXT")
    _add_column_if_not_exists(cursor, "drift_events", "suppressed_by", "TEXT")
    _add_column_if_not_exists(cursor, "drift_events", "notes", "TEXT")
    
    # Add new columns to connection_candidates table (v1 Practical Interface)
    _add_column_if_not_exists(cursor, "connection_candidates", "matched_pipe_id", "TEXT")
    _add_column_if_not_exists(cursor, "connection_candidates", "match_score", "REAL")
    _add_column_if_not_exists(cursor, "connection_candidates", "match_reason", "TEXT")
    _add_column_if_not_exists(cursor, "connection_candidates", "deferred_reason", "TEXT")
    
    # Add fabric_plane column to declared_pipes (Framework Stability phase)
    _add_column_if_not_exists(cursor, "declared_pipes", "fabric_plane", "TEXT DEFAULT 'API_GATEWAY'")
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_status ON connection_candidates(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_asset_key ON connection_candidates(asset_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipes_source ON declared_pipes(source_system)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_observations_collector ON observations(collector_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_drift_pipe ON drift_events(pipe_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_collector_runs_collector ON collector_runs(collector_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_drift_status ON drift_events(status)")
    
    # Insert default mock collector
    cursor.execute("""
        INSERT OR IGNORE INTO collectors (collector_id, name, collector_type, description, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        "mock-collector-001",
        "Mock Collector",
        "mock",
        "Generates sample observations from JSON for testing",
        datetime.utcnow().isoformat()
    ))
    
    conn.commit()
    conn.close()
    print("✓ AAM Database initialized")


# ============================================================================
# CANDIDATE OPERATIONS
# ============================================================================

def create_candidate(candidate_data: dict) -> dict:
    """Create a new connection candidate"""
    conn = get_connection()
    cursor = conn.cursor()

    candidate_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # Handle AOD execution_allowed (convert bool to int for SQLite)
    execution_allowed = candidate_data.get("execution_allowed", True)
    if isinstance(execution_allowed, bool):
        execution_allowed = 1 if execution_allowed else 0

    # Deduplication: Delete existing candidate with same asset_key to prevent duplicates
    asset_key = candidate_data["asset_key"]
    cursor.execute("DELETE FROM connection_candidates WHERE asset_key = ?", (asset_key,))

    cursor.execute("""
        INSERT INTO connection_candidates (
            candidate_id, asset_key, vendor_name, display_name, category,
            governance_status, findings, sor_tagging, evidence_refs,
            signals_summary, known_endpoints, preferred_modality, priority_score,
            status, execution_allowed, action_type, blocking_findings,
            connected_via_plane, aod_run_id, aod_asset_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        candidate_id,
        candidate_data["asset_key"],
        candidate_data["vendor_name"],
        candidate_data["display_name"],
        candidate_data["category"],
        candidate_data.get("governance_status"),
        json.dumps(candidate_data.get("findings", [])),
        candidate_data.get("sor_tagging"),
        json.dumps(candidate_data.get("evidence_refs", [])),
        candidate_data.get("signals_summary"),
        json.dumps(candidate_data.get("known_endpoints", [])),
        candidate_data.get("preferred_modality"),
        candidate_data.get("priority_score"),
        "new",
        execution_allowed,
        candidate_data.get("action_type", "provision"),
        json.dumps(candidate_data.get("blocking_findings", [])),
        candidate_data.get("connected_via_plane"),
        candidate_data.get("aod_run_id"),
        candidate_data.get("aod_asset_id"),
        now,
        now
    ))

    conn.commit()
    conn.close()

    return {
        "candidate_id": candidate_id,
        "status": "connected",
        "execution_allowed": bool(execution_allowed),
        "action_type": candidate_data.get("action_type", "provision"),
        "created_at": now,
        "updated_at": now
    }


def get_candidate(candidate_id: str) -> Optional[dict]:
    """Get a candidate by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM connection_candidates WHERE candidate_id = ?", (candidate_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return _row_to_candidate(row)
    return None


def list_candidates(status: Optional[str] = None, limit: int = 100) -> list[dict]:
    """List candidates with optional status filter, sorted by category"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if status:
        cursor.execute(
            "SELECT * FROM connection_candidates WHERE status = ? ORDER BY category ASC, created_at DESC LIMIT ?",
            (status, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM connection_candidates ORDER BY category ASC, created_at DESC LIMIT ?",
            (limit,)
        )
    
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_candidate(row) for row in rows]


def update_candidate_status(candidate_id: str, status: str) -> bool:
    """Update candidate status"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE connection_candidates SET status = ?, updated_at = ? WHERE candidate_id = ?",
        (status, datetime.utcnow().isoformat(), candidate_id)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def _row_to_candidate(row) -> dict:
    """Convert database row to candidate dict"""
    keys = row.keys()

    result = {
        "candidate_id": row["candidate_id"],
        "asset_key": row["asset_key"],
        "vendor_name": row["vendor_name"],
        "display_name": row["display_name"],
        "category": row["category"],
        "governance_status": row["governance_status"],
        "findings": json.loads(row["findings"]) if row["findings"] else [],
        "sor_tagging": row["sor_tagging"],
        "evidence_refs": json.loads(row["evidence_refs"]) if row["evidence_refs"] else [],
        "signals_summary": row["signals_summary"],
        "known_endpoints": json.loads(row["known_endpoints"]) if row["known_endpoints"] else [],
        "preferred_modality": row["preferred_modality"],
        "priority_score": row["priority_score"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }

    # Match/defer fields
    if "matched_pipe_id" in keys:
        result["matched_pipe_id"] = row["matched_pipe_id"]
    if "match_score" in keys:
        result["match_score"] = row["match_score"]
    if "match_reason" in keys:
        result["match_reason"] = row["match_reason"]
    if "deferred_reason" in keys:
        result["deferred_reason"] = row["deferred_reason"]

    # AOD Handoff fields
    if "execution_allowed" in keys:
        result["execution_allowed"] = bool(row["execution_allowed"])
    if "action_type" in keys:
        result["action_type"] = row["action_type"]
    if "blocking_findings" in keys:
        result["blocking_findings"] = json.loads(row["blocking_findings"]) if row["blocking_findings"] else []
    if "connected_via_plane" in keys:
        result["connected_via_plane"] = row["connected_via_plane"]
    if "aod_run_id" in keys:
        result["aod_run_id"] = row["aod_run_id"]
    if "aod_asset_id" in keys:
        result["aod_asset_id"] = row["aod_asset_id"]

    return result


# ============================================================================
# PIPE OPERATIONS
# ============================================================================

def create_pipe(pipe_data: dict) -> dict:
    """Create a new declared pipe"""
    conn = get_connection()
    cursor = conn.cursor()
    
    pipe_id = pipe_data.get("pipe_id", str(uuid.uuid4()))
    now = datetime.utcnow().isoformat()
    schema_hash = pipe_data.get("schema_info", {}).get("schema_hash") if pipe_data.get("schema_info") else None
    
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
        pipe_data.get("fabric_plane", "API_GATEWAY"),
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
    
    # Create initial version
    version_id = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO pipe_versions (version_id, pipe_id, version, schema_hash, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (version_id, pipe_id, 1, schema_hash, json.dumps(pipe_data), now))
    
    conn.commit()
    conn.close()
    
    return {"pipe_id": pipe_id, "version": 1, "created_at": now, "updated_at": now}


def get_pipe(pipe_id: str) -> Optional[dict]:
    """Get a pipe by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM declared_pipes WHERE pipe_id = ?", (pipe_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return _row_to_pipe(row)
    return None


def list_pipes(source_system: Optional[str] = None, fabric_plane: Optional[str] = None, limit: int = 100) -> list[dict]:
    """List pipes with optional source and fabric_plane filters"""
    conn = get_connection()
    cursor = conn.cursor()
    
    conditions = []
    params = []
    
    if source_system:
        conditions.append("source_system = ?")
        params.append(source_system)
    
    if fabric_plane:
        conditions.append("fabric_plane = ?")
        params.append(fabric_plane)
    
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)
        query = f"SELECT * FROM declared_pipes{where_clause} ORDER BY fabric_plane, source_system, created_at DESC LIMIT ?"
    else:
        query = "SELECT * FROM declared_pipes ORDER BY fabric_plane, source_system, created_at DESC LIMIT ?"
    
    params.append(limit)
    cursor.execute(query, params)
    
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_pipe(row) for row in rows]


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
    """Update a pipe and create a new version"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get current version
    cursor.execute("SELECT version, schema_hash FROM declared_pipes WHERE pipe_id = ?", (pipe_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Pipe {pipe_id} not found")
    
    current_version = row["version"]
    old_schema_hash = row["schema_hash"]
    new_version = current_version + 1
    now = datetime.utcnow().isoformat()
    
    # Update pipe
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
    
    # Create new version record
    version_id = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO pipe_versions (version_id, pipe_id, version, schema_hash, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (version_id, pipe_id, new_version, new_schema_hash, json.dumps(pipe_data), now))
    
    # Check for schema drift
    drift_id = None
    if old_schema_hash and new_schema_hash and old_schema_hash != new_schema_hash:
        drift_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO drift_events (drift_id, pipe_id, drift_type, old_value, new_value, detected_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (drift_id, pipe_id, "schema", old_schema_hash, new_schema_hash, now))
    
    conn.commit()
    conn.close()
    
    return {"pipe_id": pipe_id, "version": new_version, "drift_detected": drift_id is not None}


def _row_to_pipe(row) -> dict:
    """Convert database row to pipe dict"""
    provenance = json.loads(row["provenance"]) if row["provenance"] else {}
    schema_info = json.loads(row["schema_info"]) if row["schema_info"] else None
    access_info = json.loads(row["access_info"]) if row["access_info"] else None
    
    # Handle fabric_plane with fallback for older records
    keys = row.keys()
    fabric_plane = row["fabric_plane"] if "fabric_plane" in keys and row["fabric_plane"] else "API_GATEWAY"
    
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


# ============================================================================
# DRIFT OPERATIONS
# ============================================================================

def create_drift_event(pipe_id: str, drift_type: str, old_value: str, new_value: str, details: Optional[dict] = None) -> str:
    """Create a drift event"""
    conn = get_connection()
    cursor = conn.cursor()
    
    drift_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO drift_events (drift_id, pipe_id, drift_type, old_value, new_value, details, detected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (drift_id, pipe_id, drift_type, old_value, new_value, json.dumps(details) if details else None, now))
    
    conn.commit()
    conn.close()
    
    return drift_id


def _row_to_drift_event(row) -> dict:
    """Convert database row to drift event dict"""
    result = {
        "drift_id": row["drift_id"],
        "pipe_id": row["pipe_id"],
        "drift_type": row["drift_type"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "details": json.loads(row["details"]) if row["details"] else None,
        "detected_at": row["detected_at"]
    }
    keys = row.keys()
    if "severity" in keys:
        result["severity"] = row["severity"] or "medium"
    if "status" in keys:
        result["status"] = row["status"] or "open"
    if "acknowledged_at" in keys:
        result["acknowledged_at"] = row["acknowledged_at"]
    if "acknowledged_by" in keys:
        result["acknowledged_by"] = row["acknowledged_by"]
    if "suppressed_at" in keys:
        result["suppressed_at"] = row["suppressed_at"]
    if "suppressed_by" in keys:
        result["suppressed_by"] = row["suppressed_by"]
    if "notes" in keys:
        result["notes"] = row["notes"]
    return result


def get_drift_events(pipe_id: str) -> list[dict]:
    """Get drift events for a pipe"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM drift_events WHERE pipe_id = ? ORDER BY detected_at DESC",
        (pipe_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_drift_event(row) for row in rows]


def list_all_drift_events(limit: int = 100) -> list[dict]:
    """List all drift events"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drift_events ORDER BY detected_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_drift_event(row) for row in rows]


# ============================================================================
# OBSERVATION OPERATIONS
# ============================================================================

def create_observation(observation_data: dict) -> str:
    """Create a new observation"""
    conn = get_connection()
    cursor = conn.cursor()
    
    observation_id = observation_data.get("observation_id", str(uuid.uuid4()))
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO observations (
            observation_id, collector_id, candidate_id, observed_at,
            source_system, endpoint_info, entity_hints, schema_sample, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        observation_id,
        observation_data["collector_id"],
        observation_data.get("candidate_id"),
        observation_data.get("observed_at", now),
        observation_data["source_system"],
        json.dumps(observation_data["endpoint_info"]),
        json.dumps(observation_data.get("entity_hints", [])),
        json.dumps(observation_data.get("schema_sample")) if observation_data.get("schema_sample") else None,
        json.dumps(observation_data.get("metadata", {}))
    ))
    
    conn.commit()
    conn.close()
    
    return observation_id


def get_observations_for_candidate(candidate_id: str) -> list[dict]:
    """Get observations for a candidate"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM observations WHERE candidate_id = ? ORDER BY observed_at DESC",
        (candidate_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_observation(row) for row in rows]


def get_unprocessed_observations() -> list[dict]:
    """Get observations that haven't been processed"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM observations WHERE processed = 0 ORDER BY observed_at")
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_observation(row) for row in rows]


def mark_observation_processed(observation_id: str):
    """Mark an observation as processed"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE observations SET processed = 1 WHERE observation_id = ?", (observation_id,))
    conn.commit()
    conn.close()


def _row_to_observation(row) -> dict:
    """Convert database row to observation dict"""
    return {
        "observation_id": row["observation_id"],
        "collector_id": row["collector_id"],
        "candidate_id": row["candidate_id"],
        "observed_at": row["observed_at"],
        "source_system": row["source_system"],
        "endpoint_info": json.loads(row["endpoint_info"]),
        "entity_hints": json.loads(row["entity_hints"]) if row["entity_hints"] else [],
        "schema_sample": json.loads(row["schema_sample"]) if row["schema_sample"] else None,
        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        "processed": bool(row["processed"])
    }


# ============================================================================
# COLLECTOR OPERATIONS
# ============================================================================

def list_collectors() -> list[dict]:
    """List all collectors"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collectors ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "collector_id": row["collector_id"],
        "name": row["name"],
        "collector_type": row["collector_type"],
        "description": row["description"],
        "enabled": bool(row["enabled"]),
        "last_run": row["last_run"],
        "created_at": row["created_at"]
    } for row in rows]


def update_collector_last_run(collector_id: str):
    """Update collector's last run timestamp"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE collectors SET last_run = ? WHERE collector_id = ?",
        (datetime.utcnow().isoformat(), collector_id)
    )
    conn.commit()
    conn.close()


# ============================================================================
# COLLECTOR RUN OPERATIONS (v1 Practical Interface)
# ============================================================================

def create_collector_run(collector_id: str) -> str:
    """Create a new collector run and return the run_id"""
    conn = get_connection()
    cursor = conn.cursor()
    
    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO collector_runs (run_id, collector_id, status, started_at)
        VALUES (?, ?, ?, ?)
    """, (run_id, collector_id, "running", now))
    
    conn.commit()
    conn.close()
    
    return run_id


def complete_collector_run(run_id: str, status: str, observations_count: int, error_message: Optional[str] = None) -> bool:
    """Complete a collector run with final status"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        UPDATE collector_runs 
        SET status = ?, completed_at = ?, observations_count = ?, error_message = ?
        WHERE run_id = ?
    """, (status, now, observations_count, error_message, run_id))
    
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    return affected > 0


def get_collector_run(run_id: str) -> Optional[dict]:
    """Get a collector run by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collector_runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "run_id": row["run_id"],
            "collector_id": row["collector_id"],
            "status": row["status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "observations_count": row["observations_count"],
            "error_message": row["error_message"]
        }
    return None


def list_collector_runs(collector_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    """List collector runs with optional collector filter"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if collector_id:
        cursor.execute(
            "SELECT * FROM collector_runs WHERE collector_id = ? ORDER BY started_at DESC LIMIT ?",
            (collector_id, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM collector_runs ORDER BY started_at DESC LIMIT ?",
            (limit,)
        )
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "run_id": row["run_id"],
        "collector_id": row["collector_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "observations_count": row["observations_count"],
        "error_message": row["error_message"]
    } for row in rows]


# ============================================================================
# DRIFT STATUS OPERATIONS (v1 Practical Interface)
# ============================================================================

def update_drift_status(drift_id: str, status: str, by: Optional[str] = None, notes: Optional[str] = None) -> Optional[dict]:
    """Update drift event status (open, acknowledged, suppressed, resolved)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    if status == "acknowledged":
        cursor.execute("""
            UPDATE drift_events 
            SET status = ?, acknowledged_at = ?, acknowledged_by = ?, notes = COALESCE(?, notes)
            WHERE drift_id = ?
        """, (status, now, by, notes, drift_id))
    elif status == "suppressed":
        cursor.execute("""
            UPDATE drift_events 
            SET status = ?, suppressed_at = ?, suppressed_by = ?, notes = COALESCE(?, notes)
            WHERE drift_id = ?
        """, (status, now, by, notes, drift_id))
    else:
        cursor.execute("""
            UPDATE drift_events 
            SET status = ?, notes = COALESCE(?, notes)
            WHERE drift_id = ?
        """, (status, notes, drift_id))
    
    affected = cursor.rowcount
    conn.commit()
    
    if affected > 0:
        cursor.execute("SELECT * FROM drift_events WHERE drift_id = ?", (drift_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return _row_to_drift_event(row)
    
    conn.close()
    return None


# ============================================================================
# CANDIDATE MATCH OPERATIONS (v1 Practical Interface)
# ============================================================================

def update_candidate_match(candidate_id: str, pipe_id: str, score: float, reason: str) -> Optional[dict]:
    """Update candidate with match information"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        UPDATE connection_candidates 
        SET matched_pipe_id = ?, match_score = ?, match_reason = ?, 
            status = 'connected', updated_at = ?
        WHERE candidate_id = ?
    """, (pipe_id, score, reason, now, candidate_id))
    
    affected = cursor.rowcount
    conn.commit()
    
    if affected > 0:
        cursor.execute("SELECT * FROM connection_candidates WHERE candidate_id = ?", (candidate_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return _row_to_candidate(row)
    
    conn.close()
    return None


def update_candidate_deferred(candidate_id: str, reason: str) -> Optional[dict]:
    """Update candidate as deferred with reason"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        UPDATE connection_candidates 
        SET deferred_reason = ?, status = 'deferred', updated_at = ?
        WHERE candidate_id = ?
    """, (reason, now, candidate_id))
    
    affected = cursor.rowcount
    conn.commit()
    
    if affected > 0:
        cursor.execute("SELECT * FROM connection_candidates WHERE candidate_id = ?", (candidate_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return _row_to_candidate(row)
    
    conn.close()
    return None


# ============================================================================
# TEE REQUEST OPERATIONS (v1 Practical Interface)
# ============================================================================

def list_tee_requests(status: Optional[str] = None) -> list[dict]:
    """List tee requests with optional status filter"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if status:
        cursor.execute(
            "SELECT * FROM tee_requests WHERE status = ? ORDER BY requested_at DESC",
            (status,)
        )
    else:
        cursor.execute("SELECT * FROM tee_requests ORDER BY requested_at DESC")
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "tee_id": row["tee_id"],
        "pipe_id": row["pipe_id"],
        "target_system": row["target_system"],
        "tee_type": row["tee_type"],
        "configuration": json.loads(row["configuration"]) if row["configuration"] else {},
        "status": row["status"],
        "requested_at": row["requested_at"],
        "approved_at": row["approved_at"],
        "verified_at": row["verified_at"]
    } for row in rows]


def get_drift_event(drift_id: str) -> Optional[dict]:
    """Get a drift event by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drift_events WHERE drift_id = ?", (drift_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return _row_to_drift_event(row)
    return None


def get_tee_request(tee_id: str) -> Optional[dict]:
    """Get a single TEE request by ID"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tee_requests WHERE tee_id = ?", (tee_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "tee_id": row["tee_id"],
            "pipe_id": row["pipe_id"],
            "target_system": row["target_system"],
            "tee_type": row["tee_type"],
            "configuration": json.loads(row["configuration"]) if row["configuration"] else {},
            "status": row["status"],
            "requested_at": row["requested_at"],
            "approved_at": row["approved_at"],
            "verified_at": row["verified_at"]
        }
    return None


def create_tee_request(tee_data: dict) -> dict:
    """Create a new tee request"""
    conn = get_connection()
    cursor = conn.cursor()
    
    tee_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO tee_requests (
            tee_id, pipe_id, target_system, tee_type, configuration, status, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        tee_id,
        tee_data["pipe_id"],
        tee_data["target_system"],
        tee_data.get("tee_type", "api_proxy"),
        json.dumps(tee_data.get("configuration", {})),
        "requested",
        now
    ))
    
    conn.commit()
    conn.close()
    
    return {
        "tee_id": tee_id,
        "pipe_id": tee_data["pipe_id"],
        "target_system": tee_data["target_system"],
        "tee_type": tee_data.get("tee_type", "api_proxy"),
        "configuration": tee_data.get("configuration", {}),
        "status": "requested",
        "requested_at": now,
        "approved_at": None,
        "verified_at": None
    }


def update_tee_request_status(tee_id: str, status: str) -> Optional[dict]:
    """Update tee request status (requested, approved, verified)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    if status == "approved":
        cursor.execute("""
            UPDATE tee_requests SET status = ?, approved_at = ? WHERE tee_id = ?
        """, (status, now, tee_id))
    elif status == "verified":
        cursor.execute("""
            UPDATE tee_requests SET status = ?, verified_at = ? WHERE tee_id = ?
        """, (status, now, tee_id))
    else:
        cursor.execute("""
            UPDATE tee_requests SET status = ? WHERE tee_id = ?
        """, (status, tee_id))
    
    affected = cursor.rowcount
    conn.commit()
    
    if affected > 0:
        cursor.execute("SELECT * FROM tee_requests WHERE tee_id = ?", (tee_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "tee_id": row["tee_id"],
                "pipe_id": row["pipe_id"],
                "target_system": row["target_system"],
                "tee_type": row["tee_type"],
                "configuration": json.loads(row["configuration"]) if row["configuration"] else {},
                "status": row["status"],
                "requested_at": row["requested_at"],
                "approved_at": row["approved_at"],
                "verified_at": row["verified_at"]
            }
    
    conn.close()
    return None


# ============================================================================
# PRESET / SEED DATA OPERATIONS
# ============================================================================

def clear_all_data():
    """Clear all data from the database (for preset loading)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM drift_events")
    cursor.execute("DELETE FROM pipe_versions")
    cursor.execute("DELETE FROM declared_pipes")
    cursor.execute("DELETE FROM observations")
    cursor.execute("DELETE FROM collector_runs")
    cursor.execute("DELETE FROM connection_candidates")
    cursor.execute("DELETE FROM tee_requests")
    
    conn.commit()
    conn.close()
    
    return {"cleared": True}


def get_pipe_stats() -> dict:
    """Get statistics about pipes by fabric_plane and modality"""
    conn = get_connection()
    cursor = conn.cursor()

    stats = {
        "total_pipes": 0,
        "by_fabric_plane": {},
        "by_modality": {},
        "by_source_system": {}
    }

    cursor.execute("SELECT COUNT(*) FROM declared_pipes")
    stats["total_pipes"] = cursor.fetchone()[0]

    cursor.execute("SELECT fabric_plane, COUNT(*) FROM declared_pipes GROUP BY fabric_plane")
    for row in cursor.fetchall():
        plane = row[0] or "API_GATEWAY"
        stats["by_fabric_plane"][plane] = row[1]

    cursor.execute("SELECT modality, COUNT(*) FROM declared_pipes GROUP BY modality")
    for row in cursor.fetchall():
        stats["by_modality"][row[0]] = row[1]

    cursor.execute("SELECT source_system, COUNT(*) FROM declared_pipes GROUP BY source_system")
    for row in cursor.fetchall():
        stats["by_source_system"][row[0]] = row[1]

    conn.close()
    return stats


# ============================================================================
# TOPOLOGY / GRAPH OPERATIONS
# ============================================================================

def get_topology_data() -> dict:
    """
    Get all data needed for topology visualization.
    Returns nodes and edges for the graph.
    """
    conn = get_connection()
    cursor = conn.cursor()

    nodes = []
    edges = []

    # Track unique fabric planes and source systems
    fabric_planes = set()
    source_systems = set()

    # Get all pipes
    cursor.execute("""
        SELECT pipe_id, display_name, fabric_plane, source_system, modality,
               transport_kind, entity_scope, trust_labels, version
        FROM declared_pipes
    """)
    pipes = cursor.fetchall()

    for pipe in pipes:
        pipe_id = pipe["pipe_id"]
        fabric_plane = pipe["fabric_plane"] or "API_GATEWAY"
        source_system = pipe["source_system"]

        fabric_planes.add(fabric_plane)
        source_systems.add(source_system)

        # Add pipe node
        entity_scope = json.loads(pipe["entity_scope"]) if pipe["entity_scope"] else []
        trust_labels = json.loads(pipe["trust_labels"]) if pipe["trust_labels"] else []

        nodes.append({
            "id": f"pipe:{pipe_id}",
            "type": "pipe",
            "label": pipe["display_name"],
            "metadata": {
                "pipe_id": pipe_id,
                "fabric_plane": fabric_plane,
                "source_system": source_system,
                "modality": pipe["modality"],
                "transport_kind": pipe["transport_kind"],
                "entity_scope": entity_scope,
                "trust_labels": trust_labels,
                "version": pipe["version"]
            }
        })

        # Add edge: pipe -> fabric_plane
        edges.append({
            "id": f"edge:pipe_plane:{pipe_id}",
            "source": f"pipe:{pipe_id}",
            "target": f"plane:{fabric_plane}",
            "type": "pipe_in_plane",
            "metadata": {}
        })

        # Add edge: pipe -> source_system
        edges.append({
            "id": f"edge:pipe_source:{pipe_id}",
            "source": f"pipe:{pipe_id}",
            "target": f"source:{source_system}",
            "type": "pipe_from_source",
            "metadata": {}
        })

    # Add fabric plane nodes
    plane_colors = {
        "IPAAS": "#22d3ee",
        "API_GATEWAY": "#a78bfa",
        "EVENT_BUS": "#f97316",
        "DATA_WAREHOUSE": "#10b981"
    }
    for plane in fabric_planes:
        nodes.append({
            "id": f"plane:{plane}",
            "type": "fabric_plane",
            "label": plane.replace("_", " ").title(),
            "metadata": {
                "plane_type": plane,
                "color": plane_colors.get(plane, "#64748b")
            }
        })

    # Add source system nodes
    for source in source_systems:
        nodes.append({
            "id": f"source:{source}",
            "type": "source_system",
            "label": source,
            "metadata": {
                "source_system": source
            }
        })

    # Get all candidates
    cursor.execute("""
        SELECT candidate_id, display_name, vendor_name, category, status,
               matched_pipe_id, match_score
        FROM connection_candidates
    """)
    candidates = cursor.fetchall()

    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        vendor_name = candidate["vendor_name"]

        # Ensure vendor is in source_systems for edge consistency
        if vendor_name not in source_systems:
            source_systems.add(vendor_name)
            nodes.append({
                "id": f"source:{vendor_name}",
                "type": "source_system",
                "label": vendor_name,
                "metadata": {
                    "source_system": vendor_name
                }
            })

        # Add candidate node
        nodes.append({
            "id": f"candidate:{candidate_id}",
            "type": "candidate",
            "label": candidate["display_name"],
            "metadata": {
                "candidate_id": candidate_id,
                "vendor_name": vendor_name,
                "category": candidate["category"],
                "status": candidate["status"],
                "matched_pipe_id": candidate["matched_pipe_id"],
                "match_score": candidate["match_score"]
            }
        })

        # Add edge: candidate -> source_system
        edges.append({
            "id": f"edge:candidate_source:{candidate_id}",
            "source": f"candidate:{candidate_id}",
            "target": f"source:{vendor_name}",
            "type": "candidate_for_source",
            "metadata": {
                "category": candidate["category"]
            }
        })

        # Add edge: candidate -> pipe (if matched)
        if candidate["matched_pipe_id"]:
            edges.append({
                "id": f"edge:candidate_pipe:{candidate_id}",
                "source": f"candidate:{candidate_id}",
                "target": f"pipe:{candidate['matched_pipe_id']}",
                "type": "candidate_to_pipe",
                "metadata": {
                    "match_score": candidate["match_score"]
                }
            })

    # Get drift statistics
    cursor.execute("""
        SELECT DISTINCT pipe_id FROM drift_events WHERE status = 'open'
    """)
    pipes_with_open_drift = set(row[0] for row in cursor.fetchall())

    # Get candidate statistics
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN matched_pipe_id IS NOT NULL THEN 1 ELSE 0 END) as connected
        FROM connection_candidates
    """)
    candidate_stats = cursor.fetchone()
    total_candidates = candidate_stats[0] or 0
    connected_candidates = candidate_stats[1] or 0

    conn.close()

    # Compute stats
    nodes_by_type = {}
    for node in nodes:
        node_type = node["type"]
        nodes_by_type[node_type] = nodes_by_type.get(node_type, 0) + 1

    edges_by_type = {}
    for edge in edges:
        edge_type = edge["type"]
        edges_by_type[edge_type] = edges_by_type.get(edge_type, 0) + 1

    stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes_by_type": nodes_by_type,
        "edges_by_type": edges_by_type,
        "fabric_planes": sorted(list(fabric_planes)),
        "source_systems": sorted(list(source_systems)),
        "connected_candidates": connected_candidates,
        "unconnected_candidates": total_candidates - connected_candidates,
        "pipes_with_drift": len(pipes_with_open_drift)
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": stats
    }


def get_topology_for_pipe(pipe_id: str) -> dict:
    """Get topology centered on a specific pipe"""
    conn = get_connection()
    cursor = conn.cursor()

    nodes = []
    edges = []

    # Get the pipe
    cursor.execute("""
        SELECT pipe_id, display_name, fabric_plane, source_system, modality,
               transport_kind, entity_scope, trust_labels, version
        FROM declared_pipes WHERE pipe_id = ?
    """, (pipe_id,))
    pipe = cursor.fetchone()

    if not pipe:
        conn.close()
        return {"nodes": [], "edges": [], "stats": {}}

    fabric_plane = pipe["fabric_plane"] or "API_GATEWAY"
    source_system = pipe["source_system"]
    entity_scope = json.loads(pipe["entity_scope"]) if pipe["entity_scope"] else []
    trust_labels = json.loads(pipe["trust_labels"]) if pipe["trust_labels"] else []

    # Add pipe node (central)
    nodes.append({
        "id": f"pipe:{pipe_id}",
        "type": "pipe",
        "label": pipe["display_name"],
        "metadata": {
            "pipe_id": pipe_id,
            "fabric_plane": fabric_plane,
            "source_system": source_system,
            "modality": pipe["modality"],
            "transport_kind": pipe["transport_kind"],
            "entity_scope": entity_scope,
            "trust_labels": trust_labels,
            "version": pipe["version"],
            "central": True
        }
    })

    # Add fabric plane node
    plane_colors = {
        "IPAAS": "#22d3ee",
        "API_GATEWAY": "#a78bfa",
        "EVENT_BUS": "#f97316",
        "DATA_WAREHOUSE": "#10b981"
    }
    nodes.append({
        "id": f"plane:{fabric_plane}",
        "type": "fabric_plane",
        "label": fabric_plane.replace("_", " ").title(),
        "metadata": {
            "plane_type": fabric_plane,
            "color": plane_colors.get(fabric_plane, "#64748b")
        }
    })

    # Add source system node
    nodes.append({
        "id": f"source:{source_system}",
        "type": "source_system",
        "label": source_system,
        "metadata": {"source_system": source_system}
    })

    # Add edges
    edges.append({
        "id": f"edge:pipe_plane:{pipe_id}",
        "source": f"pipe:{pipe_id}",
        "target": f"plane:{fabric_plane}",
        "type": "pipe_in_plane",
        "metadata": {}
    })
    edges.append({
        "id": f"edge:pipe_source:{pipe_id}",
        "source": f"pipe:{pipe_id}",
        "target": f"source:{source_system}",
        "type": "pipe_from_source",
        "metadata": {}
    })

    # Get related candidates
    cursor.execute("""
        SELECT candidate_id, display_name, vendor_name, category, status, match_score
        FROM connection_candidates WHERE matched_pipe_id = ?
    """, (pipe_id,))
    candidates = cursor.fetchall()

    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        nodes.append({
            "id": f"candidate:{candidate_id}",
            "type": "candidate",
            "label": candidate["display_name"],
            "metadata": {
                "candidate_id": candidate_id,
                "vendor_name": candidate["vendor_name"],
                "category": candidate["category"],
                "status": candidate["status"],
                "match_score": candidate["match_score"]
            }
        })
        edges.append({
            "id": f"edge:candidate_pipe:{candidate_id}",
            "source": f"candidate:{candidate_id}",
            "target": f"pipe:{pipe_id}",
            "type": "candidate_to_pipe",
            "metadata": {"match_score": candidate["match_score"]}
        })

    # Get drift events
    cursor.execute("""
        SELECT drift_id, drift_type, severity, status, detected_at
        FROM drift_events WHERE pipe_id = ? AND status = 'open'
    """, (pipe_id,))
    drift_events = cursor.fetchall()

    conn.close()

    stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "connected_candidates": len(candidates),
        "open_drift_events": len(drift_events)
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": stats,
        "drift_events": [{
            "drift_id": d["drift_id"],
            "drift_type": d["drift_type"],
            "severity": d["severity"],
            "status": d["status"],
            "detected_at": d["detected_at"]
        } for d in drift_events]
    }


def get_topology_for_fabric_plane(fabric_plane: str) -> dict:
    """Get topology for a specific fabric plane"""
    conn = get_connection()
    cursor = conn.cursor()

    nodes = []
    edges = []

    # Add fabric plane node
    plane_colors = {
        "IPAAS": "#22d3ee",
        "API_GATEWAY": "#a78bfa",
        "EVENT_BUS": "#f97316",
        "DATA_WAREHOUSE": "#10b981"
    }
    nodes.append({
        "id": f"plane:{fabric_plane}",
        "type": "fabric_plane",
        "label": fabric_plane.replace("_", " ").title(),
        "metadata": {
            "plane_type": fabric_plane,
            "color": plane_colors.get(fabric_plane, "#64748b"),
            "central": True
        }
    })

    # Get all pipes in this plane
    cursor.execute("""
        SELECT pipe_id, display_name, source_system, modality,
               transport_kind, entity_scope, trust_labels, version
        FROM declared_pipes WHERE fabric_plane = ?
    """, (fabric_plane,))
    pipes = cursor.fetchall()

    source_systems = set()

    for pipe in pipes:
        pipe_id = pipe["pipe_id"]
        source_system = pipe["source_system"]
        source_systems.add(source_system)

        entity_scope = json.loads(pipe["entity_scope"]) if pipe["entity_scope"] else []
        trust_labels = json.loads(pipe["trust_labels"]) if pipe["trust_labels"] else []

        nodes.append({
            "id": f"pipe:{pipe_id}",
            "type": "pipe",
            "label": pipe["display_name"],
            "metadata": {
                "pipe_id": pipe_id,
                "fabric_plane": fabric_plane,
                "source_system": source_system,
                "modality": pipe["modality"],
                "transport_kind": pipe["transport_kind"],
                "entity_scope": entity_scope,
                "trust_labels": trust_labels,
                "version": pipe["version"]
            }
        })

        edges.append({
            "id": f"edge:pipe_plane:{pipe_id}",
            "source": f"pipe:{pipe_id}",
            "target": f"plane:{fabric_plane}",
            "type": "pipe_in_plane",
            "metadata": {}
        })

        edges.append({
            "id": f"edge:pipe_source:{pipe_id}",
            "source": f"pipe:{pipe_id}",
            "target": f"source:{source_system}",
            "type": "pipe_from_source",
            "metadata": {}
        })

    # Add source system nodes
    for source in source_systems:
        nodes.append({
            "id": f"source:{source}",
            "type": "source_system",
            "label": source,
            "metadata": {"source_system": source}
        })

    conn.close()

    stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "total_pipes": len(pipes),
        "source_systems": sorted(list(source_systems))
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": stats
    }


# ============================================================================
# AOD HANDOFF OPERATIONS
# ============================================================================

def create_handoff_log(handoff_data: dict) -> dict:
    """Create a log entry for an AOD handoff"""
    conn = get_connection()
    cursor = conn.cursor()

    handoff_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    cursor.execute("""
        INSERT INTO aod_handoff_log (
            handoff_id, aod_run_id, candidates_received, candidates_accepted,
            candidates_rejected, rejected_reasons, policy_version,
            handoff_timestamp, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        handoff_id,
        handoff_data["aod_run_id"],
        handoff_data["candidates_received"],
        handoff_data["candidates_accepted"],
        handoff_data["candidates_rejected"],
        json.dumps(handoff_data.get("rejected_reasons", [])),
        handoff_data.get("policy_version"),
        handoff_data.get("handoff_timestamp", now),
        now
    ))

    conn.commit()
    conn.close()

    return {
        "handoff_id": handoff_id,
        "aod_run_id": handoff_data["aod_run_id"],
        "processed_at": now
    }


def get_handoff_log(handoff_id: str) -> Optional[dict]:
    """Get a handoff log entry by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM aod_handoff_log WHERE handoff_id = ?", (handoff_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "handoff_id": row["handoff_id"],
            "aod_run_id": row["aod_run_id"],
            "candidates_received": row["candidates_received"],
            "candidates_accepted": row["candidates_accepted"],
            "candidates_rejected": row["candidates_rejected"],
            "rejected_reasons": json.loads(row["rejected_reasons"]) if row["rejected_reasons"] else [],
            "policy_version": row["policy_version"],
            "handoff_timestamp": row["handoff_timestamp"],
            "processed_at": row["processed_at"]
        }
    return None


def list_handoff_logs(aod_run_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List handoff logs with optional run_id filter"""
    conn = get_connection()
    cursor = conn.cursor()

    if aod_run_id:
        cursor.execute(
            "SELECT * FROM aod_handoff_log WHERE aod_run_id = ? ORDER BY processed_at DESC LIMIT ?",
            (aod_run_id, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM aod_handoff_log ORDER BY processed_at DESC LIMIT ?",
            (limit,)
        )

    rows = cursor.fetchall()
    conn.close()

    return [{
        "handoff_id": row["handoff_id"],
        "aod_run_id": row["aod_run_id"],
        "candidates_received": row["candidates_received"],
        "candidates_accepted": row["candidates_accepted"],
        "candidates_rejected": row["candidates_rejected"],
        "policy_version": row["policy_version"],
        "handoff_timestamp": row["handoff_timestamp"],
        "processed_at": row["processed_at"]
    } for row in rows]


# ============================================================================
# AOD POLICY MANIFEST OPERATIONS
# ============================================================================

def save_policy_manifest(policy_data: dict) -> dict:
    """Save or update the AOD policy manifest"""
    conn = get_connection()
    cursor = conn.cursor()

    policy_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # Deactivate any existing active policies
    cursor.execute("UPDATE aod_policy_manifest SET is_active = 0 WHERE is_active = 1")

    cursor.execute("""
        INSERT INTO aod_policy_manifest (
            policy_id, policy_version, governance_rules, blocking_finding_types,
            fabric_plane_routing, auto_provision_categories, require_human_review,
            is_active, received_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        policy_id,
        policy_data["policy_version"],
        json.dumps(policy_data.get("governance_rules", [])),
        json.dumps(policy_data.get("blocking_finding_types", [])),
        json.dumps(policy_data.get("fabric_plane_routing", {})),
        json.dumps(policy_data.get("auto_provision_categories", [])),
        json.dumps(policy_data.get("require_human_review", [])),
        1,  # is_active = True
        now,
        now
    ))

    conn.commit()
    conn.close()

    return {
        "policy_id": policy_id,
        "policy_version": policy_data["policy_version"],
        "is_active": True,
        "received_at": now
    }


def get_active_policy_manifest() -> Optional[dict]:
    """Get the currently active AOD policy manifest"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM aod_policy_manifest WHERE is_active = 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "policy_id": row["policy_id"],
            "policy_version": row["policy_version"],
            "governance_rules": json.loads(row["governance_rules"]) if row["governance_rules"] else [],
            "blocking_finding_types": json.loads(row["blocking_finding_types"]) if row["blocking_finding_types"] else [],
            "fabric_plane_routing": json.loads(row["fabric_plane_routing"]) if row["fabric_plane_routing"] else {},
            "auto_provision_categories": json.loads(row["auto_provision_categories"]) if row["auto_provision_categories"] else [],
            "require_human_review": json.loads(row["require_human_review"]) if row["require_human_review"] else [],
            "is_active": True,
            "received_at": row["received_at"],
            "updated_at": row["updated_at"]
        }
    return None


def list_policy_manifests(limit: int = 20) -> list[dict]:
    """List all policy manifests (history)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM aod_policy_manifest ORDER BY received_at DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()

    return [{
        "policy_id": row["policy_id"],
        "policy_version": row["policy_version"],
        "is_active": bool(row["is_active"]),
        "received_at": row["received_at"],
        "updated_at": row["updated_at"]
    } for row in rows]


def get_candidates_by_aod_run(aod_run_id: str) -> list[dict]:
    """Get all candidates from a specific AOD run"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM connection_candidates WHERE aod_run_id = ? ORDER BY created_at DESC",
        (aod_run_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    return [_row_to_candidate(row) for row in rows]
