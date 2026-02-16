"""
Tests for DCL export field resolution.

Validates that the export-pipes endpoint populates fields[] on every
connection using the priority cascade:
  1. Observation schema_sample (by candidate_id)
  2. Observation schema_sample (by source_system ↔ vendor_name)
  3. Declared pipe identity_keys + entity_scope (via matched_pipe_id)
  4. Vendor→plane mapping fields (infrastructure vendors in "other" category)
  5. Category-based standard fields (metadata inference)

These tests are pure unit tests — no database connection required.
"""
import pytest
from app.dcl_export import _resolve_fields, DCLConnectionSchema, DCLExportResponse
from app.constants import (
    CATEGORY_STANDARD_FIELDS,
    PLANE_STANDARD_FIELDS,
    INFRA_VENDOR_PLANE,
    SOR_CATEGORIES,
    ALL_PLANE_TYPES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_maps():
    return {
        "by_candidate_id": {},
        "by_source_system": {},
        "by_pipe_id": {},
    }


@pytest.fixture
def populated_maps():
    """Field maps with data at every level."""
    return {
        "by_candidate_id": {
            "cand-obs-direct": ["obs_field_a", "obs_field_b", "obs_field_c"],
        },
        "by_source_system": {
            "hubspot": ["hs_account_id", "hs_contact", "hs_deal"],
        },
        "by_pipe_id": {
            "pipe-777": ["pipe_entity_x", "pipe_key_y"],
        },
    }


def _make_candidate(**overrides):
    base = {
        "candidate_id": "cand-001",
        "vendor_name": "TestVendor",
        "display_name": "Test Vendor App",
        "category": "crm",
        "matched_pipe_id": None,
        "governance_status": "governed",
        "updated_at": "2026-02-16T00:00:00Z",
        "asset_key": "testvendor.com",
        "aod_asset_id": "aod-001",
        "fabric_plane_id": None,
        "connected_via_plane": None,
        "status": "connected",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# CATEGORY_STANDARD_FIELDS + PLANE_STANDARD_FIELDS completeness
# ---------------------------------------------------------------------------

class TestFieldDefinitionCompleteness:
    """Verify field definitions are well-formed and cover all known categories/planes."""

    def test_all_sor_categories_have_fields(self):
        """Every SOR category recognized by AAM must have standard fields."""
        for cat in SOR_CATEGORIES:
            fields = CATEGORY_STANDARD_FIELDS.get(cat)
            assert fields is not None, f"Category '{cat}' missing from CATEGORY_STANDARD_FIELDS"
            assert len(fields) >= 5, f"Category '{cat}' has too few fields ({len(fields)})"

    def test_ipaas_and_other_have_fields(self):
        """AOD sends 'ipaas' and 'other' — both must have field definitions."""
        for cat in ["ipaas", "other"]:
            fields = CATEGORY_STANDARD_FIELDS.get(cat)
            assert fields is not None, f"Category '{cat}' missing from CATEGORY_STANDARD_FIELDS"
            assert len(fields) >= 10, f"Category '{cat}' has too few fields ({len(fields)})"

    def test_all_plane_types_have_fields(self):
        """Every fabric plane type must have standard fields."""
        for pt in ALL_PLANE_TYPES:
            fields = PLANE_STANDARD_FIELDS.get(pt)
            assert fields is not None, f"Plane type '{pt}' missing from PLANE_STANDARD_FIELDS"
            assert len(fields) >= 10, f"Plane type '{pt}' has too few fields ({len(fields)})"

    def test_all_fields_are_strings(self):
        for cat, fields in CATEGORY_STANDARD_FIELDS.items():
            for f in fields:
                assert isinstance(f, str), f"Field in {cat} is not a string: {f!r}"
                assert len(f) > 0, f"Empty field name in category {cat}"
        for pt, fields in PLANE_STANDARD_FIELDS.items():
            for f in fields:
                assert isinstance(f, str), f"Field in plane {pt} is not a string: {f!r}"
                assert len(f) > 0, f"Empty field name in plane {pt}"

    def test_no_duplicate_fields_within_category(self):
        for cat, fields in CATEGORY_STANDARD_FIELDS.items():
            assert len(fields) == len(set(fields)), (
                f"Duplicate fields in category '{cat}': "
                f"{[f for f in fields if fields.count(f) > 1]}"
            )

    def test_no_duplicate_fields_within_plane(self):
        for pt, fields in PLANE_STANDARD_FIELDS.items():
            assert len(fields) == len(set(fields)), (
                f"Duplicate fields in plane '{pt}': "
                f"{[f for f in fields if fields.count(f) > 1]}"
            )

    def test_common_categories_present(self):
        """Core enterprise categories must be defined."""
        for cat in ["crm", "erp", "hcm", "itsm", "idp", "finance", "saas", "ipaas", "other"]:
            assert cat in CATEGORY_STANDARD_FIELDS, f"Missing core category: {cat}"


# ---------------------------------------------------------------------------
# _resolve_fields priority cascade
# ---------------------------------------------------------------------------

class TestResolveFieldsPriority:
    """Verify the field resolution cascade respects priorities."""

    def test_priority_1_observation_by_candidate_id(self, populated_maps):
        """Direct observation link takes highest priority."""
        candidate = _make_candidate(candidate_id="cand-obs-direct", category="crm")
        fields = _resolve_fields(candidate, populated_maps)
        assert fields == ["obs_field_a", "obs_field_b", "obs_field_c"]

    def test_priority_2_observation_by_source_system(self, populated_maps):
        """Source system match is used when no direct observation link exists."""
        candidate = _make_candidate(
            candidate_id="cand-no-obs",
            vendor_name="Hubspot",  # matches "hubspot" in by_source_system
            category="crm",
        )
        fields = _resolve_fields(candidate, populated_maps)
        assert fields == ["hs_account_id", "hs_contact", "hs_deal"]

    def test_priority_3_declared_pipe_fields(self, populated_maps):
        """Declared pipe fields used when no observation matches."""
        candidate = _make_candidate(
            candidate_id="cand-no-obs",
            vendor_name="UnknownVendor",
            matched_pipe_id="pipe-777",
            category="crm",
        )
        fields = _resolve_fields(candidate, populated_maps)
        assert fields == ["pipe_entity_x", "pipe_key_y"]

    def test_priority_4_vendor_plane_mapping(self, empty_maps):
        """Infrastructure vendors get plane-specific fields via INFRA_VENDOR_PLANE."""
        candidate = _make_candidate(
            vendor_name="Snowflake",  # maps to DATA_WAREHOUSE
            category="other",
        )
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == PLANE_STANDARD_FIELDS["DATA_WAREHOUSE"]

    def test_priority_4_kong_gets_api_gateway_fields(self, empty_maps):
        """Kong (API_GATEWAY vendor) gets gateway-specific fields, not 'other' generic."""
        candidate = _make_candidate(
            vendor_name="Kong",
            category="other",
        )
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == PLANE_STANDARD_FIELDS["API_GATEWAY"]

    def test_priority_4_confluent_gets_event_bus_fields(self, empty_maps):
        """Confluent (EVENT_BUS vendor) gets event-bus-specific fields."""
        candidate = _make_candidate(
            vendor_name="Confluent",
            category="other",
        )
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == PLANE_STANDARD_FIELDS["EVENT_BUS"]

    def test_priority_4_workato_gets_ipaas_fields(self, empty_maps):
        """Workato (IPAAS vendor) gets iPaaS-specific fields."""
        candidate = _make_candidate(
            vendor_name="Workato",
            category="other",
        )
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == PLANE_STANDARD_FIELDS["IPAAS"]

    def test_priority_5_category_standard_fields(self, empty_maps):
        """Category defaults used when vendor isn't a known infra vendor."""
        candidate = _make_candidate(category="crm")
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == CATEGORY_STANDARD_FIELDS["crm"]

    def test_priority_5_other_category_fallback(self, empty_maps):
        """Unknown vendors in 'other' get generic 'other' category fields."""
        candidate = _make_candidate(
            vendor_name="SomeUnknownPlatform",
            category="other",
        )
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == CATEGORY_STANDARD_FIELDS["other"]
        assert len(fields) >= 10

    def test_unknown_category_returns_empty(self, empty_maps):
        """Truly unknown category with no other data → empty fields (not crash)."""
        candidate = _make_candidate(category="alien_system")
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == []

    def test_priority_1_beats_priority_5(self, populated_maps):
        """Even if category has fields, observation data wins."""
        candidate = _make_candidate(
            candidate_id="cand-obs-direct",
            category="erp",  # has CATEGORY_STANDARD_FIELDS
        )
        fields = _resolve_fields(candidate, populated_maps)
        assert fields == ["obs_field_a", "obs_field_b", "obs_field_c"]

    def test_category_fields_are_copies(self, empty_maps):
        """Returned category fields must be copies, not references."""
        candidate = _make_candidate(category="crm")
        fields = _resolve_fields(candidate, empty_maps)
        original = CATEGORY_STANDARD_FIELDS["crm"]
        fields.append("mutated_field")
        assert "mutated_field" not in original

    def test_vendor_name_case_insensitive(self, populated_maps):
        """Vendor name matching must be case-insensitive."""
        candidate = _make_candidate(
            candidate_id="cand-no-obs",
            vendor_name="HUBSPOT",  # uppercase, should match "hubspot"
        )
        fields = _resolve_fields(candidate, populated_maps)
        assert fields == ["hs_account_id", "hs_contact", "hs_deal"]


# ---------------------------------------------------------------------------
# Seed data coverage: verify all 30 candidates from seed get fields
# ---------------------------------------------------------------------------

class TestSeedDataCoverage:
    """Verify that every candidate from the actual AOD seed payload gets fields."""

    SEED_CANDIDATES = [
        ("Salesforce", "crm"),
        ("Workday", "hcm"),
        ("ServiceNow", "itsm"),
        ("SAP", "erp"),
        ("Okta", "idp"),
        ("NetSuite", "erp"),
        ("HubSpot", "crm"),
        ("Zendesk", "itsm"),
        ("BambooHR", "hcm"),
        ("Atlassian", "itsm"),
        ("MuleSoft", "ipaas"),
        ("Kong", "other"),         # → API_GATEWAY plane fields
        ("Confluent", "other"),    # → EVENT_BUS plane fields
        ("Snowflake", "other"),    # → DATA_WAREHOUSE plane fields
        ("Workato", "other"),      # → IPAAS plane fields
        ("Apigee", "other"),       # → API_GATEWAY plane fields
        ("Databricks", "other"),   # → DATA_WAREHOUSE plane fields
        ("EventBridge", "other"),  # → EVENT_BUS plane fields
        ("Coupa", "finance"),
        ("DocuSign", "saas"),
        ("Boomi", "other"),        # → IPAAS plane fields
        ("BigQuery", "other"),     # → DATA_WAREHOUSE plane fields
        ("Slack", "saas"),
        ("Greenhouse", "hr"),
        ("Zapier", "other"),       # → IPAAS plane fields
        ("Azure APIM", "other"),   # → API_GATEWAY plane fields
        ("RabbitMQ", "other"),     # → EVENT_BUS plane fields
        ("Redshift", "other"),     # → DATA_WAREHOUSE plane fields
        ("Microsoft Dynamics", "crm"),
        ("CyberArk", "identity"),
    ]

    @pytest.mark.parametrize("vendor_name,category", SEED_CANDIDATES)
    def test_seed_candidate_gets_fields(self, vendor_name, category, empty_maps):
        """Every candidate from the AOD seed payload must resolve to non-empty fields."""
        candidate = _make_candidate(vendor_name=vendor_name, category=category)
        fields = _resolve_fields(candidate, empty_maps)
        assert len(fields) >= 10, (
            f"{vendor_name} ({category}) resolved to {len(fields)} fields: {fields}"
        )
        assert all(isinstance(f, str) for f in fields)


# ---------------------------------------------------------------------------
# DCLConnectionSchema contract
# ---------------------------------------------------------------------------

class TestDCLConnectionSchemaContract:
    """Verify the output schema matches the DCL contract."""

    def test_fields_is_list_of_strings(self):
        schema = DCLConnectionSchema(
            pipe_id="p1",
            source_name="Test",
            vendor="test_vendor",
            category="crm",
            fields=["field_a", "field_b"],
            asset_key="test.com",
        )
        assert isinstance(schema.fields, list)
        assert all(isinstance(f, str) for f in schema.fields)

    def test_fields_default_is_empty_list(self):
        schema = DCLConnectionSchema(
            pipe_id="p1",
            source_name="Test",
            vendor="test_vendor",
            category="crm",
            asset_key="test.com",
        )
        assert schema.fields == []

    def test_model_dump_structure(self):
        schema = DCLConnectionSchema(
            pipe_id="p1",
            source_name="Salesforce",
            vendor="salesforce",
            category="crm",
            fields=["account_id", "account_name"],
            asset_key="salesforce.com",
        )
        d = schema.model_dump()
        assert "fields" in d
        assert d["fields"] == ["account_id", "account_name"]
        assert d["pipe_id"] == "p1"


# ---------------------------------------------------------------------------
# DCLExportResponse structure
# ---------------------------------------------------------------------------

class TestDCLExportResponseContract:
    """Verify the top-level export response structure."""

    def test_export_response_has_required_fields(self):
        resp = DCLExportResponse(
            timestamp="2026-02-16T00:00:00Z",
            fabric_planes=[],
            total_connections=0,
        )
        d = resp.model_dump()
        assert "fabric_planes" in d
        assert "total_connections" in d
        assert "timestamp" in d
        assert "source" in d
        assert d["source"] == "aam"


# ---------------------------------------------------------------------------
# Integration-style: mock DB, full build_dcl_export
# ---------------------------------------------------------------------------

class TestBuildDCLExportWithMocks:
    """Test build_dcl_export with mocked DB calls to verify end-to-end field population."""

    def test_connections_have_fields_populated(self, monkeypatch):
        """After the fix, NO connection should have empty fields if it has a known category."""
        mock_planes = [
            {
                "plane_id": "IPAAS:workato",
                "plane_type": "IPAAS",
                "vendor": "workato",
                "display_name": "Workato iPaaS",
                "is_healthy": True,
            }
        ]
        mock_candidates = [
            {
                "candidate_id": "c1",
                "asset_key": "salesforce.com",
                "vendor_name": "salesforce",
                "display_name": "Salesforce CRM",
                "category": "crm",
                "governance_status": "governed",
                "status": "connected",
                "fabric_plane_id": "IPAAS:workato",
                "connected_via_plane": "IPAAS",
                "matched_pipe_id": None,
                "updated_at": "2026-02-16T00:00:00Z",
                "aod_asset_id": "aod-1",
            },
            {
                "candidate_id": "c2",
                "asset_key": "netsuite.com",
                "vendor_name": "netsuite",
                "display_name": "NetSuite ERP",
                "category": "erp",
                "governance_status": "governed",
                "status": "connected",
                "fabric_plane_id": "IPAAS:workato",
                "connected_via_plane": "IPAAS",
                "matched_pipe_id": None,
                "updated_at": "2026-02-16T00:00:00Z",
                "aod_asset_id": "aod-2",
            },
        ]

        monkeypatch.setattr("app.dcl_export.get_fabric_planes", lambda aod_run_id=None: mock_planes)
        monkeypatch.setattr("app.dcl_export.list_candidates", lambda **kwargs: mock_candidates)
        monkeypatch.setattr("app.dcl_export.get_all_schema_samples", lambda: [])
        monkeypatch.setattr("app.dcl_export.sb.select", lambda *a, **kw: [])

        from app.dcl_export import build_dcl_export
        result = build_dcl_export()

        assert result.total_connections == 2
        for plane in result.fabric_planes:
            for conn in plane.connections:
                assert len(conn.fields) > 0, (
                    f"Connection {conn.source_name} ({conn.category}) has empty fields"
                )
                assert all(isinstance(f, str) for f in conn.fields)

    def test_observation_fields_take_precedence(self, monkeypatch):
        """When observations exist, their fields override category defaults."""
        mock_planes = [
            {
                "plane_id": "API_GATEWAY:kong",
                "plane_type": "API_GATEWAY",
                "vendor": "kong",
                "display_name": "Kong Gateway",
                "is_healthy": True,
            }
        ]
        mock_candidates = [
            {
                "candidate_id": "c-obs",
                "asset_key": "hubspot.com",
                "vendor_name": "hubspot",
                "display_name": "HubSpot CRM",
                "category": "crm",
                "governance_status": "governed",
                "status": "connected",
                "fabric_plane_id": "API_GATEWAY:kong",
                "connected_via_plane": "API_GATEWAY",
                "matched_pipe_id": None,
                "updated_at": "2026-02-16T00:00:00Z",
                "aod_asset_id": "aod-obs",
            },
        ]
        mock_obs = [
            {
                "candidate_id": "c-obs",
                "source_system": "hubspot",
                "field_names": ["real_field_1", "real_field_2", "real_field_3"],
            }
        ]

        monkeypatch.setattr("app.dcl_export.get_fabric_planes", lambda aod_run_id=None: mock_planes)
        monkeypatch.setattr("app.dcl_export.list_candidates", lambda **kwargs: mock_candidates)
        monkeypatch.setattr("app.dcl_export.get_all_schema_samples", lambda: mock_obs)
        monkeypatch.setattr("app.dcl_export.sb.select", lambda *a, **kw: [])

        from app.dcl_export import build_dcl_export
        result = build_dcl_export()

        conn = result.fabric_planes[0].connections[0]
        assert conn.fields == ["real_field_1", "real_field_2", "real_field_3"]
        assert conn.fields != CATEGORY_STANDARD_FIELDS["crm"]

    def test_infra_vendor_other_gets_plane_fields(self, monkeypatch):
        """Infrastructure vendors categorised as 'other' get plane-specific fields."""
        mock_planes = [
            {
                "plane_id": "DATA_WAREHOUSE:snowflake",
                "plane_type": "DATA_WAREHOUSE",
                "vendor": "snowflake",
                "display_name": "Snowflake",
                "is_healthy": True,
            }
        ]
        mock_candidates = [
            {
                "candidate_id": "c-snow",
                "asset_key": "snowflake.com",
                "vendor_name": "Snowflake",
                "display_name": "Snowflake Data Warehouse",
                "category": "other",
                "governance_status": "governed",
                "status": "connected",
                "fabric_plane_id": "DATA_WAREHOUSE:snowflake",
                "connected_via_plane": "DATA_WAREHOUSE",
                "matched_pipe_id": None,
                "updated_at": "2026-02-16T00:00:00Z",
                "aod_asset_id": "aod-snow",
            },
        ]

        monkeypatch.setattr("app.dcl_export.get_fabric_planes", lambda aod_run_id=None: mock_planes)
        monkeypatch.setattr("app.dcl_export.list_candidates", lambda **kwargs: mock_candidates)
        monkeypatch.setattr("app.dcl_export.get_all_schema_samples", lambda: [])
        monkeypatch.setattr("app.dcl_export.sb.select", lambda *a, **kw: [])

        from app.dcl_export import build_dcl_export
        result = build_dcl_export()

        conn = result.fabric_planes[0].connections[0]
        assert conn.fields == PLANE_STANDARD_FIELDS["DATA_WAREHOUSE"]
        assert "table_name" in conn.fields

    def test_no_empty_fields_across_all_known_categories(self, monkeypatch):
        """Every known category should produce non-empty fields via category defaults."""
        mock_planes = [
            {
                "plane_id": "IPAAS:mulesoft",
                "plane_type": "IPAAS",
                "vendor": "mulesoft",
                "display_name": "MuleSoft",
                "is_healthy": True,
            }
        ]

        categories = list(CATEGORY_STANDARD_FIELDS.keys())
        mock_candidates = []
        for i, cat in enumerate(categories):
            mock_candidates.append({
                "candidate_id": f"c-{cat}",
                "asset_key": f"{cat}.example.com",
                "vendor_name": f"{cat}_vendor",
                "display_name": f"{cat.upper()} System",
                "category": cat,
                "governance_status": "governed",
                "status": "connected",
                "fabric_plane_id": "IPAAS:mulesoft",
                "connected_via_plane": "IPAAS",
                "matched_pipe_id": None,
                "updated_at": "2026-02-16T00:00:00Z",
                "aod_asset_id": f"aod-{cat}",
            })

        monkeypatch.setattr("app.dcl_export.get_fabric_planes", lambda aod_run_id=None: mock_planes)
        monkeypatch.setattr("app.dcl_export.list_candidates", lambda **kwargs: mock_candidates)
        monkeypatch.setattr("app.dcl_export.get_all_schema_samples", lambda: [])
        monkeypatch.setattr("app.dcl_export.sb.select", lambda *a, **kw: [])

        from app.dcl_export import build_dcl_export
        result = build_dcl_export()

        for plane in result.fabric_planes:
            for conn in plane.connections:
                assert len(conn.fields) >= 5, (
                    f"Category '{conn.category}' has fewer than 5 fields: {conn.fields}"
                )
