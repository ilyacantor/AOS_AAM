"""Smoke tests — verify database initialisation works."""


def test_init_db_creates_all_tables(db):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = sorted(row[0] for row in cursor.fetchall())
    conn.close()

    expected = sorted([
        "aod_handoff_log",
        "aod_policy_manifest",
        "collector_runs",
        "collectors",
        "connection_candidates",
        "declared_pipes",
        "drift_events",
        "fabric_planes",
        "observations",
        "pipe_versions",
        "tee_requests",
    ])
    assert tables == expected


def test_create_and_get_candidate(db):
    result = db.create_candidate({
        "asset_key": "test.com",
        "vendor_name": "testvendor",
        "display_name": "Test Vendor",
        "category": "crm",
    })
    assert result["candidate_id"]
    assert result["status"] == "connected"

    fetched = db.get_candidate(result["candidate_id"])
    assert fetched is not None
    assert fetched["asset_key"] == "test.com"


def test_candidate_dedup_by_asset_key(db):
    db.create_candidate({
        "asset_key": "dup.com",
        "vendor_name": "v1",
        "display_name": "V1",
        "category": "erp",
    })
    db.create_candidate({
        "asset_key": "dup.com",
        "vendor_name": "v2",
        "display_name": "V2",
        "category": "erp",
    })
    candidates = db.list_candidates()
    matches = [c for c in candidates if c["asset_key"] == "dup.com"]
    assert len(matches) == 1
    assert matches[0]["vendor_name"] == "v2"


def test_create_pipe_and_get(db):
    """create_pipe writes to declared_pipes; list_pipes reads connection_candidates (canonical model)."""
    pipe = db.create_pipe({
        "display_name": "Test Pipe",
        "fabric_plane": "API_GATEWAY",
        "modality": "DECLARED_INTERFACE",
        "source_system": "test",
        "transport_kind": "API",
        "provenance": {"discovered_by": "test", "discovered_at": "2025-01-01"},
    })
    assert pipe["pipe_id"]

    fetched = db.get_pipe(pipe["pipe_id"])
    assert fetched is not None
    assert fetched["display_name"] == "Test Pipe"


def test_list_pipes_returns_candidates_as_pipes(db):
    """list_pipes() reads from connection_candidates (pipes = candidates)."""
    db.create_candidate({
        "asset_key": "salesforce.com",
        "vendor_name": "salesforce",
        "display_name": "Salesforce",
        "category": "crm",
    })
    pipes = db.list_pipes()
    assert len(pipes) == 1
    assert pipes[0]["source_system"] == "salesforce"
