"""
Tests for DCL export field resolution.

Validates that the export-pipes endpoint populates fields[] on every
connection using the priority cascade:
  1. Observation schema_sample (by candidate_id)
  2. Observation schema_sample (by source_system ↔ vendor_name)
  3. Declared pipe identity_keys + entity_scope (via matched_pipe_id)
  4. Category-based standard fields (metadata inference)

These tests are pure unit tests — no database connection required.
"""
import pytest
from app.dcl_export import _resolve_fields, DCLConnectionSchema, DCLExportResponse
from app.constants import CATEGORY_STANDARD_FIELDS, SOR_CATEGORIES


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
# CATEGORY_STANDARD_FIELDS completeness
# ---------------------------------------------------------------------------

class TestCategoryStandardFields:
    """Verify the category field definitions are well-formed."""

    def test_all_sor_categories_have_fields(self):
        """Every SOR category recognized by AAM must have standard fields."""
        for cat in SOR_CATEGORIES:
            fields = CATEGORY_STANDARD_FIELDS.get(cat)
            assert fields is not None, f"Category '{cat}' missing from CATEGORY_STANDARD_FIELDS"
            assert len(fields) >= 5, f"Category '{cat}' has too few fields ({len(fields)})"

    def test_all_fields_are_strings(self):
        for cat, fields in CATEGORY_STANDARD_FIELDS.items():
            for f in fields:
                assert isinstance(f, str), f"Field in {cat} is not a string: {f!r}"
                assert len(f) > 0, f"Empty field name in category {cat}"

    def test_no_duplicate_fields_within_category(self):
        for cat, fields in CATEGORY_STANDARD_FIELDS.items():
            assert len(fields) == len(set(fields)), (
                f"Duplicate fields in category '{cat}': "
                f"{[f for f in fields if fields.count(f) > 1]}"
            )

    def test_common_categories_present(self):
        """Core enterprise categories must be defined."""
        for cat in ["crm", "erp", "hcm", "itsm", "idp", "finance", "saas"]:
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

    def test_priority_4_category_standard_fields(self, empty_maps):
        """Category defaults used as last resort."""
        candidate = _make_candidate(category="crm")
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == CATEGORY_STANDARD_FIELDS["crm"]

    def test_unknown_category_returns_empty(self, empty_maps):
        """Unknown category with no other data → empty fields (not crash)."""
        candidate = _make_candidate(category="alien_system")
        fields = _resolve_fields(candidate, empty_maps)
        assert fields == []

    def test_priority_1_beats_priority_4(self, populated_maps):
        """Even if category has fields, observation data wins."""
        candidate = _make_candidate(
            candidate_id="cand-obs-direct",
            category="erp",  # has CATEGORY_STANDARD_FIELDS
        )
        fields = _resolve_fields(candidate, populated_maps)
        # Should return observation fields, not ERP category defaults
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
        # Must NOT be the CRM category defaults
        assert conn.fields != CATEGORY_STANDARD_FIELDS["crm"]

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
