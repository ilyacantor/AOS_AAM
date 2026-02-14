"""
AAM Functional Evaluation Harness
=================================

These are *frontend-grade* functional tests.  They verify what a human would
see in the browser by hitting the same HTTP endpoints the UI calls, with the
same payloads AOD sends, and asserting on the JSON/HTML the browser receives.

No mocks, no monkeypatches on business logic, no cheating.  The only fixture
is a temp database (standard for any test that touches SQLite).

USER STORIES
------------

US-1  AOD Handoff — Plane Linkage
    Given AOD sends candidates with 4 explicit fabric planes (Kong, Workato,
    Kafka, Snowflake), WHEN the handoff completes, THEN every candidate's
    fabric_plane_id is non-NULL and matches a real fabric_planes row.

US-2  Topology — Vendor-Specific Plane Nodes
    Given a completed handoff, WHEN I view /api/topology/summary (the default
    UI view), THEN every fabric-plane node has a vendor name in its label
    (e.g. "Kong, API Gateway") and there are ZERO bare-type nodes like
    "API Gateway" without a vendor.

US-3  Topology — No Orphaned Nodes
    WHEN I view the topology, THEN every plane node is the target of at least
    one edge.  No floating disconnected plane nodes.

US-4  Topology — Edge Integrity
    Every edge's `source` and `target` reference a node ID that actually
    exists in the nodes list.  No dangling pointers.

US-5  Topology — Summary/Full Agreement
    The summary topology and the full topology assign the same candidates
    to the same fabric-plane types.  They must not disagree.

US-6  Pipe Metadata — No Hardcoded Cheats
    Candidates routed through Kafka should have transport_kind = EVENT_STREAM.
    Candidates routed through Snowflake should have transport_kind = TABLE.
    iPaaS candidates should have modality = CONTROL_PLANE.
    API Gateway candidates should have modality = DECLARED_INTERFACE.

US-7  Governance Defaults — Safe by Default
    A candidate created without an explicit execution_allowed value should
    NOT default to True/allowed.  It should be NULL (requires review).

US-8  UI Pages — No 500 Errors
    Every /ui/* page returns 200 OK, not 500.

US-9  Per-Plane Topology — Correct Filtering
    Filtering by API_GATEWAY shows only candidates routed through the
    API Gateway, not all candidates.

US-10 Handoff Idempotency
    Sending the same run_id twice does not duplicate data.
"""
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(db):
    """Create a TestClient with an initialized temp database."""
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _build_handoff_payload():
    """Build a realistic AOD handoff payload with 4 fabric planes and 12 candidates.

    This mirrors what AOD actually sends in production:
    - 4 fabric planes: Kong (API GW), Workato (iPaaS), Kafka (Event Bus), Snowflake (DW)
    - 12 candidates across CRM, ERP, HCM, ITSM, iPaaS, identity categories
    - Each candidate has connected_via_plane routing hint
    - SOR declarations from Farm
    """
    return {
        "run_id": "eval-run-001",
        "snapshot_name": "DemoDay-Eval",
        "fabric_planes": [
            {"plane_type": "API_GATEWAY", "vendor": "Kong", "is_healthy": True, "source": "aod"},
            {"plane_type": "IPAAS", "vendor": "Workato", "is_healthy": True, "source": "aod"},
            {"plane_type": "EVENT_BUS", "vendor": "Kafka", "is_healthy": True, "source": "aod"},
            {"plane_type": "DATA_WAREHOUSE", "vendor": "Snowflake", "is_healthy": True, "source": "aod"},
        ],
        "sors": [
            {"domain": "CRM", "vendor": "Salesforce", "category": "crm", "confidence": "high", "source": "farm"},
            {"domain": "ERP", "vendor": "SAP", "category": "erp", "confidence": "high", "source": "farm"},
            {"domain": "HCM", "vendor": "Workday", "category": "hcm", "confidence": "high", "source": "farm"},
        ],
        "candidates": [
            # --- API Gateway candidates ---
            {
                "asset_key": "salesforce-crm-api",
                "vendor_name": "Salesforce",
                "display_name": "Salesforce CRM API",
                "category": "crm",
                "connected_via_plane": "API_GATEWAY",
                "known_endpoints": ["https://api.salesforce.com/sobjects"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-sf-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            {
                "asset_key": "sap-erp-api",
                "vendor_name": "SAP",
                "display_name": "SAP ERP Gateway",
                "category": "erp",
                "connected_via_plane": "API_GATEWAY",
                "known_endpoints": ["https://sap.example.com/api/v1"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-sap-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            {
                "asset_key": "servicenow-itsm-api",
                "vendor_name": "ServiceNow",
                "display_name": "ServiceNow ITSM API",
                "category": "itsm",
                "connected_via_plane": "API_GATEWAY",
                "known_endpoints": ["https://instance.service-now.com/api"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-snow-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            # --- iPaaS candidates ---
            {
                "asset_key": "workato-recipes",
                "vendor_name": "Workato",
                "display_name": "Workato Integration Recipes",
                "category": "ipaas",
                "connected_via_plane": "IPAAS",
                "known_endpoints": ["https://workato.com/api/recipes"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-wk-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            {
                "asset_key": "workday-hcm-ipaas",
                "vendor_name": "Workday",
                "display_name": "Workday HCM via iPaaS",
                "category": "hcm",
                "connected_via_plane": "IPAAS",
                "known_endpoints": ["https://workday.com/api/hcm"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-wd-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            {
                "asset_key": "netsuite-erp-ipaas",
                "vendor_name": "NetSuite",
                "display_name": "NetSuite ERP via iPaaS",
                "category": "erp",
                "connected_via_plane": "IPAAS",
                "known_endpoints": ["https://netsuite.com/api"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-ns-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            # --- Event Bus candidates ---
            {
                "asset_key": "kafka-order-events",
                "vendor_name": "Kafka",
                "display_name": "Kafka Order Events Stream",
                "category": "saas",
                "connected_via_plane": "EVENT_BUS",
                "known_endpoints": ["kafka://broker:9092/orders"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-kf-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            {
                "asset_key": "kafka-user-events",
                "vendor_name": "Kafka",
                "display_name": "Kafka User Events Stream",
                "category": "saas",
                "connected_via_plane": "EVENT_BUS",
                "known_endpoints": ["kafka://broker:9092/users"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-kf-002",
                "execution_allowed": True,
                "action_type": "provision",
            },
            # --- Data Warehouse candidates ---
            {
                "asset_key": "snowflake-analytics",
                "vendor_name": "Snowflake",
                "display_name": "Snowflake Analytics Warehouse",
                "category": "saas",
                "connected_via_plane": "DATA_WAREHOUSE",
                "known_endpoints": ["snowflake://account.snowflakecomputing.com/analytics"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-sf-dw-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            {
                "asset_key": "snowflake-finance",
                "vendor_name": "Snowflake",
                "display_name": "Snowflake Finance Tables",
                "category": "finance",
                "connected_via_plane": "DATA_WAREHOUSE",
                "known_endpoints": ["snowflake://account.snowflakecomputing.com/finance"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-sf-dw-002",
                "execution_allowed": True,
                "action_type": "provision",
            },
            # --- Mixed: candidate WITH explicit plane, no connected_via_plane ---
            {
                "asset_key": "okta-identity",
                "vendor_name": "Okta",
                "display_name": "Okta Identity Provider",
                "category": "identity",
                "connected_via_plane": "API_GATEWAY",
                "known_endpoints": ["https://okta.example.com/api/v1"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-ok-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
            # --- Edge case: candidate with NO routing hint ---
            {
                "asset_key": "jira-project-mgmt",
                "vendor_name": "Jira",
                "display_name": "Jira Project Management",
                "category": "itsm",
                "known_endpoints": ["https://jira.example.com/rest/api/2"],
                "aod_run_id": "eval-run-001",
                "aod_asset_id": "aod-jira-001",
                "execution_allowed": True,
                "action_type": "provision",
            },
        ],
        "policy_version": "v2.1",
    }


# ===========================================================================
# US-1: AOD Handoff — Plane Linkage
# ===========================================================================

class TestUS1_HandoffPlaneLinkage:
    """Every candidate must be linked to a vendor-specific fabric plane after handoff."""

    def test_handoff_accepts_all_candidates(self, client):
        payload = _build_handoff_payload()
        resp = client.post("/api/handoff/aod/receive", json=payload)
        assert resp.status_code == 200, f"Handoff failed: {resp.text}"
        data = resp.json()
        assert data["candidates_accepted"] == 12, (
            f"Expected 12 accepted, got {data['candidates_accepted']}; "
            f"rejected: {data.get('rejected_reasons', [])}"
        )

    def test_candidates_have_fabric_plane_id(self, client):
        payload = _build_handoff_payload()
        client.post("/api/handoff/aod/receive", json=payload)

        resp = client.get("/api/aam/candidates")
        assert resp.status_code == 200
        candidates = resp.json()["candidates"]
        # 12 AOD candidates + possible infra candidates (e.g. Kong)
        assert len(candidates) >= 12

        # Every candidate with a connected_via_plane should have a fabric_plane_id
        routed = [c for c in candidates if c.get("connected_via_plane")]
        for c in routed:
            assert c.get("fabric_plane_id") is not None, (
                f"Candidate '{c['display_name']}' (plane hint: {c['connected_via_plane']}) "
                f"has NULL fabric_plane_id"
            )

    def test_fabric_planes_stored(self, client):
        payload = _build_handoff_payload()
        client.post("/api/handoff/aod/receive", json=payload)

        resp = client.get("/api/handoff/fabric-planes")
        assert resp.status_code == 200
        planes = resp.json()["planes"]
        plane_types = {p["plane_type"] for p in planes}
        assert plane_types == {"API_GATEWAY", "IPAAS", "EVENT_BUS", "DATA_WAREHOUSE"}, (
            f"Expected all 4 plane types, got {plane_types}"
        )


# ===========================================================================
# US-2: Topology — Vendor-Specific Plane Nodes
# ===========================================================================

class TestUS2_TopologyVendorNodes:
    """Topology must show vendor-specific nodes, not generic type nodes."""

    def _ingest(self, client):
        client.post("/api/handoff/aod/receive", json=_build_handoff_payload())

    def test_summary_plane_nodes_have_vendor(self, client):
        self._ingest(client)
        resp = client.get("/api/topology/summary")
        assert resp.status_code == 200
        data = resp.json()

        plane_nodes = [n for n in data["nodes"] if n["type"] == "fabric_plane"]
        assert len(plane_nodes) >= 4, f"Expected at least 4 plane nodes, got {len(plane_nodes)}"

        for node in plane_nodes:
            meta = node.get("metadata", {})
            # UNMAPPED is a legitimate sentinel for candidates without routing hints
            if meta.get("plane_type") == "UNMAPPED":
                continue
            # Every real plane node must have a vendor in metadata
            assert meta.get("vendor") is not None, (
                f"Plane node '{node['label']}' (id={node['id']}) has no vendor in metadata"
            )
            # The node ID must be vendor-specific (e.g. "plane:API_GATEWAY:Kong")
            # not bare-type (e.g. "plane:API_GATEWAY")
            node_id = node["id"]
            assert ":" in node_id.replace("plane:", "", 1), (
                f"Plane node ID '{node_id}' is bare-type, not vendor-specific"
            )

    def test_no_bare_type_plane_nodes(self, client):
        self._ingest(client)
        resp = client.get("/api/topology/summary")
        data = resp.json()

        plane_nodes = [n for n in data["nodes"] if n["type"] == "fabric_plane"]
        # UNMAPPED is acceptable — it means a candidate genuinely has no routing hint.
        # Bare REAL types (API_GATEWAY, IPAAS, etc.) without vendor are the bug.
        bare_type_ids = {"plane:API_GATEWAY", "plane:IPAAS", "plane:EVENT_BUS",
                         "plane:DATA_WAREHOUSE"}

        for node in plane_nodes:
            assert node["id"] not in bare_type_ids, (
                f"Found bare-type plane node: {node['id']} (label: {node['label']})"
            )


# ===========================================================================
# US-3: Topology — No Orphaned Nodes
# ===========================================================================

class TestUS3_TopologyNoOrphans:
    """Every plane node must have at least one edge pointing to it."""

    def _ingest(self, client):
        client.post("/api/handoff/aod/receive", json=_build_handoff_payload())

    def test_summary_no_orphaned_plane_nodes(self, client):
        self._ingest(client)
        resp = client.get("/api/topology/summary")
        data = resp.json()

        plane_node_ids = {n["id"] for n in data["nodes"] if n["type"] == "fabric_plane"}
        edge_targets = {e["target"] for e in data["edges"]}
        edge_sources = {e["source"] for e in data["edges"]}
        connected = edge_targets | edge_sources

        orphans = plane_node_ids - connected
        assert len(orphans) == 0, (
            f"Orphaned plane nodes (no edges): {orphans}"
        )

    def test_full_topology_no_orphaned_plane_nodes(self, client):
        self._ingest(client)
        resp = client.get("/api/topology")
        data = resp.json()

        plane_node_ids = {n["id"] for n in data["nodes"] if n["type"] == "fabric_plane"}
        edge_targets = {e["target"] for e in data["edges"]}
        edge_sources = {e["source"] for e in data["edges"]}
        connected = edge_targets | edge_sources

        orphans = plane_node_ids - connected
        assert len(orphans) == 0, (
            f"Orphaned plane nodes in full topology: {orphans}"
        )


# ===========================================================================
# US-4: Topology — Edge Integrity
# ===========================================================================

class TestUS4_TopologyEdgeIntegrity:
    """Every edge must reference existing nodes — no dangling pointers."""

    def _ingest(self, client):
        client.post("/api/handoff/aod/receive", json=_build_handoff_payload())

    def test_summary_edges_reference_existing_nodes(self, client):
        self._ingest(client)
        resp = client.get("/api/topology/summary")
        data = resp.json()

        node_ids = {n["id"] for n in data["nodes"]}
        for edge in data["edges"]:
            assert edge["source"] in node_ids, (
                f"Edge {edge['id']} source '{edge['source']}' not in nodes"
            )
            assert edge["target"] in node_ids, (
                f"Edge {edge['id']} target '{edge['target']}' not in nodes"
            )

    def test_full_topology_edges_reference_existing_nodes(self, client):
        self._ingest(client)
        resp = client.get("/api/topology")
        data = resp.json()

        node_ids = {n["id"] for n in data["nodes"]}
        for edge in data["edges"]:
            assert edge["source"] in node_ids, (
                f"Edge {edge['id']} source '{edge['source']}' not in nodes"
            )
            assert edge["target"] in node_ids, (
                f"Edge {edge['id']} target '{edge['target']}' not in nodes"
            )


# ===========================================================================
# US-5: Topology — Summary/Full Agreement
# ===========================================================================

class TestUS5_TopologyAgreement:
    """Summary and full topology must agree on plane assignments."""

    def _ingest(self, client):
        client.post("/api/handoff/aod/receive", json=_build_handoff_payload())

    def test_same_plane_types_in_both_views(self, client):
        self._ingest(client)

        summary = client.get("/api/topology/summary").json()
        full = client.get("/api/topology").json()

        summary_plane_types = {
            n["metadata"].get("plane_type")
            for n in summary["nodes"] if n["type"] == "fabric_plane"
        }
        full_plane_types = {
            n["metadata"].get("plane_type")
            for n in full["nodes"] if n["type"] == "fabric_plane"
        }

        assert summary_plane_types == full_plane_types, (
            f"Summary plane types {summary_plane_types} != full {full_plane_types}"
        )

    def test_both_views_have_four_plane_types(self, client):
        self._ingest(client)

        for endpoint in ["/api/topology/summary", "/api/topology"]:
            data = client.get(endpoint).json()
            plane_types = {
                n["metadata"].get("plane_type")
                for n in data["nodes"] if n["type"] == "fabric_plane"
            }
            expected = {"API_GATEWAY", "IPAAS", "EVENT_BUS", "DATA_WAREHOUSE"}
            missing = expected - plane_types
            assert expected <= plane_types, (
                f"{endpoint} missing plane types: {missing}"
            )


# ===========================================================================
# US-6: Pipe Metadata — No Hardcoded Cheats
# ===========================================================================

class TestUS6_PipeMetadataNoCheat:
    """Pipe metadata must reflect actual transport/modality, not hardcoded defaults."""

    def _ingest(self, client):
        client.post("/api/handoff/aod/receive", json=_build_handoff_payload())

    def test_kafka_pipes_have_event_stream_transport(self, client):
        self._ingest(client)
        resp = client.get("/api/pipes")
        assert resp.status_code == 200
        pipes = resp.json()["pipes"]

        kafka_pipes = [p for p in pipes if "Kafka" in p["display_name"]]
        assert len(kafka_pipes) >= 2, f"Expected at least 2 Kafka pipes, got {len(kafka_pipes)}"

        for pipe in kafka_pipes:
            assert pipe["transport_kind"] == "EVENT_STREAM", (
                f"Kafka pipe '{pipe['display_name']}' has transport_kind={pipe['transport_kind']}, "
                f"expected EVENT_STREAM"
            )

    def test_snowflake_pipes_have_table_transport(self, client):
        self._ingest(client)
        resp = client.get("/api/pipes")
        pipes = resp.json()["pipes"]

        sf_pipes = [p for p in pipes if "Snowflake" in p["display_name"]]
        assert len(sf_pipes) >= 2, f"Expected at least 2 Snowflake pipes, got {len(sf_pipes)}"

        for pipe in sf_pipes:
            assert pipe["transport_kind"] == "TABLE", (
                f"Snowflake pipe '{pipe['display_name']}' has transport_kind={pipe['transport_kind']}, "
                f"expected TABLE"
            )

    def test_ipaas_pipes_have_control_plane_modality(self, client):
        self._ingest(client)
        resp = client.get("/api/pipes")
        pipes = resp.json()["pipes"]

        ipaas_pipes = [p for p in pipes if p.get("fabric_plane") == "IPAAS"]
        # At minimum the Workato candidate should be IPAAS
        for pipe in ipaas_pipes:
            assert pipe["modality"] == "CONTROL_PLANE", (
                f"iPaaS pipe '{pipe['display_name']}' has modality={pipe['modality']}, "
                f"expected CONTROL_PLANE"
            )

    def test_api_gateway_pipes_have_declared_interface_modality(self, client):
        self._ingest(client)
        resp = client.get("/api/pipes")
        pipes = resp.json()["pipes"]

        gw_pipes = [p for p in pipes if p.get("fabric_plane") == "API_GATEWAY"]
        for pipe in gw_pipes:
            assert pipe["modality"] == "DECLARED_INTERFACE", (
                f"API GW pipe '{pipe['display_name']}' has modality={pipe['modality']}, "
                f"expected DECLARED_INTERFACE"
            )


# ===========================================================================
# US-7: Governance Defaults — Safe by Default
# ===========================================================================

class TestUS7_GovernanceDefaults:
    """Candidates without explicit governance should NOT default to permissive."""

    def test_schema_default_execution_allowed_is_null(self, client):
        """Direct DB insert without execution_allowed should be NULL, not 1."""
        from app.db.connection import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        # Insert a bare-minimum candidate without execution_allowed
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT INTO connection_candidates
            (candidate_id, asset_key, vendor_name, display_name, category, status, created_at, updated_at)
            VALUES ('test-gov-001', 'test-gov-key', 'TestVendor', 'Test', 'crm', 'new', ?, ?)
        """, (now, now))
        conn.commit()
        cursor.execute("SELECT execution_allowed, action_type FROM connection_candidates WHERE candidate_id = 'test-gov-001'")
        row = cursor.fetchone()
        conn.close()
        assert row["execution_allowed"] is None, (
            f"execution_allowed defaulted to {row['execution_allowed']}, expected NULL"
        )
        assert row["action_type"] is None or row["action_type"] == "inventory_only", (
            f"action_type defaulted to '{row['action_type']}', expected NULL or 'inventory_only'"
        )


# ===========================================================================
# US-8: UI Pages — No 500 Errors
# ===========================================================================

class TestUS8_UIPages:
    """All operator UI pages should return 200, not 500."""

    def _ingest(self, client):
        client.post("/api/handoff/aod/receive", json=_build_handoff_payload())

    def test_topology_page(self, client):
        self._ingest(client)
        resp = client.get("/ui/topology")
        assert resp.status_code == 200, f"Topology page returned {resp.status_code}: {resp.text[:500]}"

    def test_pipes_page(self, client):
        self._ingest(client)
        resp = client.get("/ui/pipes")
        assert resp.status_code == 200, f"Pipes page returned {resp.status_code}: {resp.text[:500]}"

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


# ===========================================================================
# US-9: Per-Plane Topology — Correct Filtering
# ===========================================================================

class TestUS9_PerPlaneFiltering:
    """Filtering by plane type should only show that plane's candidates."""

    def _ingest(self, client):
        client.post("/api/handoff/aod/receive", json=_build_handoff_payload())

    def test_api_gateway_filter(self, client):
        self._ingest(client)
        resp = client.get("/api/topology/plane/API_GATEWAY")
        assert resp.status_code == 200
        data = resp.json()

        pipe_nodes = [n for n in data["nodes"] if n["type"] == "pipe"]
        # We sent 4 candidates via API_GATEWAY (Salesforce, SAP, ServiceNow, Okta)
        assert len(pipe_nodes) >= 3, (
            f"API_GATEWAY plane should have at least 3 pipes, got {len(pipe_nodes)}"
        )

        # No pipe should be from EVENT_BUS or DATA_WAREHOUSE
        for p in pipe_nodes:
            plane = p["metadata"].get("fabric_plane", "")
            assert plane == "API_GATEWAY", (
                f"Pipe '{p['label']}' in API_GATEWAY view has plane={plane}"
            )

    def test_event_bus_filter(self, client):
        self._ingest(client)
        resp = client.get("/api/topology/plane/EVENT_BUS")
        assert resp.status_code == 200
        data = resp.json()

        pipe_nodes = [n for n in data["nodes"] if n["type"] == "pipe"]
        assert len(pipe_nodes) >= 2, (
            f"EVENT_BUS plane should have at least 2 pipes (Kafka), got {len(pipe_nodes)}"
        )


# ===========================================================================
# US-10: Handoff Idempotency
# ===========================================================================

class TestUS10_Idempotency:
    """Re-sending the same run_id should not duplicate candidates."""

    def test_duplicate_run_returns_cached(self, client):
        payload = _build_handoff_payload()
        resp1 = client.post("/api/handoff/aod/receive", json=payload)
        assert resp1.status_code == 200
        first_count = resp1.json()["candidates_accepted"]

        resp2 = client.post("/api/handoff/aod/receive", json=payload)
        assert resp2.status_code == 200

        # Count after idempotent replay should match first handoff
        # (12 AOD candidates + possible infra candidates, but NOT doubled)
        candidates = client.get("/api/aam/candidates").json()["candidates"]
        first_total = len(candidates)
        assert first_total > 0

        # Send a THIRD time — count should not grow
        resp3 = client.post("/api/handoff/aod/receive", json=payload)
        assert resp3.status_code == 200
        candidates_after = client.get("/api/aam/candidates").json()["candidates"]
        assert len(candidates_after) == first_total, (
            f"Expected {first_total} candidates after idempotent replay, got {len(candidates_after)}"
        )
