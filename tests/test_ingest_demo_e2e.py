"""End-to-end test: ipaas_stub -> factory -> discovery -> HTTPTransport ->
flow controller -> triple builder. Same assertion suite for Workato and Boomi.

This is the regression artifact for the "no vendor branching" property of the
demo. If the test passes for one vendor and not the other, vendor branching
has crept back into the downstream code path.

Triple PG write is exercised in test_ingest_demo_pg.py (uses real Supabase).
This module uses write=False to keep the unit suite hermetic.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from app.ingest.flow_controller import FlowController
from app.ingest.triples import ingest_records
from app.mcp.client import MCPClient
from app.mcp.shims import BoomiShim, WorkatoShim
from app.mcp.translator import ToolOutputTranslator
from app.transport.http import HTTPTransport
from tests.fixtures.harness.ipaas_stub import create_stub_app


@pytest.fixture(scope="module")
def stub_client() -> TestClient:
    return TestClient(create_stub_app("healthy"))


@pytest.fixture
def stub_request_fn(stub_client):
    def fn(method, url, headers, body):
        parsed = urlparse(url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        if body is None:
            return stub_client.request(method, path, headers=dict(headers)).json()
        return stub_client.request(method, path, headers=dict(headers), content=body).json()
    return fn


VENDORS = [
    ("Workato", WorkatoShim, "list_recipes", 2, 3),  # 2 pipes, 3 records total
    ("Boomi", BoomiShim, "list_processes", 1, 2),   # 1 pipe, 2 records
]


@pytest.mark.parametrize("vendor,shim_cls,tool,expected_pipes,expected_records", VENDORS)
def test_end_to_end_per_vendor(stub_request_fn, vendor, shim_cls, tool, expected_pipes, expected_records):
    """Same assertion code, different vendor at the seam. Proves no branching."""
    shim = shim_cls(endpoint="http://stub", auth={"api_key": "demo"}, request_fn=stub_request_fn)
    client = MCPClient(vendor=vendor, shim=shim)
    tools = client.list_tools()
    assert [t.name for t in tools] == [tool]

    result = client.invoke_tool(tool)
    pipes = ToolOutputTranslator(vendor=vendor).translate(tool, result)
    assert len(pipes) == expected_pipes
    # Provenance evidence: every pipe lineage_hint includes the vendor.
    for p in pipes:
        assert f"vendor:{vendor}" in p["provenance"]["lineage_hints"]
        assert p["fabric_plane"] == "IPAAS"
        assert p["modality"] == "DECLARED_INTERFACE"
        assert p["schema_info"]["fields"], f"pipe {p['display_name']} missing schema_info.fields"

    transport = HTTPTransport(
        base_url="http://stub", auth_method="api_key",
        auth_credentials={"api_key": "demo"}, request_fn=stub_request_fn,
    )

    total_records = 0
    total_triples = 0
    for pipe in pipes:
        records = transport.fetch_records(pipe_id=pipe["pipe_id"], path=pipe["endpoint_ref"]["path"])
        total_records += len(records)
        fc = FlowController(batch_size=max(1, len(records)))
        fc.submit_many(records)
        fc.finalize()
        result_ingest = ingest_records(
            records,
            pipe=pipe,
            tenant_id="00000000-0000-0000-0000-000000000001",
            entity_id="test-entity",
            vendor=vendor,
            write=False,
        )
        total_triples += result_ingest.triples_built
        # Every built triple carries all 6 provenance fields the demo requires.
        for r in records:
            built = ingest_records(
                [r], pipe=pipe, tenant_id="00000000-0000-0000-0000-000000000001",
                entity_id="test-entity", vendor=vendor, write=False,
            )
            # Re-build via build_triples to inspect the dict shape
            from app.ingest.triples import build_triples
            from app.ingest.mappings import get_mapping_for_pipe
            ts = build_triples(
                r, pipe=pipe, mappings=get_mapping_for_pipe(pipe),
                tenant_id="00000000-0000-0000-0000-000000000001",
                entity_id="test-entity",
                aam_inference_id=result_ingest.aam_inference_id,
                source_run_tag=result_ingest.source_run_tag,
                vendor=vendor,
            )
            for t in ts:
                assert t["source_system"], "triple missing source_system"
                assert t["source_field"], "triple missing source_field"
                assert t["pipe_id"], "triple missing pipe_id"
                assert t["aam_inference_id"], "triple missing aam_inference_id (namespaced run identifier per I1)"
                assert t["confidence_score"] > 0, "triple missing confidence_score"
                assert t["source_run_tag"].startswith("aam_ingest_"), "triple missing timestamp-bearing source_run_tag"
                assert t["source_table"] == f"aam_via:{vendor}", "vendor not recorded in source_table"

    assert total_records == expected_records, f"{vendor} expected {expected_records} records got {total_records}"
    assert total_triples > 0, f"{vendor} produced no triples"


def test_unsupported_vendor_returns_400_with_readable_message():
    """Paired negative test (B11): an unknown vendor must surface a readable 400."""
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/aam/ingest/demo",
        json={"vendors": ["salesforce"], "tenant_id": "00000000-0000-0000-0000-000000000001", "entity_id": "test-entity"},
    )
    assert res.status_code == 400
    body = res.json()
    assert "unsupported vendor" in str(body.get("detail", "")).lower()


def test_both_vendors_run_through_same_code_path(stub_request_fn):
    """The single most important assertion: identical code drives both vendors."""
    results: dict[str, dict] = {}
    for vendor, shim_cls, tool in [
        ("Workato", WorkatoShim, "list_recipes"),
        ("Boomi", BoomiShim, "list_processes"),
    ]:
        shim = shim_cls(endpoint="http://stub", auth={"api_key": "demo"}, request_fn=stub_request_fn)
        client = MCPClient(vendor=vendor, shim=shim)
        result = client.invoke_tool(tool)
        pipes = ToolOutputTranslator(vendor=vendor).translate(tool, result)
        transport = HTTPTransport(
            base_url="http://stub", auth_credentials={"api_key": "demo"}, request_fn=stub_request_fn,
        )
        triples_count = 0
        for p in pipes:
            recs = transport.fetch_records(pipe_id=p["pipe_id"], path=p["endpoint_ref"]["path"])
            ir = ingest_records(
                recs, pipe=p, tenant_id="00000000-0000-0000-0000-000000000001",
                entity_id="test-entity", vendor=vendor, write=False,
            )
            triples_count += ir.triples_built
        results[vendor] = {"pipes": len(pipes), "triples": triples_count}
    # Both vendors must produce > 0 pipes and > 0 triples.
    assert results["Workato"]["pipes"] > 0 and results["Workato"]["triples"] > 0
    assert results["Boomi"]["pipes"] > 0 and results["Boomi"]["triples"] > 0
