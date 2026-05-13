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
}


def _key_for(vendor: str, source_system: str, identity_keys: list[str]) -> str:
    first_key = identity_keys[0] if identity_keys else ""
    return f"{vendor.lower()}::{source_system.lower()}::{first_key.lower()}"


def get_mapping_for_pipe(pipe: dict[str, Any]) -> list[FieldMapping]:
    """Return the FieldMappings for a DeclaredPipe dict.

    Lookup key combines vendor (from provenance.lineage_hints), source_system,
    and the first identity_key. Raises if no mapping exists — the demo path
    refuses to silently invent mappings.
    """
    vendor = ""
    for hint in pipe.get("provenance", {}).get("lineage_hints", []):
        if isinstance(hint, str) and hint.startswith("vendor:"):
            vendor = hint.split(":", 1)[1]
            break
    source_system = str(pipe.get("source_system", ""))
    identity_keys = list(pipe.get("identity_keys") or [])
    key = _key_for(vendor, source_system, identity_keys)
    mappings = MAPPINGS.get(key)
    if not mappings:
        raise KeyError(
            f"No field mapping for pipe vendor={vendor} source_system={source_system} "
            f"identity_keys={identity_keys} key={key}. "
            f"Add an entry to app/ingest/mappings.py MAPPINGS or fix the pipe metadata."
        )
    return mappings
