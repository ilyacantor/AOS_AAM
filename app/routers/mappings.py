"""AAM mappings router — generic operator surface for AAM field-to-concept mappings.

GET  /api/aam/mappings          — list mapping packs (source field → AOS concept.property)
POST /api/aam/mappings/approve  — operator approves a mid-confidence mapping

Mapping packs are sourced from app/ingest/mappings.MAPPINGS (the same registry
that drives /api/aam/infer). The endpoint exposes them per pack so Console's
semantic-mapping view can render per-pipe field tables with confidence pills.

Approval is in-memory only — production replacement is the LLM-assisted
Semantic Field Mapper (Platform repo). The endpoint exists so the operator
can confirm a mid-confidence mapping without leaving Console.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..ingest.mappings import MAPPINGS, FieldMapping

router = APIRouter(tags=["mappings"])
_log = logging.getLogger("aam.routers.mappings")


# In-memory mapping approvals so the Console UI is interactive.
# Keyed by `{pack_key}::{source_field}` — same shape the prior demo used.
_MAPPING_APPROVALS: dict[str, dict[str, Any]] = {}


class ApproveMappingRequest(BaseModel):
    pack_key: str = Field(..., description="MAPPINGS dict key, e.g. workato::netsuite::vendor")
    source_field: str
    approved: bool = True


def _tier_for(confidence: float) -> str:
    if confidence >= 0.90:
        return "auto"
    if confidence >= 0.70:
        return "review"
    return "low"


def _rationale_for(pack_key: str, field: FieldMapping) -> str:
    """Operator-facing rationale.

    Auto rows return the canonical 'exact match' line; review rows include the
    raw score so the operator knows why the resolver paused. No special-case
    branding by vendor or scenario — the rationale is mechanical.
    """
    if field.confidence >= 0.90:
        return "Exact concept match; auto-applied."
    return (
        f"Resolver scored {field.confidence:.2f} for "
        f"{field.source_field} → {field.concept}.{field.property}; "
        f"needs operator confirmation."
    )


@router.get("/api/aam/mappings")
async def list_mappings() -> dict[str, Any]:
    """Return all mapping packs as `{packs: [{pack_key, display_name, fields}]}`.

    Each field row carries source_field, target concept.property, current
    confidence (post any operator approval), tier (auto/review/low), and a
    boolean `needs_click` so the UI can render an action button only where it
    matters. The returned `display_name` is the pack_key with `::` swapped for
    ` · ` — generic, no agent-specific labels.
    """
    packs: list[dict[str, Any]] = []
    for pack_key in sorted(MAPPINGS.keys()):
        fields: list[dict[str, Any]] = []
        for m in MAPPINGS[pack_key]:
            approval = _MAPPING_APPROVALS.get(f"{pack_key}::{m.source_field}")
            confidence = m.confidence
            if approval:
                confidence = approval["confidence"]
            tier = _tier_for(confidence)
            fields.append({
                "source_field": m.source_field,
                "concept": m.concept,
                "property": m.property,
                "confidence": confidence,
                "tier": tier,
                "approved": bool(approval and approval.get("approved")),
                "needs_click": tier == "review" and not (approval and approval.get("approved")),
                "rationale": _rationale_for(pack_key, m),
            })
        packs.append({
            "pack_key": pack_key,
            "display_name": pack_key.replace("::", " · "),
            "fields": fields,
        })
    return {"packs": packs, "count": len(packs)}


@router.post("/api/aam/mappings/approve")
async def approve_mapping(req: ApproveMappingRequest) -> dict[str, Any]:
    """Operator approves (or revokes) a mid-confidence mapping.

    On approval the confidence is promoted to 0.99 so downstream pipeline
    runs treat the mapping as authoritative. Stored in-memory; production
    persistence is deferred to the Semantic Field Mapper (Platform WP-8).

    On revocation (approved=False) the cached override is removed entirely,
    so the underlying registry confidence reasserts (e.g. invoice "amount"
    drops back to 0.78). This keeps the operator-driven approval lifecycle
    reversible — the same path Console offers if the operator un-confirms
    a field.
    """
    if req.pack_key not in MAPPINGS:
        raise HTTPException(status_code=404, detail=f"unknown pack_key {req.pack_key}")
    cache_key = f"{req.pack_key}::{req.source_field}"
    if req.approved:
        _MAPPING_APPROVALS[cache_key] = {"approved": True, "confidence": 0.99}
        confidence = 0.99
    else:
        _MAPPING_APPROVALS.pop(cache_key, None)
        # Reasserted confidence is whatever MAPPINGS declared.
        confidence = next(
            (m.confidence for m in MAPPINGS[req.pack_key] if m.source_field == req.source_field),
            0.0,
        )
    return {
        "pack_key": req.pack_key,
        "source_field": req.source_field,
        "approved": req.approved,
        "confidence": confidence,
    }


def _reset_approvals() -> int:
    """Test helper — clears the in-memory approval cache. Not exposed via HTTP."""
    cleared = len(_MAPPING_APPROVALS)
    _MAPPING_APPROVALS.clear()
    return cleared
