-- AAM Supabase Schema
-- All tables for Adaptive API Mesh

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
    execution_allowed BOOLEAN DEFAULT TRUE,
    action_type TEXT DEFAULT 'provision',
    blocking_findings TEXT,
    connected_via_plane TEXT,
    aod_run_id TEXT,
    aod_asset_id TEXT,
    fabric_plane_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fabric_planes (
    plane_id TEXT PRIMARY KEY,
    plane_type TEXT NOT NULL,
    vendor TEXT NOT NULL,
    display_name TEXT,
    domain TEXT,
    managed_asset_count INTEGER DEFAULT 0,
    is_healthy BOOLEAN DEFAULT TRUE,
    aod_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS declared_pipes (
    pipe_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    fabric_plane TEXT,
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
    updated_at TEXT NOT NULL,
    drift_status TEXT DEFAULT 'NONE'
);

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
    processed_at TEXT NOT NULL,
    aod_fabric_planes TEXT,
    aod_sor_vendors TEXT
);

CREATE TABLE IF NOT EXISTS aod_payload_cache (
    id INTEGER PRIMARY KEY,
    payload TEXT NOT NULL,
    cached_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aod_policy_manifest (
    policy_id TEXT PRIMARY KEY,
    policy_version TEXT NOT NULL,
    governance_rules TEXT,
    blocking_finding_types TEXT,
    fabric_plane_routing TEXT,
    auto_provision_categories TEXT,
    require_human_review TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    received_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collectors (
    collector_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    collector_type TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    config TEXT,
    last_run TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collector_runs (
    run_id TEXT PRIMARY KEY,
    collector_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    observations_count INTEGER DEFAULT 0,
    error_message TEXT
);

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
    processed BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS drift_events (
    drift_id TEXT PRIMARY KEY,
    pipe_id TEXT NOT NULL,
    drift_type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    details TEXT,
    detected_at TEXT NOT NULL,
    severity TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'open',
    acknowledged_at TEXT,
    acknowledged_by TEXT,
    suppressed_at TEXT,
    suppressed_by TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS pipe_versions (
    version_id TEXT PRIMARY KEY,
    pipe_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    schema_hash TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

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
);

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
);

CREATE TABLE IF NOT EXISTS tee_requests (
    tee_id TEXT PRIMARY KEY,
    pipe_id TEXT NOT NULL,
    target_system TEXT NOT NULL,
    tee_type TEXT NOT NULL,
    configuration TEXT,
    status TEXT DEFAULT 'requested',
    requested_at TEXT NOT NULL,
    approved_at TEXT,
    verified_at TEXT
);

CREATE TABLE IF NOT EXISTS dcl_pushes (
    push_id TEXT PRIMARY KEY,
    aod_run_id TEXT,
    pushed_at TEXT NOT NULL,
    pipe_count INTEGER NOT NULL DEFAULT 0,
    payload_hash TEXT,
    payload TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS runner_jobs (
    job_id TEXT PRIMARY KEY,
    pipe_id TEXT NOT NULL,
    status TEXT DEFAULT 'queued',
    manifest TEXT,
    dispatched_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    last_heartbeat TEXT,
    rows_transferred INTEGER DEFAULT 0,
    error_message TEXT,
    dcl_response TEXT,
    retry_count INTEGER DEFAULT 0,
    retry_after TEXT
);

CREATE TABLE IF NOT EXISTS semantic_edges (
    id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,
    source_object TEXT NOT NULL,
    source_field TEXT NOT NULL,
    target_system TEXT NOT NULL,
    target_object TEXT NOT NULL,
    target_field TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    fabric_plane TEXT NOT NULL,
    extraction_source TEXT NOT NULL,
    transformation TEXT,
    condition TEXT,
    discovered_at TEXT NOT NULL,
    last_verified TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dcl_ingested (
    ingest_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    pipe_id TEXT NOT NULL,
    source_system TEXT,
    row_count INTEGER DEFAULT 0,
    payload_hash TEXT,
    schema_hash TEXT,
    payload TEXT,
    ingested_at TEXT,
    schema_version TEXT
);
