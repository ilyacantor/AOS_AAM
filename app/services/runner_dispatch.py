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


def _generate_dispatch_id(aod_run_id: str) -> str:
    """Unique per dispatch cycle. Farm groups all pipes by this shared ID."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"aam_{aod_run_id}_{ts}"


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
    """Normalize a category to a known vocabulary, with passthrough fallback.

    Priority: VALID_CATEGORIES → CATEGORY_SYNONYMS → VENDOR_CATEGORY → raw passthrough.
    Only returns None when both raw_category and vendor are empty/unmapped.
    """
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

    # Pass through non-empty categories even if unrecognized (e.g. "other")
    # so pipes aren't silently skipped from dispatch
    if raw_category:
        return raw_category.lower().strip()

    return None


def build_manifest(
    pipe: dict,
    trigger: str = "manual",
    *,
    snapshot_name: Optional[str] = None,
    aod_run_id: Optional[str] = None,
    farm_verification: bool = False,
    run_id: Optional[str] = None,
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
        adapter = _ADAPTER_MAP.get(fabric_plane, "")
    if not adapter:
        _log.warning(
            "No adapter mapping for pipe=%s (transport_kind=%r, fabric_plane=%r) — "
            "Farm will receive adapter='' and may reject the manifest.",
            pipe_id, transport_kind, fabric_plane,
        )
        adapter = ""

    # Credentials reference (vault URI) — from pipe's access info
    access = pipe.get("access") or {}
    credentials_ref = access.get("auth_ref")

    if run_id is None:
        raise ValueError(
            f"run_id is required for manifest building (pipe={pipe_id}). "
            "Pass aod_run_id from AOD handoff or use a stable per-dispatch identifier."
        )

    raw_category = pipe.get("category") or pipe.get("app_category") or None
    vendor = pipe.get("source_system") or pipe.get("vendor_name") or None
    if not raw_category:
        candidate = get_candidate(pipe.get("pipe_id", ""))
        if candidate:
            raw_category = candidate.get("category") or None
            vendor = vendor or candidate.get("vendor_name")
    category = normalize_category(raw_category, vendor)

    tenant_id = snapshot_name or aod_run_id or "default"

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
            tenant_id=tenant_id,
        ),
        provenance={
            "aod_run_id": aod_run_id,
            "snapshot_name": snapshot_name,
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

    # Always fetch aod_run_id from the latest handoff
    try:
        from ..db.handoff import list_handoff_logs
        handoffs = list_handoff_logs(limit=1)
        if not handoffs:
            raise ValueError(
                "No AOD handoff found. Run AOD handoff first before dispatching pipes."
            )

        aod_run_id = handoffs[0].get("aod_run_id")
        snapshot_name = snapshot_name or handoffs[0].get("snapshot_name")

        if not aod_run_id:
            raise ValueError(
                "Latest handoff has no aod_run_id. Cannot dispatch without a run identifier."
            )

    except Exception as exc:
        _log.error(
            "Failed to fetch aod_run_id for dispatch (pipe=%s): %s",
            pipe_id, exc,
        )
        raise

    manifest = build_manifest(
        pipe,
        trigger,
        snapshot_name=snapshot_name,
        aod_run_id=aod_run_id,
        farm_verification=farm_verification,
        run_id=_generate_dispatch_id(aod_run_id),
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

    # Always fetch aod_run_id from the latest handoff for batch grouping
    try:
        handoffs = list_handoff_logs(limit=1)
        if not handoffs:
            raise ValueError(
                "No AOD handoff found. Run AOD handoff first before dispatching pipes."
            )

        current_aod_run_id = handoffs[0].get("aod_run_id")
        current_snapshot = handoffs[0].get("snapshot_name")

        if not current_aod_run_id:
            raise ValueError(
                "Latest handoff has no aod_run_id. Cannot dispatch without a run identifier."
            )

    except Exception as exc:
        _log.error("Failed to fetch aod_run_id for batch dispatch: %s", exc)
        raise

    # Generate one dispatch-cycle ID shared by all manifests in this batch
    batch_run_id = _generate_dispatch_id(current_aod_run_id)

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

            manifest = build_manifest(pipe, trigger, snapshot_name=current_snapshot, aod_run_id=current_aod_run_id, run_id=batch_run_id)

            manifests_data.append(manifest.model_dump())
            manifest_objects.append(manifest)
            results.append({
                "job_id": manifest.source.pipe_id,  # Use pipe_id as unique key for AAM database
                "run_id": manifest.run_id,  # Shared aod_run_id for Farm batch grouping
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


def _classify_farm_error(status_code: int, body: str, content_type: str) -> tuple[str, str]:
    """Return (error_class, human_readable_detail) from a non-2xx Farm response.

    Distinguishes:
      SLEEPING_APP   — Replit / platform "app not running" HTML page
      GATEWAY_ERROR  — reverse-proxy 502/503 (Render, nginx) returned HTML
      AUTH_FAILURE   — 401/403
      FARM_APP_ERROR — Farm returned a structured JSON error
      UNKNOWN_ERROR  — anything else
    """
    is_html = "text/html" in content_type or body.lstrip().startswith("<!DOCTYPE") or body.lstrip().startswith("<html")

    if is_html:
        # Extract <title> for a one-line summary
        import re
        title_match = re.search(r"<title[^>]*>([^<]{1,120})</title>", body, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "(no title)"
        # Replit sleeping-app page has a distinctive title/phrase
        if "not running" in body.lower() or "deploy this app" in body.lower():
            return "SLEEPING_APP", f"Platform reported app is not running (title: {title!r}). Check FARM_INTAKE_URL — likely points to a dormant Replit instance."
        return "GATEWAY_ERROR", f"Reverse-proxy or gateway returned HTML {status_code} (title: {title!r}). Farm process may have crashed or OOM-restarted."

    if status_code in (401, 403):
        return "AUTH_FAILURE", f"HTTP {status_code} — Farm rejected the request as unauthorized. Check shared secret / API key configuration."

    # Try to extract a JSON error message
    try:
        import json as _json
        err_body = _json.loads(body)
        detail = err_body.get("detail") or err_body.get("error") or err_body.get("message") or str(err_body)
        return "FARM_APP_ERROR", f"Farm returned HTTP {status_code}: {str(detail)[:300]}"
    except Exception as _e:
        _log.debug("Could not parse Farm error response body as JSON: %s", _e)

    return "UNKNOWN_ERROR", f"HTTP {status_code}: {body[:300]}"


async def dispatch_to_farm(manifest: JobManifest) -> dict:
    """POST a JobManifest to Farm's intake endpoint (Path 2).

    AAM dispatches instructions to Farm.  Farm executes extraction and
    pushes data to DCL (Path 3).  The manifest's target.dcl_url tells
    Farm where to deliver — it is NOT the manifest's own destination.
    """
    farm_url = settings.FARM_INTAKE_URL
    payload = manifest.model_dump()
    attempt_at = datetime.utcnow().isoformat() + "Z"

    try:
        async with httpx.AsyncClient(timeout=float(settings.RUNNER_JOB_TIMEOUT_S)) as client:
            resp = await client.post(farm_url, json=payload)

        if resp.status_code in (200, 201, 202):
            body = resp.json()
            _log.info(
                "Manifest dispatched to Farm: run_id=%s pipe_id=%s status=%d url=%s",
                manifest.run_id, manifest.source.pipe_id, resp.status_code, farm_url,
            )
            update_runner_status(manifest.source.pipe_id, "dispatched")
            return {"status": "dispatched", "farm_response": body}

        content_type = resp.headers.get("content-type", "")
        error_class, detail = _classify_farm_error(resp.status_code, resp.text, content_type)
        error_msg = (
            f"[{error_class}] Farm at {farm_url!r} returned HTTP {resp.status_code} "
            f"at {attempt_at}. {detail}"
        )
        _log.warning(
            "Farm dispatch failed: run_id=%s pipe_id=%s url=%s status=%d "
            "error_class=%s content_type=%r detail=%s",
            manifest.run_id, manifest.source.pipe_id, farm_url, resp.status_code,
            error_class, content_type, detail,
        )
        update_runner_status(manifest.source.pipe_id, "failed", error_message=error_msg)
        return {
            "status": "farm_error",
            "error_class": error_class,
            "error": error_msg,
        }

    except httpx.ConnectError as exc:
        error_msg = (
            f"[CONNECT_ERROR] Farm at {farm_url!r} was unreachable at {attempt_at}: {exc}. "
            f"Verify FARM_INTAKE_URL points to the live Render service, not a dormant instance."
        )
        _log.warning("Farm unreachable: run_id=%s url=%s error=%s", manifest.run_id, farm_url, exc)
        return {"status": "farm_unreachable", "error": error_msg}
