"""Hardcoded field mappings (source_field -> concept + property) for the demo.

Production replaces this with the LLM-assisted Semantic Field Mapper (WP-8,
Platform repo). For the demo, deterministic mappings cover the two vendor
schemas defined in scenarios/healthy.json and scenarios/multi_vendor.json.

confidence_score is 0.95 — these are explicit, exact mappings.

Concept names follow DCL's canonical lowercase ontology IDs (151 entries in
dcl/config/ontology_concepts.yaml). Compound names like "it_asset.saas_app"
share the registered root concept ("it_asset") for DCL validation while
preserving the AAM-side distinction between SaaSApp and Assignment, which
both belong to the same DCL domain but produce different triples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldMapping:
    source_field: str
    concept: str
    property: str
    confidence: float = 0.95


# Key: vendor_lower + first identity key + source_system (best discriminator).
# Value: list of FieldMappings.
MAPPINGS: dict[str, list[FieldMapping]] = {
    # Workato — Salesforce Account
    "workato::salesforce::account_id": [
        FieldMapping("account_id", "customer", "id"),
        FieldMapping("account_name", "customer", "name"),
        FieldMapping("annual_revenue", "customer", "revenue_usd"),
        FieldMapping("industry", "customer", "industry"),
    ],
    # Workato — Workday HR
    "workato::workday::employee_id": [
        FieldMapping("employee_id", "employee", "id"),
        FieldMapping("department", "employee", "department"),
        FieldMapping("salary", "employee", "compensation_usd"),
    ],
    # Workato — Stripe revenue
    "workato::stripe::charge_id": [
        FieldMapping("charge_id", "revenue", "id"),
        FieldMapping("amount_cents", "revenue", "amount_cents"),
        FieldMapping("currency", "revenue", "currency"),
        FieldMapping("customer_id", "revenue", "customer_id"),
    ],
    # Boomi — ServiceNow tickets
    "boomi::servicenow::ticket_id": [
        FieldMapping("ticket_id", "support", "id"),
        FieldMapping("subject", "support", "subject"),
        FieldMapping("priority", "support", "priority"),
        FieldMapping("status", "support", "status"),
    ],
    # Boomi — Concur expenses
    "boomi::concur::expense_id": [
        FieldMapping("expense_id", "opex", "id"),
        FieldMapping("amount", "opex", "amount_usd"),
        FieldMapping("category", "opex", "category"),
        FieldMapping("submitter", "opex", "submitter"),
    ],

    # --- Mappings keyed by endpoint_ref.domain (preferred over identity_keys[0])
    # for systems where multiple pipes share the same identity-key name. The
    # NetSuite + Okta packs below illustrate the pattern: three Okta pipes all
    # use identity_keys=['id'] but distinguish at the domain tag.

    # Workato -> NetSuite Vendor Master
    "workato::netsuite::vendor": [
        FieldMapping("vendor_id", "vendor", "id"),
        FieldMapping("vendor_name", "vendor", "name"),
        FieldMapping("category", "vendor", "category"),
        FieldMapping("currency", "vendor", "currency"),
        FieldMapping("subsidiary", "vendor", "subsidiary"),
        FieldMapping("is_1099", "vendor", "is_1099_reportable"),
    ],
    # Workato -> NetSuite AP Invoice. NetSuite's "amount" is the gross billed
    # amount before any reclassification — it could mean gross_billed_usd or
    # net_recognized_usd. Mid-confidence mapping (0.78) surfaces in the
    # Semantic Mapping UI for explicit operator confirmation.
    "workato::netsuite::ap_invoice": [
        FieldMapping("bill_no", "invoice", "id"),
        FieldMapping("vendor_id", "invoice", "vendor_id"),
        FieldMapping("vendor_name", "invoice", "vendor_name"),
        FieldMapping("due_date", "invoice", "due_date"),
        FieldMapping("amount", "invoice", "gross_billed_usd", confidence=0.78),
        FieldMapping("currency", "invoice", "currency"),
        FieldMapping("status", "invoice", "payment_status"),
        FieldMapping("subsidiary", "invoice", "subsidiary"),
        FieldMapping("posting_period", "invoice", "posting_period"),
    ],
    # Boomi -> Okta SaaS App Catalog (compound it_asset.saas_app keeps the
    # AAM-side distinction from Assignment while sharing DCL's registered
    # it_asset root concept)
    "boomi::okta::saas_app": [
        FieldMapping("id", "it_asset.saas_app", "id"),
        FieldMapping("label", "it_asset.saas_app", "name"),
        FieldMapping("status", "it_asset.saas_app", "status"),
        FieldMapping("license_tier", "it_asset.saas_app", "license_tier"),
        FieldMapping("license_seat_count", "it_asset.saas_app", "license_seat_count"),
        FieldMapping("annual_cost_per_seat_usd", "it_asset.saas_app", "annual_cost_per_seat_usd"),
        FieldMapping("created", "it_asset.saas_app", "created_at"),
    ],
    # Boomi -> Okta User Directory (employee root — Okta user accounts share
    # the same DCL domain as Workday Employee; source_system + property
    # discriminate at query time)
    "boomi::okta::user": [
        FieldMapping("id", "employee", "id"),
        FieldMapping("profile_email", "employee", "email"),
        FieldMapping("profile_first_name", "employee", "first_name"),
        FieldMapping("profile_last_name", "employee", "last_name"),
        FieldMapping("status", "employee", "status"),
        FieldMapping("department", "employee", "department"),
    ],
    # Boomi -> Okta App Assignment with login telemetry (compound
    # it_asset.assignment shares the it_asset root with SaaSApp)
    "boomi::okta::assignment": [
        FieldMapping("id", "it_asset.assignment", "id"),
        FieldMapping("user_id", "it_asset.assignment", "user_id"),
        FieldMapping("app_id", "it_asset.assignment", "app_id"),
        FieldMapping("assignment_date", "it_asset.assignment", "assignment_date"),
        FieldMapping("last_login", "it_asset.assignment", "last_login_at"),
        FieldMapping("active_in_last_30d", "it_asset.assignment", "active_in_last_30d"),
    ],
}


def _key_for(vendor: str, source_system: str, discriminator: str) -> str:
    return f"{vendor.lower()}::{source_system.lower()}::{discriminator.lower()}"


def get_mapping_for_pipe(pipe: dict[str, Any]) -> list[FieldMapping]:
    """Return the FieldMappings for a DeclaredPipe dict.

    Lookup discriminator (in order of preference):
      1. endpoint_ref.domain — scenarios that set an explicit domain tag
         (e.g., "vendor", "ap_invoice", "saas_app", "user", "assignment")
         resolve cleanly even when multiple pipes share the same identity_key
         field name. This is how the NetSuite + Okta example pack works —
         all three Okta pipes have identity_keys=['id'] but differ by domain.
      2. identity_keys[0] — original behavior; preserved for older scenarios
         where each pipe has a unique identity-key field name.

    Raises if no mapping exists — no silent invention.
    """
    vendor = ""
    for hint in pipe.get("provenance", {}).get("lineage_hints", []):
        if isinstance(hint, str) and hint.startswith("vendor:"):
            vendor = hint.split(":", 1)[1]
            break
    source_system = str(pipe.get("source_system", ""))
    endpoint_ref = pipe.get("endpoint_ref") or {}
    domain = ""
    if isinstance(endpoint_ref, dict):
        domain = str(endpoint_ref.get("domain") or "")
    if domain:
        # Prefer the explicit domain when the scenario provides one.
        domain_key = _key_for(vendor, source_system, domain)
        if domain_key in MAPPINGS:
            return MAPPINGS[domain_key]
    identity_keys = list(pipe.get("identity_keys") or [])
    first_key = identity_keys[0] if identity_keys else ""
    legacy_key = _key_for(vendor, source_system, first_key)
    if legacy_key in MAPPINGS:
        return MAPPINGS[legacy_key]
    raise KeyError(
        f"No field mapping for pipe vendor={vendor} source_system={source_system} "
        f"domain={domain!r} identity_keys={identity_keys}. "
        f"Add an entry to app/ingest/mappings.py MAPPINGS or set endpoint_ref.domain "
        f"on the scenario pipe."
    )
