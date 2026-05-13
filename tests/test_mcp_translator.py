"""Unit tests for the MCP tool output translator.

The translator is the seam where vendor differences must disappear. Same
input shape (MCP result with structured.items[]) -> identical DeclaredPipe
shape regardless of vendor.
"""

from __future__ import annotations

import pytest

from app.mcp.client import MCPToolResult
from app.mcp.translator import ToolOutputTranslator


def _make_result(items: list[dict]) -> MCPToolResult:
    return MCPToolResult.from_dict({
        "content": [],
        "isError": False,
        "structured": {"items": items},
    })


def test_translator_list_recipes_produces_one_pipe_per_item():
    result = _make_result([
        {
            "id": "wk-1",
            "name": "SF -> NS",
            "source_system": "Salesforce",
            "target_system": "NetSuite",
            "schema": [{"name": "account_id", "type": "string", "is_key": True}],
            "identity_keys": ["account_id"],
            "entity_scope": ["Salesforce"],
        }
    ])
    pipes = ToolOutputTranslator(vendor="Workato").translate("list_recipes", result)
    assert len(pipes) == 1
    p = pipes[0]
    assert p["pipe_id"] == "wk-1"
    assert p["source_system"] == "Salesforce"
    assert p["fabric_plane"] == "IPAAS"
    assert p["modality"] == "DECLARED_INTERFACE"
    assert p["identity_keys"] == ["account_id"]
    assert "vendor:Workato" in p["provenance"]["lineage_hints"]
    assert p["schema_info"]["fields"][0]["name"] == "account_id"


def test_translator_list_processes_for_boomi_same_shape():
    result = _make_result([
        {
            "id": "bm-1",
            "name": "SN -> SF",
            "source_system": "ServiceNow",
            "target_system": "Salesforce",
            "schema": [{"name": "ticket_id", "type": "string", "is_key": True}],
            "identity_keys": ["ticket_id"],
            "entity_scope": ["ServiceNow"],
        }
    ])
    pipes = ToolOutputTranslator(vendor="Boomi").translate("list_processes", result)
    assert len(pipes) == 1
    p = pipes[0]
    # Same keys as Workato pipe — proves vendor-agnostic output shape.
    expected_keys = {
        "pipe_id", "display_name", "fabric_plane", "modality", "source_system",
        "transport_kind", "endpoint_ref", "entity_scope", "identity_keys",
        "change_semantics", "provenance", "owner_signals", "trust_labels",
        "schema_info", "freshness", "access",
    }
    assert expected_keys.issubset(set(p.keys()))
    assert "vendor:Boomi" in p["provenance"]["lineage_hints"]


def test_translator_skips_unknown_tool_loudly():
    pipes = ToolOutputTranslator(vendor="Workato").translate("invent_things", _make_result([{"id": "x"}]))
    assert pipes == []


def test_translator_empty_items_returns_empty_no_crash():
    pipes = ToolOutputTranslator(vendor="Workato").translate("list_recipes", _make_result([]))
    assert pipes == []


def test_translator_rejects_empty_vendor():
    with pytest.raises(Exception):
        ToolOutputTranslator(vendor="")
