"""
Runner Dispatch Service — builds Job Manifests and dispatches to Farm.

AAM is the Control Plane (RACI Row 76: Fabric Plane Connection, A/R).
Farm is the Execution Engine.  Data bytes never touch AAM.

Flow: build_manifest() → dispatch_job() → dispatch_to_farm() → Farm executes
"""
import httpx
from datetime import datetime
from typing import Optional

from ..config import settings
from ..logger import get_logger
from ..db import (
    get_pipe,
    get_candidate,
    list_candidates,
    list_pipes,
)
from ..db.runner_jobs import create_runner_job, create_runner_jobs_batch, update_runner_status, list_runner_jobs
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

VALID_CATEGORIES = {"crm", "erp", "billing", "hr", "support", "devops", "observability", "infrastructure"}

CATEGORY_SYNONYMS = {
    "hcm": "hr",
    "human_capital": "hr",
    "data": "infrastructure",
    "warehouse": "infrastructure",
    "lake": "infrastructure",
    "analytics": "infrastructure",
    "bi": "infrastructure",
    "itsm": "support",
    "helpdesk": "support",
    "monitoring": "observability",
    "apm": "observability",
    "ci_cd": "devops",
    "scm": "devops",
    "project_management": "devops",
    "collaboration": "support",
    "finance": "erp",
    "accounting": "erp",
    "payments": "billing",
    "subscription": "billing",
    "idp": "infrastructure",
    "saas": "support",
    "security": "infrastructure",
}

VENDOR_CATEGORY = {
    "salesforce": "crm",
    "hubspot": "crm",
    "pipedrive": "crm",
    "zoho": "crm",
    "sap": "erp",
    "oracle": "erp",
    "netsuite": "erp",
    "workday": "hr",
    "bamboohr": "hr",
    "adp": "hr",
    "zendesk": "support",
    "freshdesk": "support",
    "intercom": "support",
    "zoom": "support",
    "slack": "support",
    "jira": "devops",
    "atlassian": "devops",
    "trello": "devops",
    "asana": "devops",
    "basecamp": "devops",
    "notion": "devops",
    "miro": "devops",
    "github": "devops",
    "gitlab": "devops",
    "datadog": "observability",
    "newrelic": "observability",
    "splunk": "observability",
    "stripe": "billing",
    "chargebee": "billing",
    "recurly": "billing",
    "snowflake": "infrastructure",
    "bigquery": "infrastructure",
    "redshift": "infrastructure",
    "databricks": "infrastructure",
    "aws": "infrastructure",
    "azure": "infrastructure",
    "gcp": "infrastructure",
    "kong": "infrastructure",
    "apigee": "infrastructure",
    "celigo": "infrastructure",
    "mulesoft": "infrastructure",
    "tray": "infrastructure",
    "aws eventbridge": "infrastructure",
    "bytedance": "support",
    "tiktok": "support",
    "docusign": "erp",
    "surveymonkey": "support",
    "momentive": "support",
    "microsoft": "support",
    "hipchat": "support",
}


def normalize_category(raw_category: Optional[str], vendor: Optional[str] = None) -> Optional[str]:
    """Normalize a category to the closed vocabulary. Returns None if unclassifiable."""
    if raw_category:
        cat = raw_category.lower().strip()
        if cat in VALID_CATEGORIES:
            return cat
        mapped = CATEGORY_SYNONYMS.get(cat)
        if mapped:
            return mapped

    if vendor:
        v = vendor.lower().strip()
        vendor_cat = VENDOR_CATEGORY.get(v)
        if vendor_cat:
            return vendor_cat

    return None


_seq_counter: Optional[int] = None


