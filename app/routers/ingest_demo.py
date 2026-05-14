"""Demo orchestrator endpoint.

POST /api/aam/ingest/demo
  body: {"vendors": ["workato", "boomi"], "tenant_id": "...", "entity_id": "..."}

Runs the WP-1 + WP-2 + WP-6 + WP-8 chain end-to-end through ipaas_stub:
  factory -> discovery -> DeclaredPipes -> HTTPTransport.fetch_records ->
  FlowController -> triple builder -> semantic_triples.

No vendor branching downstream of the factory. The same orchestrator loop
runs Workato and Boomi.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..adapters.factory import get_mcp_pair_for_vendor, supported_vendors
from ..db import supabase_client as sb
from ..ingest.flow_controller import FlowController
from ..ingest.resolver import CanonicalRegistry, RecordResolver, ResolutionResult
from ..ingest.triples import ingest_records
from ..mcp.translator import ToolOutputTranslator
from ..transport.http import HTTPTransport, TransportRecord

router = APIRouter(tags=["ingest_demo"])
_log = logging.getLogger("aam.routers.ingest_demo")


class IngestDemoRequest(BaseModel):
    vendors: list[str] = Field(default_factory=lambda: ["workato", "boomi"])
    tenant_id: str | None = None
    entity_id: str | None = None


class VendorResult(BaseModel):
    vendor: str
    pipes_discovered: int
    records_fetched: int
    triples_written: int
    pipe_ids: list[str] = Field(default_factory=list)


class IngestDemoResponse(BaseModel):
    aam_inference_id: str
    tenant_id: str
    entity_id: str
    results: list[VendorResult]
    total_pipes: int
    total_records: int
    total_triples: int
    resolver_summary: dict[str, int] = Field(default_factory=dict)


def _resolve_identity(req: IngestDemoRequest) -> tuple[str, str]:
    """Return (tenant_id, entity_id). 422 if neither request, handoff, nor env supplies them."""
    tenant_id = (req.tenant_id or "").strip()
    entity_id = (req.entity_id or "").strip()
    if tenant_id and entity_id:
        return tenant_id, entity_id
    handoff_rows = sb.select("aod_handoff_log", order="processed_at.desc", limit=1)
    handoff = handoff_rows[0] if handoff_rows else {}
    if not tenant_id:
        tenant_id = (handoff.get("tenant_id") or os.environ.get("AOS_TENANT_ID") or "").strip()
    if not entity_id:
        entity_id = (
            handoff.get("entity_id")
            or handoff.get("snapshot_name")
            or os.environ.get("AOS_DEMO_ENTITY_ID")
            or ""
        ).strip()
    if not tenant_id or not entity_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"ingest_demo: identity missing. tenant_id={tenant_id!r} entity_id={entity_id!r}. "
                "Provide in request body, or run AOD handoff, or set AOS_TENANT_ID + AOS_DEMO_ENTITY_ID."
            ),
        )
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"ingest_demo: tenant_id must be a UUID, got {tenant_id!r}")
    return tenant_id, entity_id


def _primary_tool_for(vendor: str, tools: list) -> str:
    """Pick the discovery tool to invoke for a vendor.

    No vendor branching: we just take the first tool the vendor advertises.
    Both Workato (list_recipes) and Boomi (list_processes) expose exactly one
    tool from their shim, so this is deterministic without an if-vendor.
    """
    if not tools:
        raise HTTPException(status_code=502, detail=f"ingest_demo: vendor={vendor} returned no discovery tools")
    return tools[0].name


@router.get("/api/aam/ingest/demo/vendors")
async def list_supported_vendors() -> dict[str, Any]:
    return {"vendors": supported_vendors(), "harness_mode": os.environ.get("HARNESS_MODE", "live")}


@router.post("/api/aam/ingest/demo", response_model=IngestDemoResponse)
async def run_ingest_demo(req: IngestDemoRequest) -> IngestDemoResponse:
    tenant_id, entity_id = _resolve_identity(req)
    aam_inference_id = str(uuid.uuid4())
    results: list[VendorResult] = []
    total_pipes = 0
    total_records = 0
    total_triples = 0

    # Phase A: fetch per (vendor, pipe).
    all_vendor_runs: list[tuple[str, list[tuple[dict, list[TransportRecord]]]]] = []
    for vendor in req.vendors:
        try:
            discovery, transport = get_mcp_pair_for_vendor(vendor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        tools = discovery.list_tools()
        tool_name = _primary_tool_for(vendor, tools)
        result = discovery.invoke_tool(tool_name)
        translator = ToolOutputTranslator(vendor=vendor)
        pipes = translator.translate(tool_name, result)
        if not pipes:
            raise HTTPException(
                status_code=502,
                detail=f"ingest_demo: vendor={vendor} discovery returned 0 pipes (tool={tool_name})",
            )

        records_collected: list[tuple[dict, list[TransportRecord]]] = []
        for pipe in pipes:
            records = _fetch_records(transport, pipe)
            records_collected.append((pipe, records))
        all_vendor_runs.append((vendor, records_collected))

    # Phase B: run resolver. SaaS-subscription identity is the NetSuite vendor
    # (domain=vendor) <-> Okta SaaS app (domain=saas_app) join. The resolver
    # seeds its registry from vendor records first, then resolves Okta app
    # records against it. Other domains (ap_invoice, user, assignment) pass
    # through unresolved — they don't need identity unification for the demo.
    registry = CanonicalRegistry()
    resolver = RecordResolver(registry)
    resolver_summary = {
        "exact": 0, "alias": 0, "pattern": 0, "fuzzy": 0,
        "hitl_pending": 0, "discovery": 0, "rejected": 0,
    }

    for vendor, vendor_pipes in all_vendor_runs:
        for pipe, records in vendor_pipes:
            domain = _pipe_domain(pipe)
            if domain not in ("vendor", "saas_app"):
                continue
            value_field = "vendor_name" if domain == "vendor" else "label"
            record_key_field = "vendor_id" if domain == "vendor" else "id"
            pipe_id_str = str(pipe.get("pipe_id") or "")
            for record in records:
                payload = record.payload or {}
                if value_field not in payload:
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            f"ingest_demo: pipe {pipe_id_str} ({pipe.get('display_name')}) "
                            f"record_key={record.record_key} missing identity field {value_field!r} — "
                            f"present keys: {list(payload.keys())}"
                        ),
                    )
                try:
                    res: ResolutionResult = resolver.resolve(
                        payload,
                        domain="saas_subscription",
                        pipe_id=pipe_id_str,
                        tenant_id=tenant_id,
                        entity_id=entity_id,
                        value_field=value_field,
                        record_key_field=record_key_field,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                # Attach to the record metadata so the triple builder can
                # propagate canonical_id / resolution_method / confidence.
                record.metadata = dict(record.metadata or {})
                record.metadata["_resolution"] = {
                    "canonical_id": res.canonical_id,
                    "resolution_method": res.resolution_method,
                    "resolution_confidence": res.resolution_confidence,
                    "hitl_queue_id": res.hitl_queue_id,
                }
                resolver_summary[res.resolution_method] = resolver_summary.get(
                    res.resolution_method, 0) + 1

    # Phase C: build + write triples (records now carry _resolution metadata).
    for vendor, vendor_pipes in all_vendor_runs:
        vendor_records_count = 0
        vendor_triples = 0
        for pipe, records in vendor_pipes:
            vendor_records_count += len(records)
            # Cap batch_size at 500 — larger pipes (assignment telemetry can be
            # 20k+ records) must stay within FlowController's max_buffer.
            controller = FlowController(batch_size=min(500, max(1, len(records) or 1)))
            controller.submit_many(records)
            controller.finalize()
            ingest_result = ingest_records(
                records,
                pipe=pipe,
                tenant_id=tenant_id,
                entity_id=entity_id,
                vendor=vendor,
                aam_inference_id=aam_inference_id,
            )
            vendor_triples += ingest_result.triples_written

        total_pipes += len(vendor_pipes)
        total_records += vendor_records_count
        total_triples += vendor_triples
        results.append(VendorResult(
            vendor=vendor,
            pipes_discovered=len(vendor_pipes),
            records_fetched=vendor_records_count,
            triples_written=vendor_triples,
            pipe_ids=[p["pipe_id"] for p, _ in vendor_pipes],
        ))

    return IngestDemoResponse(
        aam_inference_id=aam_inference_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
        results=results,
        total_pipes=total_pipes,
        total_records=total_records,
        total_triples=total_triples,
        resolver_summary=resolver_summary,
    )


def _pipe_domain(pipe: dict[str, Any]) -> str:
    """Extract domain tag from pipe.endpoint_ref. Empty string when absent."""
    ref = pipe.get("endpoint_ref") or {}
    if isinstance(ref, dict):
        return str(ref.get("domain") or "")
    return ""


def _fetch_records(transport: HTTPTransport, pipe: dict[str, Any]) -> list[TransportRecord]:
    """Pull the records for one pipe via its endpoint_ref.path. Loud-fail on missing."""
    endpoint_ref = pipe.get("endpoint_ref") or {}
    path = endpoint_ref.get("path")
    if not path:
        raise HTTPException(
            status_code=502,
            detail=f"ingest_demo: pipe {pipe.get('pipe_id')} ({pipe.get('display_name')}) missing endpoint_ref.path",
        )
    key_fields = list(pipe.get("identity_keys") or [])
    return transport.fetch_records(pipe_id=pipe["pipe_id"], path=path, key_fields=key_fields)
