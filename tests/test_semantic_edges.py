"""
Integration tests for SemanticEdge extraction across all 4 fabric planes.

Tests the parsers with realistic mock data and verifies:
- Correct edge_type assignment (DIRECT_MAP, TRANSFORMED, CONDITIONAL, INFERRED)
- Correct confidence scores per tier
- Field references parsed correctly
- Source system inference works
- Adapter wiring persists edges (mocked DB layer)
"""
import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.parsers.ipaas_recipe import parse_workato_recipe, parse_tray_workflow
from app.parsers.warehouse_schema import parse_information_schema, _infer_source_from_table
from app.parsers.dbt_manifest import parse_dbt_manifest
from app.parsers.eventbus_schema import parse_schema_registry_subjects, _infer_system_from_topic


# ============================================================================
# SAMPLE DATA — realistic mock payloads for each plane
# ============================================================================

WORKATO_RECIPE_STRUCTURED = {
    "id": 4782,
    "name": "Sync SF Opportunities to NS Sales Orders",
    "trigger_application": "salesforce",
    "action_applications": ["netsuite"],
    "config": {
        "trigger": {
            "application": "salesforce",
            "object": "Opportunity",
            "event": "new_or_updated",
            "filter": {"Stage": "Closed Won"},
        },
        "actions": [
            {
                "application": "netsuite",
                "object": "SalesOrder",
                "action": "create",
                "field_mappings": [
                    {"source": "Opportunity.Name", "target": "memo"},
                    {"source": "Opportunity.Amount", "target": "total"},
                    {"source": "Opportunity.CloseDate", "target": "tranDate"},
                    {"source": "Account.Name", "target": "Customer.companyName"},
                    {
                        "source": "Contact.FirstName",
                        "target": "contactName",
                        "formula": 'CONCAT(Contact.FirstName, " ", Contact.LastName)',
                    },
                    {
                        "source": "Opportunity.Amount",
                        "target": "localTotal",
                        "condition": "IF(currency == 'USD', Amount, Amount * exchangeRate)",
                    },
                ],
            }
        ],
    },
}

WORKATO_RECIPE_FLAT = {
    "id": 9001,
    "source_application": "hubspot",
    "target_application": "salesforce",
    "mappings": [
        {"source": "Contact.email", "target": "Lead.Email"},
        {"source": "Contact.firstname", "target": "Lead.FirstName"},
        {"source": "Company.name", "target": "Account.Name"},
    ],
}

TRAY_WORKFLOW = {
    "id": "tray-wf-001",
    "trigger": {"connector": "zendesk"},
    "steps": [
        {
            "connector": "salesforce",
            "operation": "Case",
            "input_fields": [
                {"source": "Ticket.subject", "field": "Subject"},
                {"source": "Ticket.description", "field": "Description"},
            ],
        }
    ],
}

WAREHOUSE_COLUMNS = [
    {"table_schema": "salesforce", "table_name": "opportunity", "column_name": "id", "data_type": "varchar"},
    {"table_schema": "salesforce", "table_name": "opportunity", "column_name": "amount", "data_type": "numeric"},
    {"table_schema": "salesforce", "table_name": "opportunity", "column_name": "close_date", "data_type": "date"},
    {"table_schema": "public", "table_name": "salesforce__account", "column_name": "name", "data_type": "varchar"},
    {"table_schema": "public", "table_name": "salesforce__account", "column_name": "industry", "data_type": "varchar"},
    {"table_schema": "raw", "table_name": "ns_sales_order", "column_name": "total", "data_type": "numeric"},
    {"table_schema": "information_schema", "table_name": "columns", "column_name": "table_name", "data_type": "varchar"},
]

DBT_MANIFEST = {
    "sources": {
        "source.my_project.salesforce.opportunity": {
            "source_name": "salesforce",
            "name": "opportunity",
            "schema": "raw_salesforce",
            "database": "analytics",
            "columns": {
                "id": {"name": "id", "description": "Primary key"},
                "amount": {"name": "amount", "description": "Deal amount"},
                "close_date": {"name": "close_date", "description": "Close date"},
                "account_id": {"name": "account_id", "description": "FK to account"},
            },
        },
    },
    "nodes": {
        "model.my_project.fct_opportunities": {
            "resource_type": "model",
            "name": "fct_opportunities",
            "schema": "analytics",
            "columns": {
                "opportunity_id": {
                    "name": "opportunity_id",
                    "meta": {"source_field": "id"},
                },
                "amount": {"name": "amount"},
                "close_date": {"name": "close_date"},
                "revenue_usd": {
                    "name": "revenue_usd",
                    "meta": {
                        "source_field": "amount",
                        "transformation": "amount * exchange_rate",
                    },
                },
            },
            "depends_on": {
                "nodes": ["source.my_project.salesforce.opportunity"],
            },
        },
        "model.my_project.dim_accounts": {
            "resource_type": "model",
            "name": "dim_accounts",
            "schema": "analytics",
            "columns": {},
            "depends_on": {"nodes": []},
        },
    },
}