def _init_seq_counter() -> int:
    """Initialize sequence counter from the max existing job number in the DB."""
    try:
        from ..db import supabase_client as sb
        from psycopg2 import sql as psql
        query = psql.SQL(
            "SELECT MAX(CAST(SUBSTRING(job_id FROM '([0-9]+)$') AS INTEGER)) as mx FROM {}"
        ).format(sb._ident("runner_jobs"))
        rows = sb._execute_composed(query)
        if rows and rows[0].get("mx") is not None:
            return int(rows[0]["mx"])
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
    Uses DeclaredPipe.pipe_id (via matched_pipe_id) as the canonical pipe_id
    so the manifest aligns with the DCL export (critical for late-binding join).
    """
    # Use DeclaredPipe pipe_id for manifest alignment with export
    pipe_id = pipe.get("matched_pipe_id") or pipe["pipe_id"]
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

    raw_category = pipe.get("category") or pipe.get("app_category") or None
    vendor = pipe.get("source_system") or pipe.get("vendor_name") or None
    if not raw_category:
        candidate = get_candidate(pipe.get("pipe_id", ""))
        if candidate:
            raw_category = candidate.get("category") or None
            vendor = vendor or candidate.get("vendor_name")
    category = normalize_category(raw_category, vendor)

    return JobManifest(
        run_id=run_id,
        source=SourceSpec(
            pipe_id=pipe_id,
            system=source_system,
            adapter=adapter,
            category=category,
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
    """High-level: load pipe → build manifest → dispatch.

    Returns job summary including the manifest for Farm dispatch.
    """
    pipe = get_pipe(pipe_id)
    if not pipe:
        raise ValueError(f"Pipe {pipe_id} not found")

    if not snapshot_name:
        try:
            from ..db.handoff import list_handoff_logs
            handoffs = list_handoff_logs(limit=1)
            if handoffs:
                snapshot_name = handoffs[0].get("snapshot_name")
        except Exception:
            pass

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
        "pipe_id": manifest.source.pipe_id,
        "status": "queued",
        "trigger": trigger,
        "_manifest": manifest,
    }


def dispatch_batch(
    pipe_ids: list[str],
    trigger: str = "manual",
) -> list[dict]:
    """Dispatch runner jobs for multiple pipes using bulk insert.

    Bulk-fetches all pipes in one query, builds manifests, then bulk-inserts.
    Returns list of job summaries with _manifest for Farm dispatch.
    """
    from ..db.handoff import list_handoff_logs

    all_pipes = list_pipes()
    pipe_map = {p["pipe_id"]: p for p in all_pipes}

    all_candidates = list_candidates()
    candidate_map = {c["candidate_id"]: c for c in all_candidates}
    for p in all_pipes:
        cand = candidate_map.get(p["pipe_id"])
        raw_cat = p.get("category") or (cand.get("category") if cand else None)
        vendor = p.get("source_system") or (cand.get("vendor_name") if cand else None)
        p["category"] = normalize_category(raw_cat, vendor)

    current_snapshot: Optional[str] = None
    try:
        handoffs = list_handoff_logs(limit=1)
        if handoffs:
            current_snapshot = handoffs[0].get("snapshot_name")
    except Exception as exc:
        _log.warning("Failed to resolve snapshot_name for dispatch: %s", exc)

    manifests_data = []
    manifest_objects = []
    results = []
    errors = []

    for pid in pipe_ids:
        try:
            pipe = pipe_map.get(pid)
            if not pipe:
                errors.append({"pipe_id": pid, "status": "error", "error": f"Pipe {pid} not found"})
                continue
            if not pipe.get("category"):
                errors.append({"pipe_id": pid, "status": "skipped", "error": "Unclassified category — incomplete inference, not dispatchable"})
                continue
            manifest = build_manifest(pipe, trigger, snapshot_name=current_snapshot)
            manifests_data.append(manifest.model_dump())
            manifest_objects.append(manifest)
            results.append({
                "job_id": manifest.run_id,
                "run_id": manifest.run_id,
                "pipe_id": manifest.source.pipe_id,
                "status": "queued",
                "trigger": trigger,
                "_manifest": manifest,
            })
        except Exception as exc:
            _log.warning("Failed to build manifest for pipe %s: %s", pid, exc)
            errors.append({"pipe_id": pid, "status": "error", "error": str(exc)})

    if manifests_data:
        try:
            create_runner_jobs_batch(manifests_data)
            _log.info("Bulk-dispatched %d runner jobs", len(manifests_data))
        except Exception as exc:
            _log.error("Bulk insert failed: %s", exc)
            for r in results:
                r["status"] = "error"
                r["error"] = f"Bulk insert failed: {exc}"

    return results + errors


async def dispatch_to_farm(manifest: JobManifest) -> dict:
    """POST a JobManifest to Farm's intake endpoint (Path 2).

    AAM dispatches instructions to Farm.  Farm executes extraction and
    pushes data to DCL (Path 3).  The manifest's target.dcl_url tells
    Farm where to deliver — it is NOT the manifest's own destination.
    """
    farm_url = settings.FARM_INTAKE_URL
    payload = manifest.model_dump()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(farm_url, json=payload)

        if resp.status_code in (200, 201, 202):
            body = resp.json()
            _log.info(
                "Manifest dispatched to Farm: run_id=%s pipe_id=%s status=%d",
                manifest.run_id, manifest.source.pipe_id, resp.status_code,
            )
            update_runner_status(manifest.run_id, "dispatched")
            return {"status": "dispatched", "farm_response": body}

        _log.warning(
            "Farm rejected manifest: run_id=%s status=%d body=%s",
            manifest.run_id, resp.status_code, resp.text[:500],
        )
        return {
            "status": "farm_error",
            "error": f"Farm returned {resp.status_code}: {resp.text[:500]}",
        }

    except httpx.ConnectError as exc:
        _log.warning("Farm unreachable at %s: %s", farm_url, exc)
        return {"status": "farm_unreachable", "error": f"Farm unreachable: {exc}"}
