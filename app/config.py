"""
AAM Configuration - Central settings management.

All configuration values read from environment variables with sensible defaults.
"""
import os


class Settings:
    """Application settings from environment variables."""

    def __init__(self):
        self.DATABASE_URL: str = os.environ.get("AAM_DATABASE_URL", "aam.db")
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
        self.DCL_INGEST_URL: str = os.environ.get(
            "AAM_DCL_INGEST_URL", "/api/dcl/ingest"
        )
        self.RUNNER_JOB_TIMEOUT_S: int = int(
            os.environ.get("AAM_RUNNER_JOB_TIMEOUT_S", "300")
        )
        # Base URL for self-referencing HTTP calls (Runner → DCL ingest)
        self.BASE_URL: str = os.environ.get(
            "AAM_BASE_URL", "http://127.0.0.1:8000"
        )


settings = Settings()