SCHEMA_REGISTRY_SUBJECTS = [
    {
        "subject": "salesforce.opportunity.created",
        "schema_type": "AVRO",
        "schema": {
            "type": "record",
            "name": "OpportunityCreated",
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "amount", "type": ["null", "double"]},
                {"name": "stage", "type": "string"},
                {"name": "close_date", "type": "string"},
            ],
        },
        "producer": "salesforce",
    },
    {
        "subject": "netsuite.order.synced",
        "schema_type": "JSON",
        "schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "total": {"type": "number"},
                "currency": {"type": "string"},
            },
        },
    },
]


# ============================================================================
# PLANE 1: iPaaS PARSER TESTS
# ============================================================================

class TestIPaaSParser:
    def test_workato_structured_recipe_direct_maps(self):
        """Direct field mappings get 0.95 confidence."""
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        direct_edges = [e for e in edges if e["edge_type"] == "DIRECT_MAP"]
        assert len(direct_edges) >= 3
        for e in direct_edges:
            assert e["confidence"] == 0.95
            assert e["fabric_plane"] == "IPAAS"
            assert e["source_system"] == "salesforce"
            assert e["target_system"] == "netsuite"

    def test_workato_structured_recipe_transformed(self):
        """Formula mappings (CONCAT) get 0.85 confidence."""
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        transformed = [e for e in edges if e["edge_type"] == "TRANSFORMED"]
        assert len(transformed) >= 1
        for e in transformed:
            assert e["confidence"] == 0.85
            assert e["transformation"] is not None

    def test_workato_structured_recipe_conditional(self):
        """Conditional mappings (IF) get 0.70 confidence."""
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        conditional = [e for e in edges if e["edge_type"] == "CONDITIONAL"]
        assert len(conditional) >= 1
        for e in conditional:
            assert e["confidence"] == 0.70

    def test_workato_structured_total_edges(self):
        """All 6 mappings in the recipe should produce 6 edges."""
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        assert len(edges) == 6

    def test_workato_flat_recipe(self):
        """Flat mappings format produces correct edges."""
        edges = parse_workato_recipe(WORKATO_RECIPE_FLAT)
        assert len(edges) == 3
        assert all(e["source_system"] == "hubspot" for e in edges)
        assert all(e["target_system"] == "salesforce" for e in edges)
        assert all(e["edge_type"] == "DIRECT_MAP" for e in edges)
        assert all(e["confidence"] == 0.95 for e in edges)

    def test_workato_extraction_source(self):
        """Extraction source should reference the recipe ID."""
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        assert all(e["extraction_source"] == "workato_recipe_4782" for e in edges)

    def test_workato_field_parsing(self):
        """Object.Field references parsed correctly."""
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        name_edge = next(e for e in edges if e["source_field"] == "Name" and e["source_object"] == "Opportunity")
        assert name_edge["target_field"] == "memo"
        assert name_edge["target_object"] == "SalesOrder"

    def test_tray_workflow(self):
        """Tray.io workflows parsed correctly."""
        edges = parse_tray_workflow(TRAY_WORKFLOW)
        assert len(edges) == 2
        assert all(e["source_system"] == "zendesk" for e in edges)
        assert all(e["target_system"] == "salesforce" for e in edges)

    def test_empty_recipe(self):
        """Empty recipe returns no edges, no crash."""
        edges = parse_workato_recipe({"id": 999})
        assert edges == []

    def test_all_edges_have_required_fields(self):
        """Every edge has all required SemanticEdge fields."""
        required = {
            "id", "source_system", "source_object", "source_field",
            "target_system", "target_object", "target_field",
            "edge_type", "confidence", "fabric_plane",
            "extraction_source", "discovered_at", "last_verified",
        }
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        for e in edges:
            assert required.issubset(e.keys()), f"Missing fields: {required - e.keys()}"


# ============================================================================
# PLANE 2: WAREHOUSE — information_schema
# ============================================================================

