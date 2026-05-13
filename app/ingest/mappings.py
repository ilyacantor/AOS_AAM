"""Hardcoded field mappings (source_field -> concept + property) for the demo.

Production replaces this with the LLM-assisted Semantic Field Mapper (WP-8,
Platform repo). For the demo, deterministic mappings cover the two vendor
schemas defined in scenarios/healthy.json and scenarios/multi_vendor.json.

confidence_score is 0.95 — these are explicit, exact mappings.
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
        FieldMapping("account_id", "Customer", "id"),
        FieldMapping("account_name", "Customer", "name"),
        FieldMapping("annual_revenue", "Customer", "revenue_usd"),
        FieldMapping("industry", "Customer", "industry"),
    ],
    # Workato — Workday HR
    "workato::workday::employee_id": [
        FieldMapping("employee_id", "Employee", "id"),
        FieldMapping("department", "Employee", "department"),
        FieldMapping("salary", "Employee", "compensation_usd"),
    ],
    # Workato — Stripe revenue
    "workato::stripe::charge_id": [
        FieldMapping("charge_id", "Transaction", "id"),
        FieldMapping("amount_cents", "Transaction", "amount_cents"),
        FieldMapping("currency", "Transaction", "currency"),
        FieldMapping("customer_id", "Transaction", "customer_id"),
    ],
    # Boomi — ServiceNow tickets
    "boomi::servicenow::ticket_id": [
        FieldMapping("ticket_id", "Incident", "id"),
        FieldMapping("subject", "Incident", "subject"),
        FieldMapping("priority", "Incident", "priority"),
        FieldMapping("status", "Incident", "status"),
    ],
    # Boomi — Concur expenses
    "boomi::concur::expense_id": [
        FieldMapping("expense_id", "Expense", "id"),
        FieldMapping("amount", "Expense", "amount_usd"),
        FieldMapping("category", "Expense", "category"),
        FieldMapping("submitter", "Expense", "submitter"),
    ],

    # --- FinOps SaaS-spending demo (NetSuite vendor/AP via Workato, Okta via Boomi) ---
    # Mapping keys for the FinOps scenario use the explicit domain tag from
    # endpoint_ref.domain — all three Okta pipes have identity_keys=['id']
    # but resolve cleanly via domain.

    # Workato -> NetSuite Vendor Master
    "workato::netsuite::vendor": [
        FieldMapping("vendor_id", "Vendor", "id"),
        FieldMapping("vendor_name", "Vendor", "name"),
        FieldMapping("category", "Vendor", "category"),
        FieldMapping("currency", "Vendor", "currency"),
        FieldMapping("subsidiary", "Vendor", "subsidiary"),
        FieldMapping("is_1099", "Vendor", "is_1099_reportable"),
    ],
    # Workato -> NetSuite AP Invoice. NetSuite's "amount" is the gross billed
    # amount before any reclassification — it could mean gross_billed_usd or
    # net_recognized_usd. Mid-confidence mapping (0.78) surfaces in the
    # Semantic Mapping UI for explicit operator confirmation.
    "workato::netsuite::ap_invoice": [
        FieldMapping("bill_no", "APInvoice", "id"),
        FieldMapping("vendor_id", "APInvoice", "vendor_id"),
        FieldMapping("vendor_name", "APInvoice", "vendor_name"),
        FieldMapping("due_date", "APInvoice", "due_date"),
        FieldMapping("amount", "APInvoice", "gross_billed_usd", confidence=0.78),
        FieldMapping("currency", "APInvoice", "currency"),
        FieldMapping("status", "APInvoice", "payment_status"),
        FieldMapping("subsidiary", "APInvoice", "subsidiary"),
        FieldMapping("posting_period", "APInvoice", "posting_period"),
    ],
    # Boomi -> Okta SaaS App Catalog
    "boomi::okta::saas_app": [
        FieldMapping("id", "SaaSApp", "id"),
        FieldMapping("label", "SaaSApp", "name"),
        FieldMapping("status", "SaaSApp", "status"),
        FieldMapping("license_tier", "SaaSApp", "license_tier"),
        FieldMapping("license_seat_count", "SaaSApp", "license_seat_count"),
        FieldMapping("annual_cost_per_seat_usd", "SaaSApp", "annual_cost_per_seat_usd"),
        FieldMapping("created", "SaaSApp", "created_at"),
    ],
    # Boomi -> Okta User Directory
    "boomi::okta::user": [
        FieldMapping("id", "User", "id"),
        FieldMapping("profile_email", "User", "email"),
        FieldMapping("profile_first_name", "User", "first_name"),
        FieldMapping("profile_last_name", "User", "last_name"),
        FieldMapping("status", "User", "status"),
        FieldMapping("department", "User", "department"),
    ],
    # Boomi -> Okta App Assignment with login telemetry
    "boomi::okta::assignment": [
        FieldMapping("id", "Assignment", "id"),
        FieldMapping("user_id", "Assignment", "user_id"),
        FieldMapping("app_id", "Assignment", "app_id"),
        FieldMapping("assignment_date", "Assignment", "assignment_date"),
        FieldMapping("last_login", "Assignment", "last_login_at"),
        FieldMapping("active_in_last_30d", "Assignment", "active_in_last_30d"),
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
         field name. This is how the FinOps SaaS-spending scenario works —
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
