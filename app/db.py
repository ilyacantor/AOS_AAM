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
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
    
    # Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_status ON connection_candidates(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_asset_key ON connection_candidates(asset_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipes_source ON declared_pipes(source_system)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_observations_collector ON observations(collector_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_drift_pipe ON drift_events(pipe_id)")
    
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
    
    cursor.execute("""
        INSERT INTO connection_candidates (
            candidate_id, asset_key, vendor_name, display_name, category,
            governance_status, findings, sor_tagging, evidence_refs,
            signals_summary, known_endpoints, preferred_modality, priority_score,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        now,
        now
    ))
    
    conn.commit()
    conn.close()
    
    return {"candidate_id": candidate_id, "status": "new", "created_at": now, "updated_at": now}


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
    """List candidates with optional status filter"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if status:
        cursor.execute(
            "SELECT * FROM connection_candidates WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM connection_candidates ORDER BY created_at DESC LIMIT ?",
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
    return {
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
            pipe_id, display_name, modality, source_system, transport_kind,
            endpoint_ref, entity_scope, identity_keys, change_semantics,
            provenance, owner_signals, trust_labels, schema_info, freshness,
            access_info, version, schema_hash, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pipe_id,
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


def list_pipes(source_system: Optional[str] = None, limit: int = 100) -> list[dict]:
    """List pipes with optional source filter"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if source_system:
        cursor.execute(
            "SELECT * FROM declared_pipes WHERE source_system = ? ORDER BY created_at DESC LIMIT ?",
            (source_system, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM declared_pipes ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
    
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
    
    return {
        "pipe_id": row["pipe_id"],
        "display_name": row["display_name"],
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
    
    return [{
        "drift_id": row["drift_id"],
        "pipe_id": row["pipe_id"],
        "drift_type": row["drift_type"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "details": json.loads(row["details"]) if row["details"] else None,
        "detected_at": row["detected_at"]
    } for row in rows]


def list_all_drift_events(limit: int = 100) -> list[dict]:
    """List all drift events"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drift_events ORDER BY detected_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "drift_id": row["drift_id"],
        "pipe_id": row["pipe_id"],
        "drift_type": row["drift_type"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "details": json.loads(row["details"]) if row["details"] else None,
        "detected_at": row["detected_at"]
    } for row in rows]


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
