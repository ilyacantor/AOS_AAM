"""
Schema initialization and migrations.
"""
import json
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection, _add_column_if_not_exists, _log

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

    # Fabric Planes (from AOD)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fabric_planes (
            plane_id TEXT PRIMARY KEY,
            plane_type TEXT NOT NULL,
            vendor TEXT NOT NULL,
            display_name TEXT,
            domain TEXT,
            managed_asset_count INTEGER DEFAULT 0,
            is_healthy INTEGER DEFAULT 1,
            aod_run_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # AOD Handoff Log (track batch handoffs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aod_handoff_log (
            handoff_id TEXT PRIMARY KEY,
            aod_run_id TEXT NOT NULL,
            snapshot_name TEXT,
            candidates_received INTEGER NOT NULL,
            candidates_accepted INTEGER NOT NULL,
            candidates_rejected INTEGER NOT NULL,
            rejected_reasons TEXT,
            policy_version TEXT,
            handoff_timestamp TEXT NOT NULL,
            processed_at TEXT NOT NULL
        )
    """)
    
    # SOR Declarations (authoritative SOR list from Farm via AOD)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sor_declarations (
            sor_id TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            vendor TEXT NOT NULL,
            category TEXT,
            confidence TEXT DEFAULT 'high',
            source TEXT DEFAULT 'farm',
            aod_run_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # SOR Dispositions (operator actions on SOR reconciliation line items)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sor_dispositions (
            disposition_id TEXT PRIMARY KEY,
            sor_vendor TEXT NOT NULL,
            aod_run_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            reason TEXT,
            operator_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(sor_vendor, aod_run_id)
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
    
    # Add fabric_plane_id to connection_candidates (link to fabric_planes table)
    _add_column_if_not_exists(cursor, "connection_candidates", "fabric_plane_id", "TEXT")
    
    # Store AOD-provided fabric planes and SOR metadata in handoff log for reconciliation
    _add_column_if_not_exists(cursor, "aod_handoff_log", "aod_fabric_planes", "TEXT")
    _add_column_if_not_exists(cursor, "aod_handoff_log", "aod_sor_vendors", "TEXT")
    
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
    
    # Migrations - add new columns to existing tables
    _add_column_if_not_exists(cursor, "aod_handoff_log", "snapshot_name", "TEXT")
    _add_column_if_not_exists(cursor, "declared_pipes", "drift_status", "TEXT DEFAULT 'NONE'")
    
    conn.commit()
    conn.close()
    _log.info("Database initialized")


