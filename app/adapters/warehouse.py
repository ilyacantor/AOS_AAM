"""
WarehouseAdapter - Data Warehouse Plane

Connects to Data Warehouses (Snowflake, BigQuery, Redshift)
to inventory tables and views as Source of Truth.

Modality: JDBC/Bulk Read - treat warehouse as authoritative.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base import FabricAdapter, AdapterStatus, PlaneHealth, PlaneDrift
from ..parsers.warehouse_schema import parse_information_schema
from ..parsers.dbt_manifest import parse_dbt_manifest
from ..db.semantic_edges import store_semantic_edges_batch, delete_semantic_edges_by_source

_log = logging.getLogger("aam.adapter.warehouse")


class WarehouseAdapter(FabricAdapter):
    """
    Adapter for Data Warehouse Fabric Plane.

    Connects to data warehouse platforms to:
    - Discover tables, views, and materialized views
    - Read metadata and schema information
    - Monitor warehouse availability and compute status
    - Self-heal suspended warehouses

    Supported vendors: Snowflake, BigQuery, Redshift, Databricks

    When the enterprise routes through DATA_WAREHOUSE, this is the authoritative Source of Truth.
    """

    SUPPORTED_VENDORS = ["snowflake", "bigquery", "redshift", "databricks"]

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._vendor = config.get("vendor", "snowflake").lower()
        self._warehouse_name = config.get("warehouse", "AAM_WAREHOUSE")
        self._tables_discovered: List[Dict] = []
        self._warehouse_suspended = False

    @property
    def plane_type(self) -> str:
        return "DATA_WAREHOUSE"

    @property
    def plane_vendor(self) -> str:
        return self._vendor

    async def connect(self) -> bool:
        """
        Connect to Data Warehouse.

        In production: Would establish JDBC/ODBC connection.
        Currently: Stub — no real connection.
        """
        _log.warning("Not implemented — no real connection")
        return False

    async def disconnect(self) -> bool:
        """Disconnect from Data Warehouse"""
        self._status = AdapterStatus.DISCONNECTED
        return True

    async def _wake_warehouse(self) -> bool:
        """
        Wake a suspended warehouse.

        AAM owns this self-healing - does NOT delegate to Farm.
        """
        self._warehouse_suspended = False
        return True

    async def check_health(self) -> PlaneHealth:
        """
        Check Data Warehouse health.

        Key checks: Warehouse status (running/suspended), query latency
        """
        _log.warning("Not implemented — no real connection")
        return PlaneHealth(
            status=AdapterStatus.DISCONNECTED,
            last_check=datetime.utcnow(),
        )

    async def discover_pipes(self) -> List[Dict[str, Any]]:
        """
        Discover tables and views from Data Warehouse.

        Returns observations for inference engine to process.
        """
        _log.warning("Not implemented — no real connection")
        return []

    async def self_heal(self, drift: PlaneDrift) -> bool:
        """
        Self-heal Data Warehouse connection issues.

        Healing strategies:
        - warehouse_suspended: Wake the warehouse
        - connection_lost: Reconnect
        - query_timeout: Increase timeout, retry with smaller batch
        """
        return False

    def extract_semantic_edges(
        self,
        columns: List[Dict[str, Any]],
        dbt_manifest: Optional[Dict[str, Any]] = None,
        database_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract field-level semantic edges from warehouse metadata.

        Two layers:
        A. information_schema columns → INFERRED edges (0.70 confidence)
        B. dbt manifest.json → DIRECT_MAP edges (0.95 confidence)

        dbt edges supersede information_schema edges for the same field
        (higher confidence wins at query time in DCL).

        Args:
            columns: Rows from information_schema.columns
            dbt_manifest: Optional parsed dbt manifest.json
            database_name: Optional database name for provenance

        Returns:
            All extracted SemanticEdge dicts (already persisted)
        """
        all_edges: List[Dict[str, Any]] = []

        # Layer A: information_schema
        if columns:
            extraction_source = f"warehouse_{self._vendor}"
            if database_name:
                extraction_source += f"_{database_name}"
            delete_semantic_edges_by_source(extraction_source)

            schema_edges = parse_information_schema(
                columns,
                warehouse_vendor=self._vendor,
                database_name=database_name,
            )
            if schema_edges:
                stored = store_semantic_edges_batch(schema_edges)
                all_edges.extend(stored)
                _log.info("Stored %d information_schema edges for %s", len(stored), self._vendor)

        # Layer B: dbt manifest
        if dbt_manifest:
            dbt_edges = parse_dbt_manifest(
                dbt_manifest,
                warehouse_vendor=self._vendor,
            )
            if dbt_edges:
                # Collect unique extraction sources and clear previous runs
                dbt_sources = {e["extraction_source"] for e in dbt_edges}
                for src in dbt_sources:
                    delete_semantic_edges_by_source(src)
                stored = store_semantic_edges_batch(dbt_edges)
                all_edges.extend(stored)
                _log.info("Stored %d dbt lineage edges for %s", len(stored), self._vendor)

        _log.info(
            "Warehouse semantic edge extraction complete: %d total edges (vendor=%s)",
            len(all_edges), self._vendor,
        )
        return all_edges

    def apply_governance_policy(self, policy: Dict[str, Any]) -> bool:
        """
        Apply governance at Warehouse level.

        Examples:
        - Row-level security
        - Column masking for PII
        - Query result caching policies
        """
        return False