class TestWarehouseSchemaParser:
    def test_column_inventory_count(self):
        """Should produce edges for all non-system-schema columns."""
        edges = parse_information_schema(WAREHOUSE_COLUMNS, warehouse_vendor="snowflake")
        # 6 columns in real schemas (salesforce, public, raw), 1 in information_schema (skipped)
        assert len(edges) == 6

    def test_system_schema_filtered(self):
        """information_schema and pg_catalog rows are skipped."""
        edges = parse_information_schema(WAREHOUSE_COLUMNS, warehouse_vendor="snowflake")
        targets = [e["target_object"] for e in edges]
        assert not any("information_schema" in t for t in targets)

    def test_confidence_inferred(self):
        """All warehouse schema edges are INFERRED at 0.70."""
        edges = parse_information_schema(WAREHOUSE_COLUMNS, warehouse_vendor="snowflake")
        assert all(e["edge_type"] == "INFERRED" for e in edges)
        assert all(e["confidence"] == 0.70 for e in edges)
        assert all(e["fabric_plane"] == "DATA_WAREHOUSE" for e in edges)

    def test_source_system_from_schema(self):
        """Columns in 'salesforce' schema → source_system='salesforce'."""
        edges = parse_information_schema(WAREHOUSE_COLUMNS, warehouse_vendor="snowflake")
        sf_edges = [e for e in edges if e["source_system"] == "salesforce"]
        assert len(sf_edges) >= 3  # opportunity.id, amount, close_date + account prefix

    def test_source_system_from_double_underscore(self):
        """Table 'salesforce__account' → source_system='salesforce'."""
        edges = parse_information_schema(WAREHOUSE_COLUMNS, warehouse_vendor="snowflake")
        sf_account = [e for e in edges if e["source_object"] == "account" and e["source_system"] == "salesforce"]
        assert len(sf_account) == 2  # name, industry

    def test_infer_source_table_patterns(self):
        """Test the source inference helper directly."""
        assert _infer_source_from_table("salesforce__opportunity", "public") == ("salesforce", "opportunity")
        assert _infer_source_from_table("sf_account", "public") == ("salesforce", "account")
        assert _infer_source_from_table("random_table", "netsuite") == ("netsuite", "random_table")
        assert _infer_source_from_table("just_a_table", "public") == ("public", "just_a_table")


# ============================================================================
# PLANE 3: WAREHOUSE — dbt manifest
# ============================================================================

class TestDbtManifestParser:
    def test_dbt_lineage_edge_count(self):
        """Should produce edges for matched columns."""
        edges = parse_dbt_manifest(DBT_MANIFEST, warehouse_vendor="snowflake")
        # opportunity_id (meta→id), amount (name match), close_date (name match),
        # revenue_usd (meta→amount)
        assert len(edges) >= 3

    def test_dbt_explicit_meta_mapping(self):
        """Column with meta.source_field gets a 0.95 DIRECT_MAP."""
        edges = parse_dbt_manifest(DBT_MANIFEST, warehouse_vendor="snowflake")
        opp_id_edge = next(
            (e for e in edges if e["target_field"] == "opportunity_id"),
            None,
        )
        assert opp_id_edge is not None
        assert opp_id_edge["source_field"] == "id"
        assert opp_id_edge["confidence"] == 0.95
        assert opp_id_edge["edge_type"] == "DIRECT_MAP"

    def test_dbt_name_match(self):
        """Column with matching name in source gets 0.95."""
        edges = parse_dbt_manifest(DBT_MANIFEST, warehouse_vendor="snowflake")
        amount_edge = next(
            (e for e in edges if e["target_field"] == "amount" and e["source_field"] == "amount"),
            None,
        )
        assert amount_edge is not None
        assert amount_edge["confidence"] == 0.95

    def test_dbt_transformation_captured(self):
        """Column with meta.transformation records the formula."""
        edges = parse_dbt_manifest(DBT_MANIFEST, warehouse_vendor="snowflake")
        rev_edge = next(
            (e for e in edges if e["target_field"] == "revenue_usd"),
            None,
        )
        assert rev_edge is not None
        assert rev_edge["transformation"] == "amount * exchange_rate"

    def test_dbt_source_system(self):
        """All edges from salesforce source have source_system='salesforce'."""
        edges = parse_dbt_manifest(DBT_MANIFEST, warehouse_vendor="snowflake")
        assert all(e["source_system"] == "salesforce" for e in edges)

    def test_dbt_extraction_source_format(self):
        """Extraction source references the dbt model name."""
        edges = parse_dbt_manifest(DBT_MANIFEST, warehouse_vendor="snowflake")
        assert all(e["extraction_source"].startswith("dbt_model_") for e in edges)

    def test_dbt_empty_manifest(self):
        """Empty manifest returns no edges."""
        edges = parse_dbt_manifest({})
        assert edges == []


# ============================================================================
# PLANE 4: EVENT BUS — schema registry
# ============================================================================

