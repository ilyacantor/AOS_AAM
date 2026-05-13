"""ipaas_stub — local HTTP stub for Workato + Boomi iPaaS endpoints.

Real vendor API shapes:
  Workato Platform API     /api/recipes                  (recipe catalog)
                           /api/recipes/{id}/callable    (invoke recipe, return records)
                           /api/jobs/{job_id}            (pipeline status)
  Boomi AtomSphere API     /api/processes                (process catalog)
                           /api/processes/{id}/execute   (invoke process, return records)
                           /api/executions/{exec_id}     (pipeline status)

Health states: reachable, degraded, unreachable, auth_expired.
Scenario config: tests/fixtures/harness/scenarios/*.json.
Mid-test state change: POST /stub/set_state {"vendor": ..., "state": ...}.

The stub speaks MCP-shaped tool output for the discovery endpoints
(items[] inside structured). The shims call these endpoints and present the
results to AAM's translator unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

_log = logging.getLogger("aam.harness.ipaas_stub")

_SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def load_scenario(name: str) -> dict[str, Any]:
    path = _SCENARIOS_DIR / f"{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in _SCENARIOS_DIR.glob("*.json"))
        raise FileNotFoundError(f"ipaas_stub: scenario '{name}' not found in {_SCENARIOS_DIR}. Available: {available}")
    return json.loads(path.read_text())


def _state(scenario_name: str) -> dict[str, Any]:
    """Mutable per-process state. Tests use POST /stub/set_state to mutate."""
    return {
        "scenario_name": scenario_name,
        "data": load_scenario(scenario_name),
    }


def create_stub_app(scenario: str = "healthy") -> FastAPI:
    """Build a FastAPI app that simulates Workato + Boomi.

    Use uvicorn to serve, or mount via TestClient.
    """
    app = FastAPI(title=f"ipaas_stub ({scenario})")
    state = _state(scenario)

    def _vendor_block(vendor: str) -> dict[str, Any]:
        block = state["data"].get("vendors", {}).get(vendor)
        if not block:
            raise HTTPException(status_code=404, detail=f"vendor {vendor} not configured in scenario {state['scenario_name']}")
        return block

    def _enforce_health(vendor: str, x_api_key: str | None) -> None:
        block = _vendor_block(vendor)
        health = block.get("health_state", "reachable")
        if health == "unreachable":
            raise HTTPException(status_code=503, detail=f"{vendor} unreachable")
        if health == "auth_expired":
            raise HTTPException(status_code=401, detail=f"{vendor} auth expired")
        if block.get("auth_required") and not x_api_key:
            raise HTTPException(status_code=401, detail=f"{vendor} requires X-API-Key")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"scenario": state["scenario_name"], "vendors": list(state["data"].get("vendors", {}).keys())}

    @app.post("/stub/set_state")
    async def set_state(req: Request) -> dict[str, Any]:
        body = await req.json()
        vendor = body.get("vendor")
        new_state = body.get("state")
        if not vendor or not new_state:
            raise HTTPException(status_code=400, detail="set_state needs vendor + state")
        block = _vendor_block(vendor)
        block["health_state"] = new_state
        return {"vendor": vendor, "state": new_state}

    @app.post("/stub/load_scenario")
    async def load(req: Request) -> dict[str, Any]:
        body = await req.json()
        name = body.get("scenario")
        if not name:
            raise HTTPException(status_code=400, detail="load_scenario needs scenario")
        state["scenario_name"] = name
        state["data"] = load_scenario(name)
        return {"scenario": name}

    # --- Workato endpoints (real API shape, mirrored) ---

    @app.post("/workato/mcp/list_tools")
    async def workato_list_tools(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
        _enforce_health("workato", x_api_key)
        return {
            "tools": [
                {"name": "list_recipes", "description": "List Workato recipes",
                 "input_schema": {"type": "object", "properties": {}}},
            ]
        }

    @app.post("/workato/mcp/list_recipes")
    async def workato_list_recipes(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
        _enforce_health("workato", x_api_key)
        recipes = _vendor_block("workato").get("recipes", [])
        items = []
        for r in recipes:
            if not r.get("active"):
                continue
            if r.get("trigger") != "external_event":
                # Translator rule: only recipes with external trigger become pipes.
                # Scheduled recipes still surface as items for visibility.
                pass
            items.append({
                "id": r["id"],
                "name": r["name"],
                "source_system": r.get("source_system", "Workato"),
                "target_system": r.get("target_system"),
                "modality": "DECLARED_INTERFACE",
                "transport_kind": "API",
                "schema": r.get("schema", []),
                "entity_scope": [r.get("source_system", "")],
                "identity_keys": [f["name"] for f in r.get("schema", []) if f.get("is_key")],
                "change_semantics": "CDC_UPSERT" if r.get("trigger") == "external_event" else "FULL_REFRESH",
                "endpoint_ref": {"path": f"/workato/api/recipes/{r['id']}/callable"},
            })
        return {"content": [], "isError": False, "structured": {"items": items}}

    @app.post("/workato/api/recipes/{recipe_id}/callable")
    async def workato_invoke(recipe_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
        _enforce_health("workato", x_api_key)
        recipes = _vendor_block("workato").get("recipes", [])
        recipe = next((r for r in recipes if r["id"] == recipe_id), None)
        if not recipe:
            raise HTTPException(status_code=404, detail=f"recipe {recipe_id} not found")
        return {
            "source_system": recipe.get("source_system", "Workato"),
            "vendor": "Workato",
            "recipe_id": recipe_id,
            "records": recipe.get("records", []),
        }

    @app.get("/workato/api/jobs/{job_id}")
    async def workato_job_status(job_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
        _enforce_health("workato", x_api_key)
        return {"job_id": job_id, "state": "completed"}

    # --- Boomi endpoints (real API shape, mirrored) ---

    @app.post("/boomi/mcp/list_tools")
    async def boomi_list_tools(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
        _enforce_health("boomi", x_api_key)
        return {
            "tools": [
                {"name": "list_processes", "description": "List Boomi processes",
                 "input_schema": {"type": "object", "properties": {}}},
            ]
        }

    @app.post("/boomi/mcp/list_processes")
    async def boomi_list_processes(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
        _enforce_health("boomi", x_api_key)
        processes = _vendor_block("boomi").get("processes", [])
        items = []
        for p in processes:
            if not p.get("active"):
                continue
            items.append({
                "id": p["id"],
                "name": p["name"],
                "source_system": p.get("source_system", "Boomi"),
                "target_system": p.get("target_system"),
                "modality": "DECLARED_INTERFACE",
                "transport_kind": "API",
                "schema": p.get("schema", []),
                "entity_scope": [p.get("source_system", "")],
                "identity_keys": [f["name"] for f in p.get("schema", []) if f.get("is_key")],
                "change_semantics": "CDC_UPSERT",
                "endpoint_ref": {"path": f"/boomi/api/processes/{p['id']}/execute"},
            })
        return {"content": [], "isError": False, "structured": {"items": items}}

    @app.post("/boomi/api/processes/{process_id}/execute")
    async def boomi_invoke(process_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
        _enforce_health("boomi", x_api_key)
        processes = _vendor_block("boomi").get("processes", [])
        process = next((p for p in processes if p["id"] == process_id), None)
        if not process:
            raise HTTPException(status_code=404, detail=f"process {process_id} not found")
        return {
            "source_system": process.get("source_system", "Boomi"),
            "vendor": "Boomi",
            "process_id": process_id,
            "records": process.get("records", []),
        }

    @app.get("/boomi/api/executions/{exec_id}")
    async def boomi_exec_status(exec_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
        _enforce_health("boomi", x_api_key)
        return {"execution_id": exec_id, "state": "completed"}

    return app


# Allow `python -m tests.fixtures.harness.ipaas_stub` for local dev.
if __name__ == "__main__":
    import uvicorn
    scenario = os.environ.get("HARNESS_SCENARIO", "healthy")
    port = int(os.environ.get("HARNESS_IPAAS_PORT", "8902"))
    uvicorn.run(create_stub_app(scenario), host="127.0.0.1", port=port)
