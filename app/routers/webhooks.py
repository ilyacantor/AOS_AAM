"""Webhook receivers — Workato + Boomi inbound from Farm fabric sims (or vendor cloud).

Per WP12a':
  - Verify HMAC signature against per-vendor *_WEBHOOK_SECRET. Reject 401 on mismatch.
  - Parse the row payload, build TransportRecords.
  - Run each row through the WP3 record-level resolver (saas_subscription
    domain) so the LinkedIn fuzzy case lands on the HITL queue.
  - Build provenance-complete triples via WP4 builder.
  - POST to DCL /api/dcl/ingest-triples (no direct PG write).

Per WP12b:
  - Every receipt is logged to fabric_webhook_log (vendor + signature result
    + payload), then finalized when the DCL push completes (success or
    failure). The /aam/fabrics UI reads this table.
  - The same ingest path is reused by /api/aam/manual-entry (source='manual').

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
from pydantic import BaseModel, Field

from ..db import fabric_webhook_log
from ..ingest import dcl_push, mappings, resolver as resolver_mod, triples as triples_mod
from ..transport.http import TransportRecord

_log = logging.getLogger("aam.routers.webhooks")

router = APIRouter(tags=["webhooks"])


# ---------------------------------------------------------------------------
# Identity defaults
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


def _vendor_tenant_entity_id(vendor: str) -> str:
    """Read the per-vendor tenant_entity_id from env.

    Per-adapter binding (not process-wide AOS_ENTITY_ID). AOS is multi-tenant;
    each fabric adapter carries its own tenant configuration so a single
    AAM process can serve multiple tenants without a global default.

    Loud-fail if unset — no fallback to a global, no hardcoded default.
    """
    env_name = f"{vendor.upper()}_TENANT_ENTITY_ID"
    eid = (os.environ.get(env_name) or "").strip()
    if not eid:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{env_name} is not set; the {vendor} webhook receiver "
                f"cannot stamp tenant identity on incoming triples."
            ),
        )
    return eid


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _expected_sig(*, body_bytes: bytes, secret_env: str, secret_default: str) -> str:
    secret = os.environ.get(secret_env, secret_default)
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def _verify_signature(
    *, body_bytes: bytes, header_value: str | None, secret_env: str, secret_default: str,
) -> bool:
    if not header_value:
        return False
    return hmac.compare_digest(
        _expected_sig(body_bytes=body_bytes, secret_env=secret_env, secret_default=secret_default),
        header_value,
    )


# ---------------------------------------------------------------------------
# Resolver — process-lifetime singleton
# ---------------------------------------------------------------------------

_registry = resolver_mod.CanonicalRegistry()
_resolver = resolver_mod.RecordResolver(_registry)


def _resolve_for_domain(
    *, record_dict, domain, value_field, record_key_field,
    pipe_id, tenant_id, entity_id,
):
    if not record_dict.get(value_field):
        return None
    result = _resolver.resolve(
        record_dict, domain=domain, pipe_id=pipe_id,
        tenant_id=tenant_id, entity_id=entity_id,
        value_field=value_field, record_key_field=record_key_field,
    )
    return {
        "canonical_id": result.canonical_id,
        "resolution_method": result.resolution_method,
        "resolution_confidence": result.resolution_confidence,
        "hitl_queue_id": result.hitl_queue_id,
        "audit": result.audit,
    }


# ---------------------------------------------------------------------------
# Pipe construction (deterministic UUID5 keeps DCL pipe_id idempotent across runs)
# ---------------------------------------------------------------------------

_PIPE_NAMESPACE = uuid.UUID("a4ca3b9c-7d36-4dbb-90b3-9a5e9b3a8b21")


def _pipe_uuid(vendor: str, source_system: str, domain: str) -> str:
    return str(uuid.uuid5(_PIPE_NAMESPACE, f"{vendor}::{source_system}::{domain}"))


def _build_pipe(*, vendor, source_system, domain, identity_keys):
    return {
        "id": _pipe_uuid(vendor, source_system, domain),
        "source_system": source_system,
        "provenance": {"lineage_hints": [f"vendor:{vendor}"]},
        "endpoint_ref": {"domain": domain},
        "identity_keys": identity_keys,
    }


# ---------------------------------------------------------------------------
# Vendor → (event_type substring) → pipe spec
#
# When a new fabric vendor is added (e.g., MuleSoft), extend this table.
# ---------------------------------------------------------------------------

# Each entry: (source_system_display, source_system_slug, fabric_plane,
#              domain, identity_keys, resolve_spec_or_None)
# resolve_spec = (value_field, record_key_field, resolve_domain)
_DISPATCH: dict[str, dict[str, tuple]] = {
    "workato": {
        # WS-2 customer-side path. resolve_spec runs WP3 against the
        # "company_name" field on the "customer" domain — that's where the
        # Slide 8 Acme demo case lands a ~0.96 fuzzy match against the
        # Sage Intacct counterpart.
        "customers": (
            "NetSuite", "netsuite", "workato", "customer", ["customer_id"],
            ("company_name", "customer_id", "customer"),
        ),
        "chart": (
            "NetSuite", "netsuite", "workato", "chart_of_account", ["account_number"], None,
        ),
        "invoices": (
            "NetSuite", "netsuite", "workato", "invoice", ["invoice_number"], None,
        ),
        "vendor_master": (
            "NetSuite", "netsuite", "workato", "vendor", ["vendor_id"],
            ("vendor_name", "vendor_id", "saas_subscription"),
        ),
        "ap_invoices": (
            "NetSuite", "netsuite", "workato", "ap_invoice", ["bill_no"], None,
        ),
    },
    "boomi": {
        # WS-2: Boomi is bound to Sage Intacct (was Okta in WS-1). The five
        # branches below match the Sage Intacct sim's five processes.
        "customers": (
            "Sage Intacct", "sage_intacct", "boomi", "customer", ["customer_id"],
            ("company_name", "customer_id", "customer"),
        ),
        "chart": (
            "Sage Intacct", "sage_intacct", "boomi", "chart_of_account", ["account_number"], None,
        ),
        "invoices": (
            "Sage Intacct", "sage_intacct", "boomi", "invoice", ["invoice_number"], None,
        ),
        "ap_invoices": (
            "Sage Intacct", "sage_intacct", "boomi", "ap_invoice", ["invoice_number"], None,
        ),
        "vendors": (
            "Sage Intacct", "sage_intacct", "boomi", "vendor", ["vendor_id"], None,
        ),
        # DEPRECATED 2026-05-16 (WS-2): Okta source moved off Boomi. These
        # branches are kept so any in-flight Okta-tagged webhooks during the
        # transition window dispatch cleanly rather than 400. Remove when
        # the Okta source-sim is removed entirely (WS-1.5 cleanup pass).
        "okta_apps": (
            "Okta", "okta", "boomi", "saas_app", ["id"],
            ("label", "id", "saas_subscription"),
        ),
        "okta_users": (
            "Okta", "okta", "boomi", "user", ["id"], None,
        ),
        "okta_assignments": (
            "Okta", "okta", "boomi", "assignment", ["id"], None,
        ),
    },
}


def _dispatch_for_event(vendor: str, event_type: str):
    table = _DISPATCH.get(vendor)
    if not table:
        return None
    for substr, spec in table.items():
        if substr in event_type:
            return spec
    return None


# ---------------------------------------------------------------------------
# Core ingest path — shared by webhook receivers and manual entry
# ---------------------------------------------------------------------------

def _ingest_rows(
    *, rows, pipe, vendor, fabric_plane, source_system,
    tenant_id, entity_id, aam_inference_id, source_run_tag,
    resolve_value_field, resolve_record_key, resolve_domain,
):
    field_mappings = mappings.get_mapping_for_pipe(pipe)
    all_triples: list[dict[str, Any]] = []
    for row in rows:
        identity_value = next(
            (str(row.get(k)) for k in pipe["identity_keys"] if row.get(k) is not None), "",
        )
        if not identity_value:
            raise HTTPException(
                status_code=422,
                detail=f"row missing identity field {pipe['identity_keys']!r}; row keys={list(row.keys())}",
            )
        record = TransportRecord(
            pipe_id=pipe["id"], record_key=identity_value,
            payload=dict(row), source_system=source_system, metadata={},
        )
        if resolve_value_field and resolve_domain and resolve_record_key:
            resolution = _resolve_for_domain(
                record_dict=row, domain=resolve_domain,
                value_field=resolve_value_field, record_key_field=resolve_record_key,
                pipe_id=pipe["id"], tenant_id=tenant_id, entity_id=entity_id,
            )
            if resolution:
                record.metadata["_resolution"] = resolution
        triples = triples_mod.build_triples(
            record, pipe=pipe, mappings=field_mappings,
            tenant_id=tenant_id, entity_id=entity_id,
            aam_inference_id=aam_inference_id,
            source_run_tag=f"{source_run_tag}::{record.record_key}",
            vendor=vendor,
        )
        for t in triples:
            t["fabric_plane"] = fabric_plane
            t["fabric_product"] = vendor
        all_triples.extend(triples)
    return all_triples


def _process_payload(
    *, vendor: str, event_type: str, rows: list[dict],
    tenant_id: str, entity_id: str,
) -> dict[str, Any]:
    # entity_id arrives bound by the caller (per-adapter or per-request),
    # never derived inside this function.
    """Resolve dispatch spec → ingest → push. Returns the response dict.
    Raises HTTPException on validation / unknown event."""
    spec = _dispatch_for_event(vendor, event_type)
    if not spec:
        raise HTTPException(status_code=400, detail=f"unknown event_type for {vendor}: {event_type!r}")
    src_display, src_slug, fabric_plane, domain, identity_keys, resolve_spec = spec
    pipe = _build_pipe(
        vendor=vendor, source_system=src_slug, domain=domain, identity_keys=identity_keys,
    )
    aam_inference_id = str(uuid.uuid4())
    source_run_tag = f"{vendor}::{event_type}::{aam_inference_id[:8]}"
    rvf, rrk, rd = (resolve_spec or (None, None, None))
    all_triples = _ingest_rows(
        rows=rows, pipe=pipe, vendor=vendor,
        fabric_plane=fabric_plane, source_system=src_display,
        tenant_id=tenant_id, entity_id=entity_id,
        aam_inference_id=aam_inference_id, source_run_tag=source_run_tag,
        resolve_value_field=rvf, resolve_record_key=rrk, resolve_domain=rd,
    )
    pushed = dcl_push.push_triples(
        triples=all_triples, tenant_id=tenant_id, entity_id=entity_id,
        source_run_tag=source_run_tag,
    )
    return {
        "aam_inference_id": aam_inference_id,
        "dcl_ingest_id": pushed.get("dcl_ingest_id"),
        "rows_seen": len(rows),
        "triples_built": len(all_triples),
        "triples_pushed": len(all_triples),  # push_triples raises on rejection
        "concept_summary": pushed.get("concept_summary"),
    }


# ---------------------------------------------------------------------------
# Webhook receiver (vendor-agnostic core; thin per-vendor wrappers)
# ---------------------------------------------------------------------------

async def _handle_webhook(
    *, vendor: str, request: Request, header_value: str | None,
    secret_env: str, secret_default: str,
) -> dict[str, Any]:
    body_bytes = await request.body()
    sig_truncated = (header_value or "")[:16] or None
    verified = _verify_signature(
        body_bytes=body_bytes, header_value=header_value,
        secret_env=secret_env, secret_default=secret_default,
    )
    # Parse event_type best-effort for the receipt row before we 401.
    parsed: dict[str, Any] = {}
    if verified:
        try:
            parsed = json.loads(body_bytes)
        except json.JSONDecodeError:
            parsed = {}
    event_type = parsed.get("event_type") if isinstance(parsed, dict) else None
    receipt_id = fabric_webhook_log.log_receipt(
        vendor=vendor, event_type=event_type,
        payload_bytes=len(body_bytes),
        signature_verified=verified,
        signature_truncated=sig_truncated,
        payload=parsed if verified else None,
        source="webhook",
    )

    if not verified:
        fabric_webhook_log.finalize_receipt(
            receipt_id, error="signature mismatch or missing header",
            push_status_code=401,
        )
        raise HTTPException(status_code=401, detail="webhook signature mismatch or missing")

    try:
        payload = parsed if isinstance(parsed, dict) and parsed else json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        fabric_webhook_log.finalize_receipt(receipt_id, error=f"JSON parse: {exc}", push_status_code=400)
        raise HTTPException(status_code=400, detail=f"webhook body not JSON: {exc}")

    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        fabric_webhook_log.finalize_receipt(receipt_id, error="payload.rows not a list", push_status_code=400)
        raise HTTPException(status_code=400, detail="payload.rows must be a list")
    if not rows:
        fabric_webhook_log.finalize_receipt(receipt_id, rows_seen=0, triples_built=0,
                                            triples_pushed=0, push_status_code=200)
        return {"accepted": True, "receipt_id": receipt_id, "rows": 0, "triples_pushed": 0}

    try:
        tenant_id = _tenant_id_from(payload)
        # Per-adapter entity_id — NOT from payload, NOT from a global env.
        # The webhook payload's entity_id (set by the Farm sim or vendor
        # cloud) is informational; the AAM receiver is the source of truth
        # for what identity gets stamped on triples that land in DCL.
        entity_id = _vendor_tenant_entity_id(vendor)
        result = _process_payload(
            vendor=vendor, event_type=event_type or "",
            rows=rows, tenant_id=tenant_id, entity_id=entity_id,
        )
    except HTTPException as exc:
        fabric_webhook_log.finalize_receipt(
            receipt_id, error=f"{exc.status_code}: {exc.detail}",
            push_status_code=exc.status_code,
        )
        raise
    except dcl_push.DCLPushError as exc:
        fabric_webhook_log.finalize_receipt(receipt_id, error=str(exc)[:500], push_status_code=502)
        raise HTTPException(status_code=502, detail=f"DCL push failed: {exc}")
    except Exception as exc:
        fabric_webhook_log.finalize_receipt(receipt_id, error=f"unexpected: {exc}"[:500], push_status_code=500)
        raise

    fabric_webhook_log.finalize_receipt(
        receipt_id,
        aam_inference_id=result["aam_inference_id"],
        dcl_ingest_id=result["dcl_ingest_id"],
        rows_seen=result["rows_seen"],
        triples_built=result["triples_built"],
        triples_pushed=result["triples_pushed"],
        push_status_code=201,  # DCL ingest returns 201
    )
    _log.info(
        "%s webhook accepted event=%s rows=%d triples=%d dcl_ingest_id=%s receipt_id=%s",
        vendor, event_type, len(rows), result["triples_built"],
        result["dcl_ingest_id"], receipt_id,
    )
    return {"accepted": True, "receipt_id": receipt_id, **result, "rows": len(rows)}


@router.post("/api/aam/webhooks/workato")
async def workato_webhook(
    request: Request,
    x_workato_signature: str | None = Header(default=None, alias="x-workato-signature"),
):
    return await _handle_webhook(
        vendor="workato", request=request, header_value=x_workato_signature,
        secret_env="WORKATO_WEBHOOK_SECRET", secret_default="sim-workato-secret",
    )


@router.post("/api/aam/webhooks/boomi")
async def boomi_webhook(
    request: Request,
    x_boomi_signature: str | None = Header(default=None, alias="x-boomi-signature"),
):
    return await _handle_webhook(
        vendor="boomi", request=request, header_value=x_boomi_signature,
        secret_env="BOOMI_WEBHOOK_SECRET", secret_default="sim-boomi-secret",
    )


# ---------------------------------------------------------------------------
# WP12e — manual entry: same code path, no signature, source='manual'
# ---------------------------------------------------------------------------

class ManualEntry(BaseModel):
    pipe_key: str = Field(..., description="MAPPINGS key, e.g., workato::netsuite::vendor")
    row: dict[str, Any] = Field(..., description="Single record with field names matching the mapping")
    entity_id: str = Field(..., min_length=1, description="Tenant entity_id — REQUIRED. No env fallback; manual entry is per-call.")
    tenant_id: str | None = None


# Map MAPPINGS key → (vendor, event_type) so manual entries route through
# the same _process_payload dispatch table as webhooks. Keys mirror the
# vendor-event substrings used in _DISPATCH.
_MANUAL_PIPE_TO_EVENT: dict[str, tuple[str, str]] = {
    # WS-2 customer-side: NetSuite via Workato
    "workato::netsuite::customer":            ("workato", "customers"),
    "workato::netsuite::chart_of_account":    ("workato", "chart"),
    "workato::netsuite::invoice":             ("workato", "invoices"),
    # NetSuite vendor-payable side (carried from WS-1)
    "workato::netsuite::vendor":              ("workato", "vendor_master"),
    "workato::netsuite::ap_invoice":          ("workato", "ap_invoices"),
    # WS-2: Sage Intacct via Boomi
    "boomi::sage_intacct::customer":          ("boomi", "customers"),
    "boomi::sage_intacct::chart_of_account":  ("boomi", "chart"),
    "boomi::sage_intacct::invoice":           ("boomi", "invoices"),
    "boomi::sage_intacct::ap_invoice":        ("boomi", "ap_invoices"),
    "boomi::sage_intacct::vendor":            ("boomi", "vendors"),
}


@router.post("/api/aam/manual-entry")
async def manual_entry(req: ManualEntry):
    if req.pipe_key not in _MANUAL_PIPE_TO_EVENT:
        raise HTTPException(
            status_code=400,
            detail=f"unknown pipe_key {req.pipe_key!r}; valid: {sorted(_MANUAL_PIPE_TO_EVENT.keys())}",
        )
    vendor, event_type = _MANUAL_PIPE_TO_EVENT[req.pipe_key]
    payload = {
        "event_type": event_type,
        "tenant_id": req.tenant_id or os.environ.get("AOS_TENANT_ID", ""),
        "entity_id": req.entity_id,    # required by Pydantic; no env fallback
        "rows": [req.row],
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    receipt_id = fabric_webhook_log.log_receipt(
        vendor=vendor, event_type=event_type,
        payload_bytes=len(body_bytes),
        signature_verified=True,           # n/a for manual
        signature_truncated=None,
        payload=payload, source="manual",
    )
    try:
        tenant_id = _tenant_id_from(payload)
        result = _process_payload(
            vendor=vendor, event_type=event_type,
            rows=payload["rows"], tenant_id=tenant_id, entity_id=req.entity_id,
        )
    except HTTPException as exc:
        fabric_webhook_log.finalize_receipt(
            receipt_id, error=f"{exc.status_code}: {exc.detail}",
            push_status_code=exc.status_code,
        )
        raise
    except dcl_push.DCLPushError as exc:
        fabric_webhook_log.finalize_receipt(receipt_id, error=str(exc)[:500], push_status_code=502)
        raise HTTPException(status_code=502, detail=f"DCL push failed: {exc}")

    fabric_webhook_log.finalize_receipt(
        receipt_id,
        aam_inference_id=result["aam_inference_id"],
        dcl_ingest_id=result["dcl_ingest_id"],
        rows_seen=result["rows_seen"],
        triples_built=result["triples_built"],
        triples_pushed=result["triples_pushed"],
        push_status_code=201,
    )
    return {"accepted": True, "receipt_id": receipt_id, **result, "rows": 1}
