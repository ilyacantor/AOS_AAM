"""
WarehouseAdapter - Data Warehouse Plane

Connects to Data Warehouses (Snowflake, BigQuery, Redshift)
to inventory tables and views as Source of Truth.

Modality: JDBC/Bulk Read - treat warehouse as authoritative.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid

from .base import FabricAdapter, AdapterStatus, PlaneHealth, PlaneDrift


class WarehouseAdapter(FabricAdapter):
    """
    Adapter for Data Warehouse Fabric Plane.
    
    Connects to data warehouse platforms to:
    - Discover tables, views, and materialized views
    - Read metadata and schema information
    - Monitor warehouse availability and compute status
    - Self-heal suspended warehouses
    
    Supported vendors: Snowflake, BigQuery, Redshift, Databricks
    
    In Preset 11 (Warehouse-Centric), this is the authoritative Source of Truth.
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
        Currently: Mock implementation for architecture validation.
        """
        self._status = AdapterStatus.CONNECTING
        
        try:
            if self._warehouse_suspended:
                await self._wake_warehouse()
            
            self._status = AdapterStatus.CONNECTED
            self._last_health_check = datetime.utcnow()
            return True
        except Exception as e:
            self._status = AdapterStatus.FAILED
            self._error_message = str(e)
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
        self._last_health_check = datetime.utcnow()
        
        status = self._status
        if self._warehouse_suspended:
            status = AdapterStatus.DEGRADED
        
        return PlaneHealth(
            status=status,
            last_check=self._last_health_check,
            latency_ms=200.0,
            metrics={
                "vendor": self._vendor,
                "warehouse": self._warehouse_name,
                "warehouse_suspended": self._warehouse_suspended,
                "tables_discovered": len(self._tables_discovered),
                "compute_credits_used": 2.5
            }
        )
    
    async def discover_pipes(self) -> List[Dict[str, Any]]:
        """
        Discover tables and views from Data Warehouse.
        
        Returns observations for inference engine to process.
        """
        observations = []
        
        mock_tables = [
            {
                "table": "raw.crm.accounts",
                "type": "table",
                "entities": ["Account"],
                "row_count": 150000,
                "last_modified": "2026-01-23T10:00:00Z"
            },
            {
                "table": "raw.marketing.contacts",
                "type": "table",
                "entities": ["Contact"],
                "row_count": 500000,
                "last_modified": "2026-01-23T09:30:00Z"
            },
            {
                "table": "curated.customers_360",
                "type": "view",
                "entities": ["Customer", "Account", "Contact"],
                "source_tables": ["raw.crm.accounts", "raw.marketing.contacts"],
                "is_materialized": True
            },
            {
                "table": "analytics.revenue_metrics",
                "type": "materialized_view",
                "entities": ["Revenue", "MRR", "ARR"],
                "refresh_schedule": "0 */6 * * *"
            }
        ]
        
        for table in mock_tables:
            observations.append({
                "observation_id": str(uuid.uuid4()),
                "collector_id": f"warehouse-{self._vendor}",
                "observed_at": datetime.utcnow().isoformat(),
                "source_system": self._vendor,
                "endpoint_info": {
                    "type": "warehouse_table",
                    "table_name": table["table"],
                    "table_type": table["type"],
                    "vendor": self._vendor,
                    "warehouse": self._warehouse_name
                },
                "entity_hints": table.get("entities", []),
                "schema_sample": {
                    "row_count": table.get("row_count"),
                    "last_modified": table.get("last_modified")
                },
                "metadata": {
                    "fabric_plane": "DATA_WAREHOUSE",
                    "modality": "DECLARED_INTERFACE",
                    "transport_kind": "TABLE",
                    "change_semantics": "CDC_UPSERT" if table["type"] == "table" else "SNAPSHOT",
                    **table
                }
            })
        
        self._tables_discovered = mock_tables
        return observations
    
    async def self_heal(self, drift: PlaneDrift) -> bool:
        """
        Self-heal Data Warehouse connection issues.
        
        Healing strategies:
        - warehouse_suspended: Wake the warehouse
        - connection_lost: Reconnect
        - query_timeout: Increase timeout, retry with smaller batch
        """
        if drift.drift_type == "warehouse_suspended":
            self._warehouse_suspended = True
            return await self._wake_warehouse()
        
        elif drift.drift_type == "connection_lost":
            return await self.connect()
        
        elif drift.drift_type == "query_timeout":
            return True
        
        return False
    
    def apply_governance_policy(self, policy: Dict[str, Any]) -> bool:
        """
        Apply governance at Warehouse level.
        
        Examples:
        - Row-level security
        - Column masking for PII
        - Query result caching policies
        """
        policy_type = policy.get("type")
        
        if policy_type == "row_level_security":
            return True
        
        elif policy_type == "column_masking":
            return True
        
        elif policy_type == "result_caching":
            return True
        
        return False