class TestEventBusSchemaParser:
    def test_avro_schema_fields(self):
        """Avro record schema fields extracted correctly."""
        edges = parse_schema_registry_subjects(SCHEMA_REGISTRY_SUBJECTS, bus_vendor="kafka")
        sf_edges = [e for e in edges if e["source_system"] == "salesforce"]
        assert len(sf_edges) == 4  # id, amount, stage, close_date

    def test_json_schema_fields(self):
        """JSON Schema properties extracted correctly."""
        edges = parse_schema_registry_subjects(SCHEMA_REGISTRY_SUBJECTS, bus_vendor="kafka")
        ns_edges = [e for e in edges if "netsuite" in e["extraction_source"]]
        assert len(ns_edges) == 3  # order_id, total, currency

    def test_event_bus_confidence(self):
        """All schema registry edges get 0.80 confidence."""
        edges = parse_schema_registry_subjects(SCHEMA_REGISTRY_SUBJECTS, bus_vendor="kafka")
        assert all(e["confidence"] == 0.80 for e in edges)
        assert all(e["edge_type"] == "INFERRED" for e in edges)
        assert all(e["fabric_plane"] == "EVENT_BUS" for e in edges)

    def test_topic_system_inference(self):
        """Topic name 'salesforce.opportunity.created' → source='salesforce'."""
        assert _infer_system_from_topic("salesforce.opportunity.created") == "salesforce"
        assert _infer_system_from_topic("cdc.netsuite.sales_order") == "netsuite"
        assert _infer_system_from_topic("sf-contact-events") == "salesforce"
        assert _infer_system_from_topic("completely-unknown-topic") == "unknown"

    def test_explicit_producer(self):
        """Explicit producer overrides topic name inference."""
        edges = parse_schema_registry_subjects(SCHEMA_REGISTRY_SUBJECTS, bus_vendor="kafka")
        sf_edges = [e for e in edges if e["source_system"] == "salesforce"]
        # The first subject has explicit producer="salesforce"
        assert len(sf_edges) >= 4

    def test_empty_subjects(self):
        """Empty subject list returns no edges."""
        edges = parse_schema_registry_subjects([], bus_vendor="kafka")
        assert edges == []


# ============================================================================
# ADAPTER WIRING — mock DB layer to verify persistence
# ============================================================================

def _ensure_psycopg2_mock():
    """Inject mock psycopg2 into sys.modules so the adapter import chain
    doesn't fail when psycopg2 isn't installed locally."""
    import sys
    if "psycopg2" not in sys.modules:
        mock_pg = MagicMock()
        sys.modules["psycopg2"] = mock_pg
        sys.modules["psycopg2.pool"] = mock_pg.pool
        sys.modules["psycopg2.extras"] = mock_pg.extras
        sys.modules["psycopg2.sql"] = mock_pg.sql


class TestAdapterWiring:
    """Test adapter persistence wiring by mocking the DB functions
    before the adapter modules are imported."""

    def _mock_db(self):
        """Set up mock DB module to avoid Supabase connection."""
        mock_store = MagicMock(side_effect=lambda rows: rows)
        mock_delete = MagicMock(return_value=[])
        return mock_store, mock_delete

    def test_ipaas_adapter_persists_edges(self):
        """IPaaSAdapter.extract_semantic_edges calls store + delete."""
        _ensure_psycopg2_mock()
        mock_store, mock_delete = self._mock_db()

        import app.adapters.ipaas as ipaas_mod
        ipaas_mod.store_semantic_edges_batch = mock_store
        ipaas_mod.delete_semantic_edges_by_source = mock_delete

        adapter = ipaas_mod.IPaaSAdapter({"vendor": "workato"})
        result = adapter.extract_semantic_edges([WORKATO_RECIPE_STRUCTURED])

        mock_delete.assert_called()
        mock_store.assert_called_once()
        stored_edges = mock_store.call_args[0][0]
        assert len(stored_edges) == 6

    def test_ipaas_adapter_zapier_gap(self):
        """Zapier adapter logs gap warning, stores no edges."""
        _ensure_psycopg2_mock()
        mock_store, mock_delete = self._mock_db()

        import app.adapters.ipaas as ipaas_mod
        ipaas_mod.store_semantic_edges_batch = mock_store
        ipaas_mod.delete_semantic_edges_by_source = mock_delete

        adapter = ipaas_mod.IPaaSAdapter({"vendor": "zapier"})
        result = adapter.extract_semantic_edges([{"id": 1, "name": "Some Zap"}])
        mock_store.assert_not_called()
        assert result == []

    def test_warehouse_adapter_both_layers(self):
        """WarehouseAdapter runs both info_schema and dbt layers."""
        _ensure_psycopg2_mock()
        mock_store, mock_delete = self._mock_db()

        import app.adapters.warehouse as wh_mod
        wh_mod.store_semantic_edges_batch = mock_store
        wh_mod.delete_semantic_edges_by_source = mock_delete

        adapter = wh_mod.WarehouseAdapter({"vendor": "snowflake"})
        result = adapter.extract_semantic_edges(
            WAREHOUSE_COLUMNS,
            dbt_manifest=DBT_MANIFEST,
            database_name="analytics",
        )

        # Should be called twice: once for info_schema, once for dbt
        assert mock_store.call_count == 2

    def test_eventbus_adapter_persists_edges(self):
        """EventBusAdapter.extract_semantic_edges calls store."""
        _ensure_psycopg2_mock()
        mock_store, mock_delete = self._mock_db()

        import app.adapters.eventbus as eb_mod
        eb_mod.store_semantic_edges_batch = mock_store
        eb_mod.delete_semantic_edges_by_source = mock_delete

        adapter = eb_mod.EventBusAdapter({"vendor": "kafka"})
        result = adapter.extract_semantic_edges(SCHEMA_REGISTRY_SUBJECTS)

        mock_store.assert_called_once()
        stored_edges = mock_store.call_args[0][0]
        assert len(stored_edges) == 7  # 4 avro + 3 json


