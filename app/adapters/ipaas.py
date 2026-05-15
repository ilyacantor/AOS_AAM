"""
IPaaSAdapter - Integration Platform Control Plane

Connects to iPaaS platforms (Workato, MuleSoft, Boomi, Tray.io)
to inventory integration flows and recipes.

Modality: Webhooks/Signals from the iPaaS control plane.

WP12a' — workato + boomi adapters now have real implementations against
vendor REST contracts (Workato Platform API v2.0; Boomi AtomSphere REST v1).
The vendor URL is read from env (WORKATO_BASE_URL / BOOMI_BASE_URL); pointing
at Farm fabric sims (http://localhost:8003/sims/<vendor>) is a config swap,
not a code change. mulesoft / tray.io / zapier remain unimplemented.
"""

import base64
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from .base import FabricAdapter, AdapterStatus, PlaneHealth, PlaneDrift
from ..parsers.ipaas_recipe import parse_workato_recipe, parse_tray_workflow
from ..db.semantic_edges import store_semantic_edges_batch, delete_semantic_edges_by_source

_log = logging.getLogger("aam.adapter.ipaas")


class IPaaSAdapter(FabricAdapter):
    """
    Adapter for iPaaS Fabric Plane.

    Connects to integration platform control planes to:
    - Discover existing integration flows/recipes
    - Monitor flow execution status
    - Receive webhook signals on flow changes
    - Self-heal connection disruptions

    Supported vendors: Workato, MuleSoft, Boomi, Tray.io, Zapier
    """

    SUPPORTED_VENDORS = ["workato", "mulesoft", "boomi", "tray.io", "zapier"]

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._vendor = config.get("vendor", "workato").lower()
        self._webhook_url: Optional[str] = None
        self._flows_discovered: List[Dict] = []

    @property
    def plane_type(self) -> str:
        return "IPAAS"

    @property
    def plane_vendor(self) -> str:
        return self._vendor

    # ---- per-vendor env config ------------------------------------------

    def _workato_base(self) -> str:
        url = os.environ.get("WORKATO_BASE_URL", "").rstrip("/")
        if not url:
            raise RuntimeError("WORKATO_BASE_URL not set; point at Farm sim or vendor cloud")
        return url

    def _workato_token(self) -> str:
        token = os.environ.get("WORKATO_API_TOKEN", "")
        if not token:
            raise RuntimeError("WORKATO_API_TOKEN not set")
        return token

    def _boomi_base(self) -> str:
        url = os.environ.get("BOOMI_BASE_URL", "").rstrip("/")
        if not url:
            raise RuntimeError("BOOMI_BASE_URL not set; point at Farm sim or vendor cloud")
        return url

    def _boomi_basic_header(self) -> str:
        user = os.environ.get("BOOMI_USERNAME", "")
        token = os.environ.get("BOOMI_API_TOKEN", "")
        if not user or not token:
            raise RuntimeError("BOOMI_USERNAME and BOOMI_API_TOKEN must both be set")
        encoded = base64.b64encode(f"{user}:{token}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    def _boomi_account(self) -> str:
        acct = os.environ.get("BOOMI_ACCOUNT_ID", "")
        if not acct:
            raise RuntimeError("BOOMI_ACCOUNT_ID not set")
        return acct

    # ---- connect ---------------------------------------------------------

    async def connect(self) -> bool:
        """Connect: validate creds with a cheap GET against a known endpoint."""
        if self._vendor == "workato":
            base, token = self._workato_base(), self._workato_token()
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{base}/api/recipes",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"per_page": 1},
                )
            if r.status_code == 401:
                self._status = AdapterStatus.FAILED
                self._error_message = "Workato auth rejected — check WORKATO_API_TOKEN"
                return False
            if r.status_code >= 400:
                self._status = AdapterStatus.FAILED
                self._error_message = f"Workato connect HTTP {r.status_code}: {r.text[:200]}"
                return False
            self._status = AdapterStatus.CONNECTED
            return True
        if self._vendor == "boomi":
            base = self._boomi_base()
            acct = self._boomi_account()
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{base}/api/rest/v1/{acct}/Process",
                    headers={"Authorization": self._boomi_basic_header()},
                )
            if r.status_code == 401:
                self._status = AdapterStatus.FAILED
                self._error_message = "Boomi auth rejected — check BOOMI_USERNAME / BOOMI_API_TOKEN"
                return False
            if r.status_code >= 400:
                self._status = AdapterStatus.FAILED
                self._error_message = f"Boomi connect HTTP {r.status_code}: {r.text[:200]}"
                return False
            self._status = AdapterStatus.CONNECTED
            return True
        raise NotImplementedError(
            f"IPaaSAdapter.connect() not implemented for vendor '{self._vendor}'. "
            "Workato and Boomi are implemented; other vendors require their own auth flow."
        )

    async def disconnect(self) -> bool:
        """Disconnect from iPaaS control plane"""
        self._status = AdapterStatus.DISCONNECTED
        self._webhook_url = None
        return True

    async def check_health(self) -> PlaneHealth:
        """Health check via the same endpoint as connect()."""
        started = datetime.utcnow()
        try:
            ok = await self.connect()
        except RuntimeError as exc:
            self._status = AdapterStatus.FAILED
            self._error_message = str(exc)
            ok = False
        latency_ms = (datetime.utcnow() - started).total_seconds() * 1000
        self._last_health_check = datetime.utcnow()
        return PlaneHealth(
            status=self._status,
            last_check=self._last_health_check,
            latency_ms=round(latency_ms, 2),
            error_message=None if ok else self._error_message,
        )

    async def discover_pipes(self) -> List[Dict[str, Any]]:
        """List the recipes/processes available on the control plane."""
        if self._vendor == "workato":
            base, token = self._workato_base(), self._workato_token()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{base}/api/recipes",
                    headers={"Authorization": f"Bearer {token}"},
                )
            r.raise_for_status()
            recipes = r.json()
            self._flows_discovered = recipes
            return [
                {
                    "vendor": "workato",
                    "vendor_id": str(rec.get("id")),
                    "name": rec.get("name"),
                    "running": rec.get("running", False),
                    "trigger_application": rec.get("trigger_application"),
                }
                for rec in recipes
            ]
        if self._vendor == "boomi":
            base = self._boomi_base()
            acct = self._boomi_account()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{base}/api/rest/v1/{acct}/Process",
                    headers={"Authorization": self._boomi_basic_header()},
                )
            r.raise_for_status()
            processes = r.json()
            self._flows_discovered = processes
            return [
                {
                    "vendor": "boomi",
                    "vendor_id": proc.get("id"),
                    "name": proc.get("name"),
                    "deployment_id": proc.get("deploymentId"),
                    "trigger": proc.get("trigger"),
                }
                for proc in processes
            ]
        raise NotImplementedError(
            f"IPaaSAdapter.discover_pipes() not implemented for vendor '{self._vendor}'."
        )

    async def self_heal(self, drift: PlaneDrift) -> bool:
        """Self-heal iPaaS connection issues — re-auth on connection_lost."""
        if drift.drift_type == "connection_lost" and self._vendor in ("workato", "boomi"):
            self._status = AdapterStatus.HEALING
            ok = await self.connect()
            return ok
        raise NotImplementedError(
            f"IPaaSAdapter.self_heal() not implemented for vendor '{self._vendor}' "
            f"+ drift_type='{drift.drift_type}'."
        )

    def extract_semantic_edges(self, recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract field-level semantic edges from iPaaS recipes/workflows.

        For each recipe:
        1. Parse the recipe JSON using the vendor-appropriate parser
        2. Delete any previously-stored edges from this extraction source
           (idempotent re-scan)
        3. Batch-insert the new edges into semantic_edges table

        Args:
            recipes: List of recipe/workflow JSON objects from the iPaaS API

        Returns:
            All extracted SemanticEdge dicts (already persisted)
        """
        all_edges: List[Dict[str, Any]] = []

        for recipe in recipes:
            recipe_id = recipe.get("id", "unknown")

            if self._vendor in ("workato", "mulesoft", "boomi"):
                edges = parse_workato_recipe(recipe)
            elif self._vendor == "tray.io":
                edges = parse_tray_workflow(recipe)
            elif self._vendor == "zapier":
                _log.warning(
                    "Zapier recipe %s — field-level extraction not available "
                    "(API limitation in free/pro tiers)",
                    recipe_id,
                )
                continue
            else:
                _log.warning("Unsupported iPaaS vendor %s for recipe %s", self._vendor, recipe_id)
                continue

            if not edges:
                continue

            # Idempotent: clear previous edges from this recipe before re-insert
            extraction_source = edges[0]["extraction_source"]
            delete_semantic_edges_by_source(extraction_source)
            stored = store_semantic_edges_batch(edges)
            all_edges.extend(stored)
            _log.info(
                "Stored %d semantic edges from %s recipe %s",
                len(stored), self._vendor, recipe_id,
            )

        _log.info(
            "iPaaS semantic edge extraction complete: %d edges from %d recipes",
            len(all_edges), len(recipes),
        )
        return all_edges

    def apply_governance_policy(self, policy: Dict[str, Any]) -> bool:
        """Apply governance at iPaaS level."""
        raise NotImplementedError(
            f"IPaaSAdapter.apply_governance_policy() not implemented for vendor '{self._vendor}'."
        )
