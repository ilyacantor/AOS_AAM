"""
AAM Configuration - Central settings management.

All configuration values read from environment variables with sensible defaults.

DISP #24 — env_class coupling guard:
  Every prod-coupled config value (DCL endpoint, Farm endpoint, vendor
  sim endpoints, tenant entity IDs, webhook secrets) is tagged with its
  environment class. AAM refuses to start when classes are mixed —
  e.g., a prod DCL endpoint paired with a sim vendor endpoint, or a
  demo tenant_entity_id paired with prod DCL.

  Two same-class prod-pollution incidents (WP12a'-cleanup 942 rows,
  DISP #24 incident 1.235M rows) had the same root cause: a single
  env-bound value drifted independently from the rest, the operator
  didn't notice at launch, and the system happily wrote sim data to
  prod. The structural fix is to refuse the drift at startup, not to
  cleanup after.

  Three env classes:
    DEV         — local development. DCL :8104, Farm :8003, sim creds,
                  demo tenant_entity_ids.
    PROD_DEMO   — prod DCL but writing real-customer data (no sim/demo
                  identities). Used for prod ops where AAM ingests for
                  real-tenant entity IDs.
    AMBIGUOUS   — value doesn't carry strong class signal (e.g., empty
                  env var, unknown hostname). Treated as compatible
                  with any class.
"""
import os
import re


# ---------------------------------------------------------------------------
# DISP #24 env_class coupling guard
# ---------------------------------------------------------------------------

# Three env classes. UNKNOWN means "no strong class signal" — compatible
# with everything (e.g., unset env vars, custom hostnames operator wires up).
# DEV = local dev stack. PROD_DEMO = prod DCL serving real tenants.
_DEV = "DEV"
_PROD_DEMO = "PROD_DEMO"
_UNKNOWN = "UNKNOWN"


# Known sim/demo tenant_entity_id values. AAM's per-adapter binding (post
# WP12a'-cleanup) uses these strings to tag webhook receipts. If any of
# them flows into prod DCL, that's a class violation.
_DEMO_TENANT_IDS = frozenset({
    "finops-demo-co", "techedge-25kh", "techflow-n4ae", "aerosystems-2h05",
    "techflow-n4qe", "helixcorp-c2k4", "aeroworks-gcm3", "networks-lo0u",
    "techcorp-bn7a", "apexworks-2cly", "cloudlabs-1t2p",
})


def _classify_url(url: str, dev_ports: set[int], prod_ports: set[int]) -> str:
    """Classify a URL by its port. Returns DEV / PROD_DEMO / UNKNOWN."""
    if not url:
        return _UNKNOWN
    m = re.search(r":(\d{2,5})(?:/|$)", url)
    if not m:
        return _UNKNOWN
    port = int(m.group(1))
    if port in dev_ports:
        return _DEV
    if port in prod_ports:
        return _PROD_DEMO
    return _UNKNOWN


def _classify_tenant_id(tenant_id: str) -> str:
    """Classify a tenant_entity_id string."""
    if not tenant_id or not tenant_id.strip():
        return _UNKNOWN
    if tenant_id.strip().lower() in _DEMO_TENANT_IDS:
        return _DEV
    return _PROD_DEMO


def _classify_env_and_assert_coherent() -> None:
    """Inspect every prod-coupled env var, tag with env_class, refuse mismatch.

    Two same-class prod-pollution incidents (WP12a'-cleanup 942 rows,
    DISP #24 1.235M rows) had identical root cause: one env var drifted
    out of step. The fix is to make drift impossible at startup.
    """
    # Endpoint URLs: dev ports = 8104 (DCL dev), 8003 (Farm), 8104 (DCL dev
    # frontend implicit); prod port = 8004 (DCL prod). The Farm port 8003 is
    # shared dev/prod because Farm itself isn't tenant-bound.
    endpoint_classes = {
        "DCL_URL": _classify_url(
            os.environ.get("DCL_URL", ""),
            dev_ports={8104}, prod_ports={8004},
        ),
        # Vendor sim endpoints — by convention point at Farm port 8003
        # /sims/<vendor> in dev, or at real vendor cloud in prod.
        "WORKATO_BASE_URL": _classify_url(
            os.environ.get("WORKATO_BASE_URL", ""),
            dev_ports={8003}, prod_ports=set(),
        ),
        "BOOMI_BASE_URL": _classify_url(
            os.environ.get("BOOMI_BASE_URL", ""),
            dev_ports={8003}, prod_ports=set(),
        ),
        "FARM_URL": _classify_url(
            os.environ.get("FARM_URL", ""),
            dev_ports={8003}, prod_ports=set(),
        ),
    }
    # Tenant bindings — demo IDs are DEV, anything else is PROD_DEMO.
    tenant_classes = {
        "WORKATO_TENANT_ENTITY_ID": _classify_tenant_id(
            os.environ.get("WORKATO_TENANT_ENTITY_ID", "")
        ),
        "BOOMI_TENANT_ENTITY_ID": _classify_tenant_id(
            os.environ.get("BOOMI_TENANT_ENTITY_ID", "")
        ),
    }
    all_classes = {**endpoint_classes, **tenant_classes}
    # Filter to definite classes (drop UNKNOWN — those carry no signal).
    definite = {k: v for k, v in all_classes.items() if v != _UNKNOWN}
    if not definite:
        return  # No definite class anywhere → operator's call, allow.
    distinct = set(definite.values())
    if len(distinct) > 1:
        # Class mismatch. Build a clear breakdown.
        by_class: dict[str, list[str]] = {}
        for var, cls in definite.items():
            by_class.setdefault(cls, []).append(var)
        breakdown = "; ".join(
            f"{cls}=[{', '.join(sorted(vars))}]"
            for cls, vars in sorted(by_class.items())
        )
        raise RuntimeError(
            "FATAL: refusing to start. AAM env_class coupling guard "
            "(DISP #24) detected mixed environment classes: " + breakdown +
            ". Two prod-pollution incidents in a week (WP12a'-cleanup 942 rows, "
            "DISP #24 1.235M rows on 2026-05-17) had the same root cause: "
            "one env var drifted out of step. Every prod-coupled env var must "
            "carry the same class — either all DEV (dev DCL :8104 + sim "
            "vendor URLs at Farm :8003 + demo tenant IDs) or all PROD_DEMO "
            "(prod DCL :8004 + real vendor cloud URLs + non-demo tenant IDs). "
            "Fix the offending env var(s) in the pm2 launch command, not in "
            "this guard."
        )


