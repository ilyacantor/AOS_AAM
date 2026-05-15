"""Webhook receivers — Workato + Boomi inbound from Farm fabric sims (or vendor cloud).

Per WP12a':
  - Verify HMAC signature against per-vendor *_WEBHOOK_SECRET. Reject 401 on mismatch.
  - Parse the row payload, build TransportRecords.
  - Run each row through the WP3 record-level resolver (saas_subscription
    domain) so the 0.71 LinkedIn fuzzy case lands on the HITL queue.
  - Build provenance-complete triples via WP4 builder.
  - POST to DCL /api/dcl/ingest-triples (no direct PG write).

Sim vs real vendor is just a URL/cred swap. Same code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from ..ingest import dcl_push, mappings, resolver as resolver_mod, triples as triples_mod
from ..transport.http import TransportRecord

_log = logging.getLogger("aam.routers.webhooks")

router = APIRouter(tags=["webhooks"])


# ---------------------------------------------------------------------------
# Identity defaults — webhook payloads carry these by convention; if absent,
# fall back to env. Tenant must be a UUID; entity_id is a stable string.
# ---------------------------------------------------------------------------

def _tenant_id_from(payload: dict[str, Any]) -> str:
    tid = (payload.get("tenant_id") or os.environ.get("AOS_TENANT_ID") or "").strip()
    if not tid:
        raise HTTPException(status_code=422, detail="tenant_id missing (no payload field, no AOS_TENANT_ID env)")
    try:
        uuid.UUID(tid)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"tenant_id is not a valid UUID: {tid!r}")
    return tid


def _entity_id_from(payload: dict[str, Any]) -> str:
    eid = (payload.get("entity_id") or os.environ.get("AOS_ENTITY_ID") or "").strip()
    if not eid:
        raise HTTPException(
            status_code=422,
            detail="entity_id missing (no payload field, no AOS_ENTITY_ID env)",
        )
    return eid


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(
    *, body_bytes: bytes, header_value: str | None, secret_env: str, secret_default: str,
) -> None:
    secret = os.environ.get(secret_env, secret_default)
    if not header_value:
        raise HTTPException(status_code=401, detail="missing webhook signature header")
    expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header_value):
        raise HTTPException(status_code=401, detail="webhook signature mismatch")


# ---------------------------------------------------------------------------
# Resolver — process-lifetime singleton with one canonical registry.
# Saas-subscription is the only domain wired in this pass. Discovery on first
# sight; fuzzy match in [0.65, 0.90) lands on HITL.
# ---------------------------------------------------------------------------

_registry = resolver_mod.CanonicalRegistry()
_resolver = resolver_mod.RecordResolver(_registry)


def _resolve_for_domain(
    *,
    record_dict: dict[str, Any],
    domain: str,
    value_field: str,
    record_key_field: str,
    pipe_id: str,
    tenant_id: str,
    entity_id: str,
) -> dict[str, Any] | None:
    if not record_dict.get(value_field):
        return None
    result = _resolver.resolve(
        record_dict,
        domain=domain,
        pipe_id=pipe_id,
        tenant_id=tenant_id,
        entity_id=entity_id,
        value_field=value_field,
        record_key_field=record_key_field,
    )
    return {
        "canonical_id": result.canonical_id,
        "resolution_method": result.resolution_method,
        "resolution_confidence": result.resolution_confidence,
        "hitl_queue_id": result.hitl_queue_id,
        "audit": result.audit,
    }


# ---------------------------------------------------------------------------
# Webhook → ingest pipeline (shared by both vendor receivers)
# ---------------------------------------------------------------------------

_PIPE_NAMESPACE = uuid.UUID("a4ca3b9c-7d36-4dbb-90b3-9a5e9b3a8b21")  # WP12a' fabric-sim pipes


def _pipe_uuid(vendor: str, source_system: str, domain: str) -> str:
    """Deterministic UUID5 per (vendor, source_system, domain). Stable across
    runs so DCL idempotency on pipe_id continues to hold, and joins on
    semantic_triples.pipe_id are meaningful across ingest batches."""
    return str(uuid.uuid5(_PIPE_NAMESPACE, f"{vendor}::{source_system}::{domain}"))


def _build_pipe(*, vendor: str, source_system: str, domain: str, identity_keys: list[str]) -> dict[str, Any]:
    """Build a minimal pipe dict that get_mapping_for_pipe can resolve."""
    return {
        "id": _pipe_uuid(vendor, source_system, domain),
        "source_system": source_system,
        "provenance": {"lineage_hints": [f"vendor:{vendor}"]},
        "endpoint_ref": {"domain": domain},
        "identity_keys": identity_keys,
    }


def _ingest_rows(
    *,
    rows: list[dict[str, Any]],
    pipe: dict[str, Any],
    vendor: str,
    fabric_plane: str,
    source_system: str,
    tenant_id: str,
    entity_id: str,
    aam_inference_id: str,
    source_run_tag: str,
    resolve_value_field: str | None,
    resolve_record_key: str | None,
    resolve_domain: str | None,
) -> list[dict[str, Any]]:
    """Convert webhook rows to triples (resolver + builder), return triples."""
    field_mappings = mappings.get_mapping_for_pipe(pipe)
    all_triples: list[dict[str, Any]] = []
    for row in rows:
        identity_value = next(
            (str(row.get(k)) for k in pipe["identity_keys"] if row.get(k) is not None),
            "",
        )
        if not identity_value:
            raise HTTPException(
                status_code=422,
                detail=f"row missing identity field {pipe['identity_keys']!r}; row keys={list(row.keys())}",
            )
        record = TransportRecord(
            pipe_id=pipe["id"],
            record_key=identity_value,
            payload=dict(row),
            source_system=source_system,
            metadata={},
        )
        # Resolve when the row carries a value the resolver knows about.
        if resolve_value_field and resolve_domain and resolve_record_key:
            resolution = _resolve_for_domain(
                record_dict=row,
                domain=resolve_domain,
                value_field=resolve_value_field,
                record_key_field=resolve_record_key,
                pipe_id=pipe["id"],
                tenant_id=tenant_id,
                entity_id=entity_id,
            )
            if resolution:
                record.metadata["_resolution"] = resolution

        triples = triples_mod.build_triples(
            record,
            pipe=pipe,
            mappings=field_mappings,
            tenant_id=tenant_id,
            entity_id=entity_id,
            aam_inference_id=aam_inference_id,
            source_run_tag=f"{source_run_tag}::{record.record_key}",
            vendor=vendor,
        )
        # Stamp fabric_plane on every triple (DCL contract requires non-null).
        for t in triples:
            t["fabric_plane"] = fabric_plane
            t["fabric_product"] = vendor
        all_triples.extend(triples)
    return all_triples


# ---------------------------------------------------------------------------
# Workato receiver
# ---------------------------------------------------------------------------

@router.post("/api/aam/webhooks/workato")
async def workato_webhook(
    request: Request,
    x_workato_signature: str | None = Header(default=None, alias="x-workato-signature"),
):
    body_bytes = await request.body()
    _verify_signature(
        body_bytes=body_bytes,
        header_value=x_workato_signature,
        secret_env="WORKATO_WEBHOOK_SECRET",
        secret_default="sim-workato-secret",
    )
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"webhook body not JSON: {exc}")
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows must be a list")
    if not rows:
        return {"accepted": True, "rows": 0, "triples_pushed": 0}

    event_type = payload.get("event_type") or ""
    tenant_id = _tenant_id_from(payload)
    entity_id = _entity_id_from(payload)
    aam_inference_id = str(uuid.uuid4())
    source_run_tag = f"workato::{event_type}::{aam_inference_id[:8]}"

    if "vendor_master" in event_type:
        pipe = _build_pipe(
            vendor="workato", source_system="netsuite", domain="vendor",
            identity_keys=["vendor_id"],
        )
        all_triples = _ingest_rows(
            rows=rows, pipe=pipe, vendor="workato",
            fabric_plane="workato", source_system="NetSuite",
            tenant_id=tenant_id, entity_id=entity_id,
            aam_inference_id=aam_inference_id, source_run_tag=source_run_tag,
            resolve_value_field="vendor_name",
            resolve_record_key="vendor_id",
            resolve_domain="saas_subscription",
        )
    elif "ap_invoices" in event_type:
        pipe = _build_pipe(
            vendor="workato", source_system="netsuite", domain="ap_invoice",
            identity_keys=["bill_no"],
        )
        all_triples = _ingest_rows(
            rows=rows, pipe=pipe, vendor="workato",
            fabric_plane="workato", source_system="NetSuite",
            tenant_id=tenant_id, entity_id=entity_id,
            aam_inference_id=aam_inference_id, source_run_tag=source_run_tag,
            resolve_value_field=None, resolve_record_key=None, resolve_domain=None,
        )
    else:
        raise HTTPException(status_code=400, detail=f"unknown event_type: {event_type!r}")

    pushed = dcl_push.push_triples(
        triples=all_triples, tenant_id=tenant_id, entity_id=entity_id,
        source_run_tag=source_run_tag,
    )
    _log.info(
        "workato webhook accepted event=%s rows=%d triples=%d dcl_ingest_id=%s",
        event_type, len(rows), len(all_triples), pushed.get("dcl_ingest_id"),
    )
    return {
        "accepted": True,
        "rows": len(rows),
        "triples_pushed": len(all_triples),
        "aam_inference_id": aam_inference_id,
        "dcl_ingest_id": pushed.get("dcl_ingest_id"),
        "concept_summary": pushed.get("concept_summary"),
    }


# ---------------------------------------------------------------------------
# Boomi receiver
# ---------------------------------------------------------------------------

@router.post("/api/aam/webhooks/boomi")
async def boomi_webhook(
    request: Request,
    x_boomi_signature: str | None = Header(default=None, alias="x-boomi-signature"),
):
    body_bytes = await request.body()
    _verify_signature(
        body_bytes=body_bytes,
        header_value=x_boomi_signature,
        secret_env="BOOMI_WEBHOOK_SECRET",
        secret_default="sim-boomi-secret",
    )
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"webhook body not JSON: {exc}")
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="payload.rows must be a list")
    if not rows:
        return {"accepted": True, "rows": 0, "triples_pushed": 0}

    event_type = payload.get("event_type") or ""
    tenant_id = _tenant_id_from(payload)
    entity_id = _entity_id_from(payload)
    aam_inference_id = str(uuid.uuid4())
    source_run_tag = f"boomi::{event_type}::{aam_inference_id[:8]}"

    if "okta_apps" in event_type:
        pipe = _build_pipe(
            vendor="boomi", source_system="okta", domain="saas_app",
            identity_keys=["id"],
        )
        all_triples = _ingest_rows(
            rows=rows, pipe=pipe, vendor="boomi",
            fabric_plane="boomi", source_system="Okta",
            tenant_id=tenant_id, entity_id=entity_id,
            aam_inference_id=aam_inference_id, source_run_tag=source_run_tag,
            resolve_value_field="label",
            resolve_record_key="id",
            resolve_domain="saas_subscription",
        )
    elif "okta_users" in event_type:
        pipe = _build_pipe(
            vendor="boomi", source_system="okta", domain="user",
            identity_keys=["id"],
        )
        all_triples = _ingest_rows(
            rows=rows, pipe=pipe, vendor="boomi",
            fabric_plane="boomi", source_system="Okta",
            tenant_id=tenant_id, entity_id=entity_id,
            aam_inference_id=aam_inference_id, source_run_tag=source_run_tag,
            resolve_value_field=None, resolve_record_key=None, resolve_domain=None,
        )
    elif "okta_assignments" in event_type:
        pipe = _build_pipe(
            vendor="boomi", source_system="okta", domain="assignment",
            identity_keys=["id"],
        )
        all_triples = _ingest_rows(
            rows=rows, pipe=pipe, vendor="boomi",
            fabric_plane="boomi", source_system="Okta",
            tenant_id=tenant_id, entity_id=entity_id,
            aam_inference_id=aam_inference_id, source_run_tag=source_run_tag,
            resolve_value_field=None, resolve_record_key=None, resolve_domain=None,
        )
    else:
        raise HTTPException(status_code=400, detail=f"unknown event_type: {event_type!r}")

    pushed = dcl_push.push_triples(
        triples=all_triples, tenant_id=tenant_id, entity_id=entity_id,
        source_run_tag=source_run_tag,
    )
    _log.info(
        "boomi webhook accepted event=%s rows=%d triples=%d dcl_ingest_id=%s",
        event_type, len(rows), len(all_triples), pushed.get("dcl_ingest_id"),
    )
    return {
        "accepted": True,
        "rows": len(rows),
        "triples_pushed": len(all_triples),
        "aam_inference_id": aam_inference_id,
        "dcl_ingest_id": pushed.get("dcl_ingest_id"),
        "concept_summary": pushed.get("concept_summary"),
    }
