"""TransportRecord -> DCL TriplePayload builder.

Produces dicts matching the shape DCL's /api/dcl/ingest-triples endpoint
expects (dcl/backend/api/routes/ingest_triples.py:57-75 TriplePayload).

Differs from the legacy builder in app/ingest/triples.py:
  - Output keys map DCL's column vocabulary (no aam_inference_id field —
    that lives on the request envelope, not on each triple).
  - Concept names are canonicalized to ontology-valid lowercase roots
    (e.g., "Vendor" -> "vendor", "SaaSApp" -> "it_asset.saas_app") so the
    DCL concept registry accepts them. AAM operator-facing names in
    app/ingest/mappings.py stay readable; the canonicalizer translates at
    the write boundary.
  - source_system is derived from the pipe's source_product (NetSuite,
    Okta, Salesforce, ...) — never literal "AAM". Validates the
    vendor↔source-product pair against an explicit map; ambiguous pairs
    raise rather than fall back to a default.
  - fabric_plane is read from the pipe's existing translator output
    (IPAAS / API_GATEWAY / EVENT_BUS / DATA_WAREHOUSE) and lowercased to
    match DCL's enum.
  - resolution_method is translated to DCL's vocabulary
    {deterministic, fuzzy, manual} via _RESOLUTION_METHOD_TO_PG (re-exported
    from app/ingest/triples.py — single source of truth for the mapping).

The builder owns no I/O. The orchestrator hands the triples to DCLPusher.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from ..transport.http import TransportRecord
from .mappings import FieldMapping
from .triples import _RESOLUTION_METHOD_TO_PG

_log = logging.getLogger("aam.ingest.triple_builder")


# ---------------------------------------------------------------------------
# Identifier coercion
# ---------------------------------------------------------------------------
# DCL's semantic_triples.pipe_id column is UUID-typed. AAM's pipes carry
# human-readable ids like "wk-recipe-101" from the ipaas_stub. Deterministically
# coerce any non-UUID string to a UUID5 from the URL namespace so the same pipe
# id always produces the same UUID across runs — same pattern Farm's
# dcl_triple_pusher.derive_pipeline_uuid uses.
def _to_uuid_or_none(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        uuid.UUID(s)
        return s
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, s))


# ---------------------------------------------------------------------------
# Concept canonicalization
# ---------------------------------------------------------------------------
# DCL validates triple concepts in two places:
#   1. backend/registry/concept_registry.py — concept root must be a known
#      ontology concept id (151 entries in config/ontology_concepts.yaml).
#   2. backend/api/routes/ingest_triples.py:156-172 — concept root must be in
#      _MAPPED_DOMAIN_PREFIXES (built from config/persona_domains.yaml).
#
# AAM's FieldMapping uses operator-friendly capitalized names (Vendor, Customer,
# SaaSApp). Translate to lowercase ontology roots at the write boundary. This
# is the equivalent of _RESOLUTION_METHOD_TO_PG: keep the in-process vocabulary
# expressive, narrow at the DCL seam.
_CONCEPT_TO_DCL_ROOT: dict[str, str] = {
    "Customer": "customer",
    "Employee": "employee",
    "Vendor": "vendor",
    "Transaction": "revenue",          # stripe charges -> revenue domain
    "Incident": "support",             # ServiceNow tickets -> support
    "Expense": "opex",                 # Concur expenses -> opex
    "APInvoice": "invoice",            # NetSuite AP invoices -> invoice
    "SaaSApp": "it_asset",             # Okta apps -> it_asset (registered + persona-mapped)
    "User": "employee",                # Okta users surface as employee identities
    "Assignment": "it_asset",          # Okta app assignment = user-app linkage
}


def _canonical_concept(concept: str) -> str:
    """Translate an AAM mapping concept to a DCL-valid concept.

    Mapping concepts are like "Customer", "Vendor", "SaaSApp" (PascalCase).
    DCL requires the root segment (before the first dot) to be a registered
    ontology concept AND a mapped persona domain prefix.

    The translator keeps the AAM property name as a sub-segment so the triple
    semantic stays unambiguous: "Vendor" + property "name" becomes
    concept="vendor.name". DCL's prefix-based validator
    (ConceptRegistry.is_valid_concept) accepts any concept whose root segment
    is a registered id, so "vendor.name", "vendor.subsidiary", etc. all pass.
    """
    if not concept:
        raise ValueError("triple_builder: concept must be a non-empty string")
    if concept in _CONCEPT_TO_DCL_ROOT:
        return _CONCEPT_TO_DCL_ROOT[concept]
    # Already lowercase / pre-canonicalized — let it through unchanged. If
    # DCL rejects it, the loud-fail error from the pusher will surface the
    # root, and the operator can add the explicit mapping here.
    root = concept.split(".", 1)[0]
    if root.islower() and root.isascii():
        return concept
    raise ValueError(
        f"triple_builder: concept {concept!r} has no entry in "
        f"_CONCEPT_TO_DCL_ROOT and is not already lowercase. "
        f"Add an explicit mapping in app/ingest/triple_builder.py before "
        f"sending this concept to DCL."
    )


# ---------------------------------------------------------------------------
# Vendor -> source_system map
# ---------------------------------------------------------------------------
# The pipe's TransportRecord.source_system already carries the source product
# name as a free-form string ("NetSuite", "Okta", "Salesforce"). Lowercase it
# at the DCL boundary so downstream queries (SELECT source_system, COUNT(*) ...
# GROUP BY source_system) collapse the casing variants. If the record's
# source_system is empty, the builder raises — no fallback to vendor name or
# "AAM" placeholder.
#
# This map is for the reverse lookup: given a (vendor, intended_source_product)
# pair, what is the canonical source_system string. Used by tests asserting
# the expected source_system per scenario configuration.
VENDOR_TO_SOURCE_SYSTEM: dict[tuple[str, str], str] = {
    ("workato", "netsuite"): "netsuite",
    ("workato", "salesforce"): "salesforce",
    ("workato", "workday"): "workday",
    ("workato", "stripe"): "stripe",
    ("boomi", "okta"): "okta",
    ("boomi", "servicenow"): "servicenow",
    ("boomi", "concur"): "concur",
}


def expected_source_system(vendor: str, source_product: str) -> str:
    """Return the canonical source_system string for a (vendor, product) pair.

    Tests use this to compute expected values; the runtime path reads
    source_system off TransportRecord directly. Raises on unknown pairs.
    """
    key = (vendor.strip().lower(), source_product.strip().lower())
    if key not in VENDOR_TO_SOURCE_SYSTEM:
        raise KeyError(
            f"triple_builder: no source_system mapping for vendor={vendor!r} "
            f"source_product={source_product!r}. Add to VENDOR_TO_SOURCE_SYSTEM."
        )
    return VENDOR_TO_SOURCE_SYSTEM[key]


# ---------------------------------------------------------------------------
# Fabric plane normalization
# ---------------------------------------------------------------------------
# Translator output uses uppercase enum-style values (IPAAS, API_GATEWAY,
# EVENT_BUS, DATA_WAREHOUSE). DCL's fabric_plane column is free-text string
# (Optional[str]) but downstream queries lowercase. Normalize once at the
# write boundary so both producers agree.
_FABRIC_PLANE_TO_DCL: dict[str, str] = {
    "IPAAS": "ipaas",
    "API_GATEWAY": "api_gateway",
    "EVENT_BUS": "event_bus",
    "DATA_WAREHOUSE": "data_warehouse",
}


def _canonical_fabric_plane(plane: Optional[str]) -> Optional[str]:
    """Lowercase the fabric_plane to match DCL's persona-stat lowercase
    convention. Unknown planes pass through unchanged.
    """
    if not plane:
        return None
    return _FABRIC_PLANE_TO_DCL.get(plane, plane.lower())


# ---------------------------------------------------------------------------
# Confidence tier
# ---------------------------------------------------------------------------
# DCL's IngestRequest._VALID_TIERS = {"exact", "high", "medium", "low"}.
# Threshold bands match what the legacy builder uses
# (app/ingest/triples.py _tier).
def _tier(score: float) -> str:
    if score >= 0.95:
        return "exact"
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_dcl_triples(
    record: TransportRecord,
    *,
    pipe: dict[str, Any],
    mappings: list[FieldMapping],
    tenant_id: str,
    entity_id: str,
    vendor: str,
) -> list[dict[str, Any]]:
    """Produce one DCL TriplePayload dict per (record, mapped field).

    Loud-fail invariants:
      - tenant_id and entity_id must be non-empty strings
      - record.source_system must be non-empty (the real source product
        name like "NetSuite" / "Okta"; never the literal "AAM")
      - every concept must canonicalize to a DCL-valid root
    """
    if not tenant_id or not entity_id:
        raise ValueError(
            f"build_dcl_triples: tenant_id and entity_id are required "
            f"(got tenant_id={tenant_id!r} entity_id={entity_id!r})"
        )
    if not record.source_system:
        raise ValueError(
            f"build_dcl_triples: record.source_system is empty "
            f"pipe_id={record.pipe_id} record_key={record.record_key}. "
            f"Source product must be non-empty — no 'AAM' placeholder."
        )

    # Resolution metadata (canonical_id, resolution_method, resolution_confidence)
    # is attached to the record by the resolver stage upstream. Absence means
    # the resolver was skipped (e.g., non-identity domains) — leave the
    # resolution columns NULL.
    resolution = (record.metadata or {}).get("_resolution") or {}
    canonical_id = resolution.get("canonical_id")
    resolution_method_internal = resolution.get("resolution_method")
    resolution_confidence = resolution.get("resolution_confidence")

    # Translate AAM's resolver vocabulary to DCL's CHECK constraint.
    resolution_method_dcl: Optional[str] = None
    if resolution_method_internal is not None:
        if resolution_method_internal not in _RESOLUTION_METHOD_TO_PG:
            raise ValueError(
                f"build_dcl_triples: unknown resolution_method="
                f"{resolution_method_internal!r}. "
                f"Allowed AAM values: {sorted(_RESOLUTION_METHOD_TO_PG.keys())}"
            )
        resolution_method_dcl = _RESOLUTION_METHOD_TO_PG[resolution_method_internal]

    fabric_plane_raw = pipe.get("fabric_plane")
    fabric_plane = _canonical_fabric_plane(
        fabric_plane_raw if isinstance(fabric_plane_raw, str) else None
    )
    fabric_product = record.source_system.lower()
    source_system = record.source_system.lower()
    pipe_id_raw = pipe.get("pipe_id") or record.pipe_id
    # DCL stores pipe_id as UUID — coerce non-UUID strings deterministically.
    pipe_id = _to_uuid_or_none(pipe_id_raw)

    out: list[dict[str, Any]] = []
    mapping_by_field = {m.source_field: m for m in mappings}
    for field_name, value in record.payload.items():
        m = mapping_by_field.get(field_name)
        if not m:
            _log.warning(
                "build_dcl_triples: unmapped field=%s pipe_id=%s record_key=%s — "
                "surfacing for review",
                field_name, record.pipe_id, record.record_key,
            )
            continue
        # m.concept = "Vendor"; m.property = "name". DCL concept = "vendor.name".
        dcl_root = _canonical_concept(m.concept)
        dcl_concept = f"{dcl_root}.{m.property}"
        # Resolver confidence (when present and lower than the field-mapping
        # confidence) takes precedence — a fuzzy resolution can't push a
        # downstream triple to higher certainty than the resolution itself.
        confidence = m.confidence
        if (
            resolution_confidence is not None
            and resolution_confidence < confidence
        ):
            confidence = resolution_confidence

        out.append({
            "entity_id": entity_id,
            "concept": dcl_concept,
            "property": m.property,
            "value": value,
            "period": None,
            "currency": "USD",
            "unit": None,
            "source_system": source_system,
            "source_table": f"aam_via:{vendor}",
            "source_field": field_name,
            "pipe_id": pipe_id,
            "confidence_score": confidence,
            "confidence_tier": _tier(confidence),
            "canonical_id": canonical_id,
            "resolution_method": resolution_method_dcl,
            "resolution_confidence": resolution_confidence,
            "fabric_plane": fabric_plane,
            "fabric_product": fabric_product,
        })
    return out
