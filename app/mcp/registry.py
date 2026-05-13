"""MCP Connection Registry — per-tenant active MCP connections.

In-memory for the demo. Production tracks: vendor, endpoint, auth_type,
connection_status, last_discovery_at. CRUD + health_check operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RegistryEntry:
    tenant_id: str
    vendor: str
    endpoint: str
    auth_type: str
    connection_status: str = "disconnected"
    last_discovery_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    def key(self) -> tuple[str, str]:
        return (self.tenant_id, self.vendor)


class MCPRegistry:
    """In-memory registry of MCP connections, keyed by (tenant_id, vendor)."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], RegistryEntry] = {}

    def upsert(self, entry: RegistryEntry) -> RegistryEntry:
        if not entry.tenant_id or not entry.vendor:
            raise ValueError("RegistryEntry requires non-empty tenant_id and vendor")
        self._entries[entry.key()] = entry
        return entry

    def get(self, tenant_id: str, vendor: str) -> Optional[RegistryEntry]:
        return self._entries.get((tenant_id, vendor))

    def list_for_tenant(self, tenant_id: str) -> list[RegistryEntry]:
        return [e for (t, _), e in self._entries.items() if t == tenant_id]

    def list_all(self) -> list[RegistryEntry]:
        return list(self._entries.values())

    def remove(self, tenant_id: str, vendor: str) -> bool:
        key = (tenant_id, vendor)
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def mark_status(self, tenant_id: str, vendor: str, status: str) -> RegistryEntry:
        entry = self.get(tenant_id, vendor)
        if entry is None:
            raise KeyError(f"registry: no entry for tenant={tenant_id} vendor={vendor}")
        entry.connection_status = status
        if status == "connected":
            entry.last_discovery_at = datetime.utcnow()
        return entry
