"""Tool Output Translator — MCP tool result JSON -> DeclaredPipe objects.

Translation rules from Blueprint WP-1:
  list_recipes  -> one DeclaredPipe per active recipe with external trigger
  list_processes -> one DeclaredPipe per active Boomi process (same shape)
  list_services -> one DeclaredPipe per service+route (API gateway)
  list_topics   -> one DeclaredPipe per topic with producer (event bus)
  list_tables   -> one DeclaredPipe per landing/staging table (warehouse)

Unknown tool types: log warning, skip. No silent fallback.

CRITICAL: the translator output is shape-identical regardless of vendor. The
shim normalizes vendor differences before output; the translator does not
branch on vendor name. That is what makes "same AAM code path across Workato
and Boomi" a real property of the system.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from .client import MCPToolResult

_log = logging.getLogger("aam.mcp.translator")


class TranslatorError(Exception):
    """Raised when a tool result cannot be translated."""


_KNOWN_TOOLS = {
    "list_recipes",
    "list_processes",
    "list_flows",
    "list_services",
    "list_topics",
    "list_tables",
}


def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat()


def _provenance(vendor: str, tool: str) -> dict[str, Any]:
    return {
        "discovered_by": f"mcp:{vendor}:{tool}",
        "discovered_at": _utcnow_iso(),
        "lineage_hints": [f"vendor:{vendor}", f"tool:{tool}"],
    }


class ToolOutputTranslator:
    """Translate one MCP tool result into a list of DeclaredPipe dicts."""

    def __init__(self, vendor: str):
        if not vendor or not vendor.strip():
            raise TranslatorError("ToolOutputTranslator requires non-empty vendor")
        self.vendor = vendor

    def translate(self, tool_name: str, result: MCPToolResult) -> list[dict[str, Any]]:
        if tool_name not in _KNOWN_TOOLS:
            _log.warning("translator: skipping unknown tool=%s vendor=%s", tool_name, self.vendor)
            return []
        items = self._extract_items(result)
        if not items:
            _log.warning("translator: tool=%s vendor=%s returned 0 items", tool_name, self.vendor)
            return []
        return [self._item_to_pipe(tool_name, item) for item in items]

    def _extract_items(self, result: MCPToolResult) -> list[dict[str, Any]]:
        """Pull items[] from the structured payload."""
        structured = result.structured or {}
        items = structured.get("items")
        if isinstance(items, list):
            return [i for i in items if isinstance(i, dict)]
        return []

    def _item_to_pipe(self, tool_name: str, item: dict[str, Any]) -> dict[str, Any]:
        """Build a DeclaredPipe dict. Shape matches app.models.DeclaredPipe."""
        pipe_id = str(item.get("id") or uuid.uuid4())
        display_name = str(item.get("name") or item.get("display_name") or f"{self.vendor}-{tool_name}-{pipe_id[:6]}")
        source_system = str(item.get("source_system") or self.vendor)
        target_system = item.get("target_system")
        modality = self._modality_for(tool_name, item)
        transport_kind = self._transport_for(tool_name, item)
        fabric_plane = self._plane_for(tool_name)
        endpoint_ref = dict(item.get("endpoint_ref") or {})
        if target_system and "target_system" not in endpoint_ref:
            endpoint_ref["target_system"] = target_system
        entity_scope = list(item.get("entity_scope") or [])
        identity_keys = list(item.get("identity_keys") or [])
        schema_fields = item.get("schema") or item.get("fields") or []
        schema_info = self._schema_info(schema_fields) if schema_fields else None

        pipe = {
            "pipe_id": pipe_id,
            "display_name": display_name,
            "fabric_plane": fabric_plane,
            "modality": modality,
            "source_system": source_system,
            "transport_kind": transport_kind,
            "endpoint_ref": endpoint_ref,
            "entity_scope": entity_scope,
            "identity_keys": identity_keys,
            "change_semantics": str(item.get("change_semantics") or "UNKNOWN"),
            "provenance": _provenance(self.vendor, tool_name),
            "owner_signals": [f"system:{source_system}", f"vendor:{self.vendor}"],
            "trust_labels": [f"source:mcp:{tool_name}"],
            "schema_info": schema_info,
            "freshness": item.get("freshness"),
            "access": None,
        }
        return pipe

    def _modality_for(self, tool_name: str, item: dict[str, Any]) -> str:
        explicit = item.get("modality")
        if isinstance(explicit, str) and explicit:
            return explicit
        if tool_name in {"list_recipes", "list_processes", "list_flows"}:
            return "DECLARED_INTERFACE"
        if tool_name == "list_topics":
            return "EVENT_STREAM"
        if tool_name == "list_tables":
            return "CDC_FEED"
        if tool_name == "list_services":
            return "DECLARED_INTERFACE"
        return "DECLARED_INTERFACE"

    def _transport_for(self, tool_name: str, item: dict[str, Any]) -> str:
        explicit = item.get("transport_kind")
        if isinstance(explicit, str) and explicit:
            return explicit
        if tool_name == "list_topics":
            return "EVENT_STREAM"
        if tool_name == "list_tables":
            return "BATCH"
        return "API"

    def _plane_for(self, tool_name: str) -> str:
        if tool_name in {"list_recipes", "list_processes", "list_flows"}:
            return "IPAAS"
        if tool_name == "list_services":
            return "API_GATEWAY"
        if tool_name == "list_topics":
            return "EVENT_BUS"
        if tool_name == "list_tables":
            return "DATA_WAREHOUSE"
        return "IPAAS"

    def _schema_info(self, fields: Any) -> dict[str, Any] | None:
        if not isinstance(fields, list) or not fields:
            return None
        normalized = []
        for f in fields:
            if isinstance(f, dict) and "name" in f:
                normalized.append({
                    "name": str(f["name"]),
                    "type": str(f.get("type", "string")),
                    "is_key": bool(f.get("is_key", False)),
                })
        if not normalized:
            return None
        names_concat = "|".join(sorted(n["name"] for n in normalized))
        schema_hash = uuid.uuid5(uuid.NAMESPACE_URL, names_concat).hex[:16]
        return {
            "schema_hash": schema_hash,
            "schema_ref": None,
            "schema_version": "inferred",
            "fields": normalized,
        }
