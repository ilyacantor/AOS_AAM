"""Tests for the DISP #24 env_class coupling guard at app/config.py.

Every prod-coupled env var is tagged with one of three classes:
  DEV         — dev DCL :8104, Farm :8003 (sim endpoints), demo tenant IDs
  PROD_DEMO   — prod DCL :8004, real vendor cloud URLs, real tenant IDs
  UNKNOWN     — no class signal (empty / unrecognized) — compatible with all

AAM refuses to start when any two declared classes mismatch.
"""
from __future__ import annotations

import importlib
import sys

import pytest


def _reimport_config(monkeypatch, **env):
    """Set env vars then force a fresh import of app.config."""
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    for mod_name in [m for m in sys.modules if m.startswith("app.config")]:
        del sys.modules[mod_name]
    return importlib.import_module("app.config")


# ---------- ALL-DEV: everything tagged dev → allowed ---------------------

def test_all_dev_classes_allowed(monkeypatch):
    config = _reimport_config(
        monkeypatch,
        DCL_URL="http://localhost:8104",
        FARM_INTAKE_URL="http://localhost:8003",
        WORKATO_BASE_URL="http://localhost:8003/sims/workato",
        BOOMI_BASE_URL="http://localhost:8003/sims/boomi",
        FARM_URL="http://localhost:8003",
        WORKATO_TENANT_ENTITY_ID="finops-demo-co",
        BOOMI_TENANT_ENTITY_ID="finops-demo-co",
    )
    assert config.settings.DCL_INGEST_URL == "http://localhost:8104/api/dcl/ingest"


# ---------- ALL-PROD: prod DCL + real tenant + no sim URLs → allowed -----

def test_prod_dcl_with_real_tenant_allowed(monkeypatch):
    config = _reimport_config(
        monkeypatch,
        DCL_URL="http://localhost:8004",
        FARM_INTAKE_URL="http://localhost:8003",
        WORKATO_BASE_URL=None,  # no sim URL → UNKNOWN, doesn't conflict
        BOOMI_BASE_URL=None,
        FARM_URL=None,
        WORKATO_TENANT_ENTITY_ID="real-customer-acme",
        BOOMI_TENANT_ENTITY_ID="real-customer-acme",
    )
    assert config.settings.DCL_INGEST_URL.startswith("http://localhost:8004")


# ---------- MIXED: the DISP #24 incident shape --------------------------

def test_disp24_incident_shape_refused(monkeypatch):
    """Prod DCL + sim vendor URLs + demo tenant — exactly what caused 1.235M-row pollution."""
    with pytest.raises(RuntimeError) as exc_info:
        _reimport_config(
            monkeypatch,
            DCL_URL="http://localhost:8004",
            FARM_INTAKE_URL="http://localhost:8003",
            WORKATO_BASE_URL="http://localhost:8003/sims/workato",
            BOOMI_BASE_URL="http://localhost:8003/sims/boomi",
            FARM_URL="http://localhost:8003",
            WORKATO_TENANT_ENTITY_ID="finops-demo-co",
            BOOMI_TENANT_ENTITY_ID="finops-demo-co",
        )
    msg = str(exc_info.value)
    assert "DISP #24" in msg
    assert "mixed environment classes" in msg
    assert "DEV" in msg and "PROD_DEMO" in msg
    assert "DCL_URL" in msg


# ---------- Each direction of single-var drift ---------------------------

def test_prod_dcl_with_demo_tenant_only_refused(monkeypatch):
    """Prod DCL + demo tenant (no sim URLs) — single-var drift, must refuse."""
    with pytest.raises(RuntimeError) as exc_info:
        _reimport_config(
            monkeypatch,
            DCL_URL="http://localhost:8004",
            FARM_INTAKE_URL="http://localhost:8003",
            WORKATO_BASE_URL=None,
            BOOMI_BASE_URL=None,
            FARM_URL=None,
            WORKATO_TENANT_ENTITY_ID="finops-demo-co",
            BOOMI_TENANT_ENTITY_ID=None,
        )
    assert "WORKATO_TENANT_ENTITY_ID" in str(exc_info.value)