class Settings:
    """Application settings from environment variables."""

    def __init__(self):
        self.AOD_PAYLOAD_FILE: str = os.environ.get("AAM_AOD_PAYLOAD_FILE", "aod_last_payload.json")
        self.LOG_LEVEL: str = os.environ.get("AAM_LOG_LEVEL", "INFO")
        self.DRIFT_LATENCY_THRESHOLD_MS: float = float(
            os.environ.get("AAM_DRIFT_LATENCY_THRESHOLD_MS", "1000")
        )
        self.DRIFT_CONSUMER_LAG_THRESHOLD: int = int(
            os.environ.get("AAM_DRIFT_CONSUMER_LAG_THRESHOLD", "10000")
        )
        self.DRIFT_CONNECTION_TIMEOUT_S: int = int(
            os.environ.get("AAM_DRIFT_CONNECTION_TIMEOUT_S", "30")
        )
        # Runner / DCL ingestion
        # DCL_URL is required — no fallback. A missing DCL_URL means every job
        # would silently route to localhost and appear to succeed before failing.
        dcl_base = os.environ.get("DCL_URL", "").rstrip("/")
        if not dcl_base:
            raise RuntimeError(
                "FATAL: DCL_URL must be set. "
                "AAM cannot ingest data or dispatch pipes without a configured DCL endpoint."
            )
        # DISP #24 env_class guard — refuse mixed classes at startup.
        _classify_env_and_assert_coherent()
        self.DCL_INGEST_URL: str = f"{dcl_base}/api/dcl/ingest"
        self.DCL_EXPORT_PIPES_URL: str = f"{dcl_base}/api/dcl/export-pipes"
        self.DCL_DISPATCH_URL: str = f"{dcl_base}/api/dcl/export-pipes/dispatch"
        self.RUNNER_JOB_TIMEOUT_S: int = int(
            os.environ.get("AAM_RUNNER_JOB_TIMEOUT_S", "300")
        )
        # Base URL for self-referencing HTTP calls (Runner → DCL ingest)
        self.BASE_URL: str = os.environ.get(
            "AAM_BASE_URL", "http://127.0.0.1:5000"
        )
        # API key the Runner sends in x-api-key header to DCL.
        # Must be set via AAM_DCL_API_KEY env var. Empty string means
        # requests to DCL will fail authentication, which is the correct
        # behavior when no key is configured.
        self.DCL_API_KEY: str = os.environ.get("AAM_DCL_API_KEY", "")
        # Farm intake URL — where AAM dispatches JobManifests (Path 2).
        # Farm executes extraction and pushes data to DCL (Path 3).
        _farm_base = os.environ.get("FARM_INTAKE_URL", "").rstrip("/")
        if not _farm_base:
            raise RuntimeError(
                "FATAL: FARM_INTAKE_URL must be set. "
                "AAM cannot dispatch to Farm without a configured intake URL."
            )
        if not _farm_base.endswith("/api/farm/manifest-intake"):
            self.FARM_INTAKE_URL: str = _farm_base + "/api/farm/manifest-intake"
        else:
            self.FARM_INTAKE_URL: str = _farm_base
        # Batch endpoint for multi-manifest dispatch (one HTTP round-trip).
        self.FARM_BATCH_URL: str = self.FARM_INTAKE_URL + "/batch"
        # Maximum retries for transient Farm errors (502/503, connect errors).
        # After this many requeue cycles, the job is permanently failed.
        self.FARM_MAX_RETRIES: int = int(
            os.environ.get("AAM_FARM_MAX_RETRIES", "5")
        )
        # Base backoff in seconds between transient Farm retries.
        # Actual delay = base * 2^(retry_count - 1), capped at 5 minutes.
        self.FARM_RETRY_BACKOFF_S: int = int(
            os.environ.get("AAM_FARM_RETRY_BACKOFF_S", "10")
        )


settings = Settings()
