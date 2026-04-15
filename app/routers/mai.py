"""
Mai status endpoint — returns structured AAM state for cross-module orchestration.

GET /mai/status?tenant_id=<id> returns manifest counts, connection state,
and health for a given tenant.
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional

from ..db.mai_status import get_mai_status
from ..logger import get_logger

_log = get_logger("routers.mai")

router = APIRouter(prefix="/mai", tags=["Mai"])


class ManifestCounts(BaseModel):
    total: int
    succeeded: int
    failed: int
    pending: int


class SSOPending(BaseModel):
    count: int
    items: list[dict]


class ConnectionInfo(BaseModel):
    pipe_id: str
    source_system: str
    fabric_plane: Optional[str]
    modality: str
    transport_kind: str


class MaiStatusResponse(BaseModel):
    module: str
    tenant_id: str
    manifests: ManifestCounts
    sso_pending: SSOPending
    connections: list[ConnectionInfo]
    last_execution_at: Optional[str]
    healthy: bool


@router.get("/status", response_model=MaiStatusResponse)
async def mai_status(
    tenant_id: str = Query(..., description="Tenant identifier (maps to AOD snapshot_name)"),
):
    """Return AAM manifest and connection state for a given tenant.

    Queries runner_jobs, connection_candidates, declared_pipes, and
    drift_events scoped to the aod_run_ids associated with the tenant.
    """
    result = get_mai_status(tenant_id)
    return MaiStatusResponse(**result)
