"""
EventBusAdapter - Event Streaming Plane

Connects to Event Bus platforms (Kafka, EventBridge, Pulsar)
to inventory streaming topics and consumer groups.

Modality: Streaming Consumer - passive subscription to events.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base import FabricAdapter, AdapterStatus, PlaneHealth, PlaneDrift
from ..parsers.eventbus_schema import parse_schema_registry_subjects
from ..db.semantic_edges import store_semantic_edges_batch, delete_semantic_edges_by_source

_log = logging.getLogger("aam.adapter.eventbus")


class EventBusAdapter(FabricAdapter):
    """
    Adapter for Event Bus Fabric Plane.

    Connects to event streaming platforms to:
    - Discover topics and consumer groups
    - Monitor consumer lag and throughput
    - Subscribe to event streams (read-only)
    - Self-heal consumer issues (restart, rebalance)

    Supported vendors: Kafka, AWS EventBridge, Pulsar, Azure Event Hubs
    """

    SUPPORTED_VENDORS = ["kafka", "eventbridge", "pulsar", "azure_eventhubs"]

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._vendor = config.get("vendor", "kafka").lower()
        self._consumer_group = config.get("consumer_group", "aam-observer")
        self._topics_discovered: List[Dict] = []
        self._current_lag: int = 0

    @property
    def plane_type(self) -> str:
        return "EVENT_BUS"

    @property
    def plane_vendor(self) -> str:
        return self._vendor

    async def connect(self) -> bool:
        """Connect to Event Bus cluster."""
        raise NotImplementedError(
            f"EventBusAdapter.connect() not implemented for vendor '{self._vendor}'. "
            "Implement consumer connection before calling connect()."
        )

    async def disconnect(self) -> bool:
        """Disconnect from Event Bus (graceful consumer shutdown)"""
        self._status = AdapterStatus.DISCONNECTED
        return True

    async def check_health(self) -> PlaneHealth:
        """Check Event Bus health."""
        raise NotImplementedError(
            f"EventBusAdapter.check_health() not implemented for vendor '{self._vendor}'."
        )

    async def discover_pipes(self) -> List[Dict[str, Any]]:
        """Discover topics and streams from Event Bus."""
        raise NotImplementedError(
            f"EventBusAdapter.discover_pipes() not implemented for vendor '{self._vendor}'."
        )

    async def self_heal(self, drift: PlaneDrift) -> bool:
        """Self-heal Event Bus connection issues."""
        raise NotImplementedError(
            f"EventBusAdapter.self_heal() not implemented for vendor '{self._vendor}'. "
            f"Drift type: {drift.drift_type}"
        )

    def extract_semantic_edges(
        self, subjects: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract field-level semantic edges from schema registry subjects.

        For each subject:
        1. Parse the schema (Avro/JSON/Protobuf) to extract field definitions
        2. Delete any previously-stored edges for this subject (idempotent)
        3. Batch-insert new edges

        Args:
            subjects: List of schema registry subject dicts

        Returns:
            All extracted SemanticEdge dicts (already persisted)
        """
        all_edges: List[Dict[str, Any]] = []

        edges = parse_schema_registry_subjects(
            subjects, bus_vendor=self._vendor,
        )

        if not edges:
            _log.info("No schema registry edges extracted for %s", self._vendor)
            return all_edges

        # Group by extraction_source for idempotent upsert
        sources_seen: set[str] = set()
        for e in edges:
            src = e["extraction_source"]
            if src not in sources_seen:
                delete_semantic_edges_by_source(src)
                sources_seen.add(src)

        stored = store_semantic_edges_batch(edges)
        all_edges.extend(stored)
        _log.info(
            "Stored %d schema registry edges for %s (%d subjects)",
            len(stored), self._vendor, len(subjects),
        )
        return all_edges

    def apply_governance_policy(self, policy: Dict[str, Any]) -> bool:
        """Apply governance at Event Bus level."""
        raise NotImplementedError(
            f"EventBusAdapter.apply_governance_policy() not implemented for vendor '{self._vendor}'."
        )