def test_dev_dcl_with_real_tenant_refused(monkeypatch):
    """Dev DCL + real tenant — also a class mismatch, must refuse."""
    with pytest.raises(RuntimeError) as exc_info:
        _reimport_config(
            monkeypatch,
            DCL_URL="http://localhost:8104",
            FARM_INTAKE_URL="http://localhost:8003",
            WORKATO_BASE_URL=None,
            BOOMI_BASE_URL=None,
            FARM_URL=None,
            WORKATO_TENANT_ENTITY_ID="real-customer-acme",
            BOOMI_TENANT_ENTITY_ID=None,
        )
    assert "WORKATO_TENANT_ENTITY_ID" in str(exc_info.value)


def test_prod_dcl_with_sim_workato_url_refused(monkeypatch):
    """Prod DCL + sim vendor URL — webhook ingestion would route sim data to prod."""
    with pytest.raises(RuntimeError) as exc_info:
        _reimport_config(
            monkeypatch,
            DCL_URL="http://localhost:8004",
            FARM_INTAKE_URL="http://localhost:8003",
            WORKATO_BASE_URL="http://localhost:8003/sims/workato",
            BOOMI_BASE_URL=None,
            FARM_URL=None,
            WORKATO_TENANT_ENTITY_ID=None,
            BOOMI_TENANT_ENTITY_ID=None,
        )
    assert "WORKATO_BASE_URL" in str(exc_info.value)


# ---------- UNKNOWN class doesn't trigger mismatch -----------------------

def test_minimal_env_allowed(monkeypatch):
    """Only DCL_URL + FARM_INTAKE_URL set, no other class signals → allowed."""
    config = _reimport_config(
        monkeypatch,
        DCL_URL="http://localhost:8104",
        FARM_INTAKE_URL="http://localhost:8003",
        WORKATO_BASE_URL=None,
        BOOMI_BASE_URL=None,
        FARM_URL=None,
        WORKATO_TENANT_ENTITY_ID=None,
        BOOMI_TENANT_ENTITY_ID=None,
    )
    assert config.settings.DCL_INGEST_URL.startswith("http://localhost:8104")


def test_unrecognized_dcl_url_treated_as_unknown(monkeypatch):
    """Custom hostname for DCL → UNKNOWN class, doesn't conflict with anything."""
    config = _reimport_config(
        monkeypatch,
        DCL_URL="https://dcl-staging.example.com",
        FARM_INTAKE_URL="http://localhost:8003",
        WORKATO_TENANT_ENTITY_ID="finops-demo-co",
        BOOMI_TENANT_ENTITY_ID=None,
        WORKATO_BASE_URL=None,
        BOOMI_BASE_URL=None,
        FARM_URL=None,
    )
    # Should be allowed: tenant says DEV, DCL says UNKNOWN. No mismatch.
    assert "dcl-staging.example.com" in config.settings.DCL_INGEST_URL


# ---------- Every demo tenant_id is recognized ---------------------------

@pytest.mark.parametrize("demo", [
    "finops-demo-co", "techedge-25kh", "techflow-n4ae", "aerosystems-2h05",
    "FINOPS-DEMO-CO",  # case-insensitive
])
def test_demo_tenant_ids_recognized(monkeypatch, demo):
    """All known demo tenants must classify as DEV and conflict with prod DCL."""
    with pytest.raises(RuntimeError):
        _reimport_config(
            monkeypatch,
            DCL_URL="http://localhost:8004",
            FARM_INTAKE_URL="http://localhost:8003",
            WORKATO_TENANT_ENTITY_ID=demo,
            BOOMI_TENANT_ENTITY_ID=None,
            WORKATO_BASE_URL=None,
            BOOMI_BASE_URL=None,
            FARM_URL=None,
        )


# ---------- Each declared violation in the error message ----------------

def test_error_message_lists_offending_vars(monkeypatch):
    """Error message must name the specific vars that don't agree."""
    with pytest.raises(RuntimeError) as exc_info:
        _reimport_config(
            monkeypatch,
            DCL_URL="http://localhost:8004",
            FARM_INTAKE_URL="http://localhost:8003",
            WORKATO_BASE_URL="http://localhost:8003/sims/workato",
            BOOMI_BASE_URL=None,
            FARM_URL=None,
            WORKATO_TENANT_ENTITY_ID="finops-demo-co",
            BOOMI_TENANT_ENTITY_ID="real-customer-acme",
        )
    msg = str(exc_info.value)
    # All three offending vars must appear in the breakdown.
    assert "DCL_URL" in msg
    assert "WORKATO_BASE_URL" in msg
    assert "WORKATO_TENANT_ENTITY_ID" in msg
    assert "BOOMI_TENANT_ENTITY_ID" in msg
