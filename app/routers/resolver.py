"""Resolver HITL Review endpoints.

GET  /api/aam/resolver/pending        — list pending HITL pairs for a tenant
POST /api/aam/resolver/decisions      — operator approves / rejects a pair
GET  /api/aam/resolver/audit          — audit trail for one HITL decision
GET  /api/aam/resolver/auto-matches   — list auto-applied matches (WS-2 B5)

The decision endpoint promotes approved pairs to canonical authority — every
downstream semantic_triples row with the proposed canonical_id gets its
resolution_method updated to `hitl_confirmed` at confidence 0.99. The DCL
write path is shared with the demo path; AAM owns the resolution_method /
resolution_confidence columns in semantic_triples (per A10 + I3).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import psycopg2.sql as psql

from ..db import hitl_store, supabase_client as sb

router = APIRouter(tags=["resolver"])
_log = logging.getLogger("aam.routers.resolver")


class DecisionRequest(BaseModel):
    hitl_queue_id: str = Field(..., description="The pending HITL row to finalize.")
    decision: str = Field(..., description="'approved' or 'rejected'")
    decided_by: str = Field(..., description="Operator id / email — required for the audit trail.")


@router.get("/api/aam/resolver/auto-matches")
async def list_auto_matches(
    tenant_id: str = Query(...),
    domain: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Return auto-applied resolver matches (confidence >= auto_threshold).

    Slide 8: auto-applied matches must be operator-visible with confidence,
    source pointers, match rule, and timestamp. This is the read path
    behind /ui/candidates Recent Matches.

    Identity is required (I2): no tenant_id, no listing.
    """
    if not tenant_id:
        raise HTTPException(status_code=422, detail="tenant_id is required")
    rows = hitl_store.list_auto_applied(
        tenant_id=tenant_id, domain=domain, limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "domain": domain,
        "count": len(rows),
        "auto_matches": rows,
    }


@router.get("/api/aam/resolver/pending")
async def list_pending(
    tenant_id: str = Query(...),
    entity_id: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Return pending HITL pairs scoped to tenant_id (+ optional entity_id / domain).

    Identity is required (I2): no tenant_id, no listing.
    """
    if not tenant_id:
        raise HTTPException(status_code=422, detail="tenant_id is required")
    rows = hitl_store.get_pending(
        tenant_id=tenant_id, entity_id=entity_id, domain=domain, limit=limit,
    )
    return {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "domain": domain,
        "count": len(rows),
        "pending": rows,
    }


@router.post("/api/aam/resolver/decisions")
async def post_decision(req: DecisionRequest) -> dict[str, Any]:
    """Approve or reject a pending HITL pair.

    On approval: flip every semantic_triple already written under the proposed
    canonical_id (for the same tenant/entity) to method=hitl_confirmed,
    confidence=0.99 — the human is now the source of truth.
    On rejection: leave the triples in place but mark the HITL row rejected so
    downstream consumers can filter / re-route.
    """
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")
    if not req.decided_by:
        raise HTTPException(status_code=422, detail="decided_by required for audit trail")
    try:
        row = hitl_store.decide(
            hitl_queue_id=req.hitl_queue_id,
            decision=req.decision,
            decided_by=req.decided_by,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    updated_triples = 0
    if req.decision == "approved":
        updated_triples = _promote_triples_to_confirmed(
            tenant_id=row["tenant_id"],
            entity_id=row["entity_id"],
            canonical_id=row["proposed_canonical_id"],
        )
        hitl_store.append_audit(
            hitl_queue_id=req.hitl_queue_id,
            event="triples_promoted",
            details={"updated_triples": updated_triples,
                     "new_method": "hitl_confirmed",
                     "new_confidence": 0.99},
            actor="aam.resolver",
        )
    return {
        "hitl_queue_id": req.hitl_queue_id,
        "decision": req.decision,
        "decided_by": req.decided_by,
        "status": row["status"],
        "tenant_id": row["tenant_id"],
        "entity_id": row["entity_id"],
        "proposed_canonical_id": row["proposed_canonical_id"],
        "triples_promoted": updated_triples,
    }


@router.get("/api/aam/resolver/audit")
async def get_audit(hitl_queue_id: str = Query(...)) -> dict[str, Any]:
    if not hitl_queue_id:
        raise HTTPException(status_code=422, detail="hitl_queue_id is required")
    row = hitl_store.get_by_id(hitl_queue_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"hitl_queue_id {hitl_queue_id} not found")
    audit_rows = hitl_store.get_audit(hitl_queue_id)
    return {
        "hitl_queue_id": hitl_queue_id,
        "tenant_id": row["tenant_id"],
        "entity_id": row["entity_id"],
        "domain": row["domain"],
        "status": row["status"],
        "confidence": row["confidence"],
        "proposed_canonical_id": row["proposed_canonical_id"],
        "audit": audit_rows,
    }


def _promote_triples_to_confirmed(*, tenant_id: str, entity_id: str, canonical_id: str) -> int:
    """Bulk-update semantic_triples rows where canonical_id matches.

    Sets resolution_method='manual' (DCL's vocab for human-confirmed) and
    resolution_confidence=0.99. Filters on resolution_method='fuzzy' since
    that's how AAM writes HITL-pending rows to PG (see triples.py
    _RESOLUTION_METHOD_TO_PG). Returns the number of rows updated; 0 if
    nothing matches — the triples may not exist yet (e.g., HITL row created
    from a unit test without triple writes).
    """
    rows = sb._execute_composed(
        psql.SQL("""
            UPDATE semantic_triples
               SET resolution_method = 'manual',
                   resolution_confidence = 0.99
             WHERE tenant_id::text = %s
               AND entity_id = %s
               AND canonical_id::text = %s
               AND resolution_method = 'fuzzy'
             RETURNING id
        """),
        params=(tenant_id, entity_id, canonical_id),
        fetch=True,
    )
    return len(rows)
