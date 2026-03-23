"""
Operating Mode Detection — determines AAM's current operating context.

Three modes:
  SYNTHETIC       — no live MCP connections, all data from Farm. Default.
  PRODUCTION_SE   — at least one live MCP connection, single entity.
  PRODUCTION_ME   — live MCP connections, multiple entities (convergence).

This is the single gating function. All control surface gating and UI
conditional rendering reference get_operating_mode(). The detection is
data-driven, not config-driven.

Forward compat: when the MCP client lands and the connection registry
has active entries, get_operating_mode() will return PRODUCTION_SE
without code changes.
"""
import logging
from enum import Enum

_log = logging.getLogger("aam.operating_mode")


class OperatingMode(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    PRODUCTION_SE = "PRODUCTION_SE"
    PRODUCTION_ME = "PRODUCTION_ME"


# MCP connection registry — populated by the MCP client when it lands.
# Each entry: {"connection_id": str, "vendor": str, "active": bool, "validated": bool}
_mcp_connections: list[dict] = []


def register_mcp_connection(connection: dict) -> None:
    """Register an MCP connection. Called by the MCP client on connect."""
    _mcp_connections.append(connection)
    _log.info(
        "MCP connection registered: vendor=%s active=%s",
        connection.get("vendor"), connection.get("active"),
    )


def remove_mcp_connection(connection_id: str) -> None:
    """Remove an MCP connection from the registry."""
    global _mcp_connections
    _mcp_connections = [c for c in _mcp_connections if c.get("connection_id") != connection_id]


def _count_entities_in_triple_store() -> int:
    """Count distinct entity_ids in the PG triple store with source_system='AAM'.

    Only called when active MCP connections exist. PG query failures propagate —
    the caller must know if entity count is unreliable.
    """
    from ..db import supabase_client as sb
    from psycopg2 import sql as psql

    query = psql.SQL(
        "SELECT COUNT(DISTINCT {}) FROM {} WHERE {} = %s"
    ).format(
        sb._ident("entity_id"),
        sb._ident("semantic_triples"),
        sb._ident("source_system"),
    )
    rows = sb._execute_composed(query, ("AAM",))
    if rows:
        return rows[0]["count"]
    return 0


def get_operating_mode() -> OperatingMode:
    """Detect the current operating mode based on MCP connections and entity count.

    Returns SYNTHETIC when no active MCP connections exist (current state).
    Returns PRODUCTION_SE when live connections exist with a single entity.
    Returns PRODUCTION_ME when live connections exist with multiple entities.
    """
    active_connections = [
        c for c in _mcp_connections
        if c.get("active") and c.get("validated")
    ]

    if not active_connections:
        return OperatingMode.SYNTHETIC

    entity_count = _count_entities_in_triple_store()

    if entity_count > 1:
        return OperatingMode.PRODUCTION_ME

    return OperatingMode.PRODUCTION_SE