# ============================================================================
# CONFIDENCE SCORE SUMMARY — cross-plane verification
# ============================================================================

class TestConfidenceScores:
    """Verify the confidence score contract across all planes."""

    def test_ipaas_direct_095(self):
        edges = parse_workato_recipe(WORKATO_RECIPE_FLAT)
        assert all(e["confidence"] == 0.95 for e in edges)

    def test_ipaas_transformed_085(self):
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        transformed = [e for e in edges if e["edge_type"] == "TRANSFORMED"]
        assert all(e["confidence"] == 0.85 for e in transformed)

    def test_ipaas_conditional_070(self):
        edges = parse_workato_recipe(WORKATO_RECIPE_STRUCTURED)
        conditional = [e for e in edges if e["edge_type"] == "CONDITIONAL"]
        assert all(e["confidence"] == 0.70 for e in conditional)

    def test_warehouse_inferred_070(self):
        edges = parse_information_schema(WAREHOUSE_COLUMNS)
        assert all(e["confidence"] == 0.70 for e in edges)

    def test_dbt_direct_095(self):
        edges = parse_dbt_manifest(DBT_MANIFEST)
        assert all(e["confidence"] == 0.95 for e in edges)

    def test_event_bus_080(self):
        edges = parse_schema_registry_subjects(SCHEMA_REGISTRY_SUBJECTS)
        assert all(e["confidence"] == 0.80 for e in edges)


# ============================================================================
# NEGATIVE TESTS — confirm bad behavior can't return
# ============================================================================

class TestNegativeCases:
    def test_no_silent_fallback_on_missing_fields(self):
        """Mappings with empty source/target are skipped, not faked."""
        recipe = {
            "id": 100,
            "config": {
                "trigger": {"application": "salesforce"},
                "actions": [{
                    "application": "netsuite",
                    "object": "Order",
                    "field_mappings": [
                        {"source": "", "target": "memo"},
                        {"source": "Opp.Name", "target": ""},
                        {"source": "Opp.Amount", "target": "total"},
                    ],
                }],
            },
        }
        edges = parse_workato_recipe(recipe)
        assert len(edges) == 1
        assert edges[0]["source_field"] == "Amount"
        assert edges[0]["target_field"] == "total"

    def test_no_edges_from_unknown_schema_type(self):
        """Unknown schema type produces no edges, no crash."""
        subjects = [{
            "subject": "test-topic",
            "schema_type": "THRIFT",
            "schema": {"fields": [{"name": "x"}]},
        }]
        edges = parse_schema_registry_subjects(subjects)
        assert edges == []

    def test_dbt_non_model_nodes_ignored(self):
        """Seeds and tests in the manifest don't produce edges."""
        manifest = {
            "sources": {},
            "nodes": {
                "seed.my_project.countries": {
                    "resource_type": "seed",
                    "name": "countries",
                    "columns": {"code": {}},
                    "depends_on": {"nodes": []},
                },
                "test.my_project.unique_id": {
                    "resource_type": "test",
                    "name": "unique_id",
                    "columns": {},
                    "depends_on": {"nodes": []},
                },
            },
        }
        edges = parse_dbt_manifest(manifest)
        assert edges == []
