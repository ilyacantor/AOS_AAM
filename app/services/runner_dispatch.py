"""
Runner Dispatch Service — builds Job Manifests and dispatches runner jobs.

AAM is the Control Plane (RACI Row 76: Fabric Plane Connection, A/R).
The Runner is the Muscle (ephemeral worker).  Data bytes never touch AAM.

Flow: build_manifest() → dispatch_job() → runner executes → callback
"""
from datetime import datetime
from typing import Optional

from ..config import settings
from ..logger import get_logger
from ..db import (
    get_pipe,
    list_pipes,
)
from ..db.runner_jobs import create_runner_job, update_runner_status, list_runner_jobs
from ..models import (
    JobManifest,
    SourceSpec,
    TargetSpec,
    RunLimits,
    FabricPlane,
    TransportKind,
)

_log = get_logger("services.runner_dispatch")

# Map fabric plane + transport kind to adapter type string
_ADAPTER_MAP = {
    FabricPlane.API_GATEWAY: "rest_api",
    FabricPlane.IPAAS: "ipaas",
    FabricPlane.EVENT_BUS: "kafka",
    FabricPlane.DATA_WAREHOUSE: "jdbc",
}

_TRANSPORT_ADAPTER = {
    TransportKind.API: "rest_api",
    TransportKind.EVENT_STREAM: "kafka",
    TransportKind.TABLE: "jdbc",
    TransportKind.FILE: "file",
    TransportKind.WEBHOOK: "webhook",
}

_seq_counter: Optional[int] = None


def _init_seq_counter() -> int:
    """Initialize sequence counter from the max existing job number in the DB."""
    try:
        jobs = list_runner_jobs(limit=1)
        if jobs:
            last_id = jobs[0].get("job_id", "")
            parts = last_id.rsplit("_", 1)
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
    except Exception:
        pass
    return 0


def _next_run_id(source_system: str) -> str:
    """Generate a unique run_id: run_{YYYYMMDD}_{system}_{seq:03d}"""
    global _seq_counter
    if _seq_counter is None:
        _seq_counter = _init_seq_counter()
    _seq_counter += 1
    date_str = datetime.utcnow().strftime("%Y%m%d")
    safe_system = source_system.lower().replace(" ", "_")[:20]
    return f"run_{date_str}_{safe_system}_{_seq_counter:03d}"


def build_manifest(
    pipe: dict,
    trigger: str = "manual",
    *,
    snapshot_name: Optional[str] = None,
    farm_verification: bool = False,
) -> JobManifest:
    """Build an immutable Job Manifest from a pipe definition.

    The manifest contains vault references for secrets — never plaintext.
    """
    pipe_id = pipe["pipe_id"]
    source_system = pipe.get("source_system", "unknown")
    fabric_plane = pipe.get("fabric_plane", "")
    transport_kind = pipe.get("transport_kind", "")
    endpoint_ref = pipe.get("endpoint_ref", {})

    # Resolve adapter type: prefer transport_kind, fall back to fabric_plane
    adapter = _TRANSPORT_ADAPTER.get(transport_kind, "")
    if not adapter:
        adapter = _ADAPTER_MAP.get(fabric_plane, "rest_api")

    # Credentials reference (vault URI) — from pipe's access info
    access = pipe.get("access") or {}
    credentials_ref = access.get("auth_ref")

    run_id = _next_run_id(source_system)

    return JobManifest(
        run_id=run_id,
        source=SourceSpec(
            pipe_id=pipe_id,
            system=source_system,
            adapter=adapter,
            endpoint_ref=endpoint_ref,
            credentials_ref=credentials_ref,
        ),
        target=TargetSpec(
            dcl_url=settings.DCL_INGEST_URL,
            snapshot_name=snapshot_name,
        ),
        provenance={
            "run_timestamp": datetime.utcnow().isoformat(),
            "triggered_by": trigger,
        },
        limits=RunLimits(timeout_seconds=settings.RUNNER_JOB_TIMEOUT_S),
        farm_verification=farm_verification,
    )


def dispatch_job(manifest: JobManifest) -> str:
    """Dispatch a runner job: store manifest and mark as queued.

    v1: job is stored and returned.  The caller (or inline runner) executes it.
    v2: job would be enqueued to a background worker pool.
    """
    job_id = create_runner_job(manifest.model_dump())
    _log.info("Dispatched runner job %s for pipe %s", job_id, manifest.source.pipe_id)
    return job_id


def dispatch_pipe(
    pipe_id: str,
    trigger: str = "manual",
    *,
    snapshot_name: Optional[str] = None,
    farm_verification: bool = False,
) -> dict:
    """High-level: load pipe → build manifest → dispatch.  Returns job summary."""
    pipe = get_pipe(pipe_id)
    if not pipe:
        raise ValueError(f"Pipe {pipe_id} not found")

    manifest = build_manifest(
        pipe,
        trigger,
        snapshot_name=snapshot_name,
        farm_verification=farm_verification,
    )
    job_id = dispatch_job(manifest)

    return {
        "job_id": job_id,
        "run_id": manifest.run_id,
        "pipe_id": pipe_id,
        "status": "queued",
        "trigger": trigger,
    }


def dispatch_batch(
    pipe_ids: list[str],
    trigger: str = "manual",
) -> list[dict]:
    """Dispatch runner jobs for multiple pipes.  Returns list of job summaries."""
    results = []
    for pid in pipe_ids:
        try:
            result = dispatch_pipe(pid, trigger)
            results.append(result)
        except Exception as exc:
            _log.warning("Failed to dispatch pipe %s: %s", pid, exc)
            results.append({"pipe_id": pid, "status": "error", "error": str(exc)})
    return results
