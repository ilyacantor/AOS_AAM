"""HTTP push to DCL /api/dcl/ingest-triples.

The earlier WP4 push library was deleted in WP6 (see entry #12 in
aam_deferred_work.md). This is a fresh, minimal HTTP client for the new
WP12a' webhook path — no batch parallelism (volumes are small per webhook),
no retries (failures must surface). If a future code path needs production-
scale ingest, port Farm's farm/src/services/dcl_triple_pusher.py.

Contract: POST /api/dcl/ingest-triples
Required envelope fields: tenant_id (UUID), dcl_ingest_id (UUID), triples[].
Required per-triple provenance: source_system, source_field, pipe_id,
fabric_plane, confidence_score (all non-null). DCL returns 422 if any
provenance field is missing.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

import httpx

_log = logging.getLogger("aam.ingest.dcl_push")


class DCLPushError(Exception):
    """Raised when a DCL ingest call fails. Loud-fail."""


def _to_dcl_triple(t: dict[str, Any]) -> dict[str, Any]:
    """Translate AAM in-memory triple dict to DCL TriplePayload schema."""
    out = {
        "entity_id": t["entity_id"],
        "concept": t["concept"],
        "property": t["property"],
        "value": t["value"],
        "period": t.get("period"),
        "currency": t.get("currency", "USD"),
        "unit": t.get("unit"),
        "source_system": t["source_system"],
        "source_table": t.get("source_table"),
        "source_field": t["source_field"],
        "pipe_id": t["pipe_id"],
        "confidence_score": t["confidence_score"],
        "confidence_tier": t["confidence_tier"],
        "canonical_id": t.get("canonical_id"),
        "resolution_method": _translate_resolution_method(t.get("resolution_method")),
        "resolution_confidence": t.get("resolution_confidence"),
        "fabric_plane": t.get("fabric_plane"),
        "fabric_product": t.get("fabric_product"),
    }
    return out


# DCL's CHECK constraint on resolution_method accepts {deterministic, fuzzy,
# manual} — see deferred entry #7. AAM's richer vocabulary translates here.
_RESOLUTION_METHOD_TO_DCL = {
    "exact": "deterministic",
    "alias": "deterministic",
    "pattern": "deterministic",
    "discovery": "deterministic",
    "fuzzy": "fuzzy",
    "hitl_pending": "fuzzy",
    "hitl_confirmed": "manual",
    "rejected": None,
    None: None,
}


def _translate_resolution_method(method: Any) -> Any:
    if method not in _RESOLUTION_METHOD_TO_DCL:
        raise DCLPushError(
            f"unknown resolution_method={method!r}; "
            f"allowed: {sorted(k for k in _RESOLUTION_METHOD_TO_DCL if k is not None)}"
        )
    return _RESOLUTION_METHOD_TO_DCL[method]


def push_triples(
    *,
    triples: list[dict[str, Any]],
    tenant_id: str,
    entity_id: str,
    source_run_tag: str,
    dcl_base: str | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """POST one batch to /api/dcl/ingest-triples. Returns the parsed response.

    Raises DCLPushError on non-2xx.
    """
    if not triples:
        raise DCLPushError("push_triples called with empty triples list")
    base = (dcl_base or os.environ.get("DCL_URL", "")).rstrip("/")
    if not base:
        raise DCLPushError("DCL_URL is not set; cannot push triples")
    url = f"{base}/api/dcl/ingest-triples"

    dcl_ingest_id = str(uuid.uuid4())
    body = {
        "tenant_id": tenant_id,
        "dcl_ingest_id": dcl_ingest_id,
        "source_run_tag": source_run_tag,
        "entity_id": entity_id,
        "source_rows": len({t.get("source_field") for t in triples}),
        "triples": [_to_dcl_triple(t) for t in triples],
    }
    _log.info(
        "DCL push -> %s tenant=%s entity=%s triples=%d dcl_ingest_id=%s",
        url, tenant_id, entity_id, len(triples), dcl_ingest_id,
    )
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, json=body)
    except httpx.HTTPError as exc:
        raise DCLPushError(
            f"DCL push transport failed: {type(exc).__name__}: {exc}"
        ) from exc
    if resp.status_code >= 400:
        raise DCLPushError(
            f"DCL push rejected: status={resp.status_code} body={resp.text[:500]}"
        )
    try:
        parsed = resp.json()
    except json.JSONDecodeError as exc:
        raise DCLPushError(f"DCL response was not JSON: {exc} body={resp.text[:200]}") from exc
    parsed["dcl_ingest_id"] = parsed.get("dcl_ingest_id") or dcl_ingest_id
    return parsed
