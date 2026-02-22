"""
AAM Configuration - Central settings management.

All configuration values read from environment variables with sensible defaults.
"""
import os


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


settings = Settings()
