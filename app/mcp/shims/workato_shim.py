"""Workato shim — translates Workato Platform API to MCP tool output JSON.

Workato is in the process of shipping a native MCP server. Until then, this
shim calls the Platform API (api.workato.com) and reformats responses.
Disposable: deleted the day Workato's MCP server is GA.

Auth: API key in X-API-Key header.

Discovery tools:
  list_recipes  -> structured.items[] one per active recipe.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from ..shim_base import VendorShimBase

_log = logging.getLogger("aam.mcp.shims.workato")


class WorkatoShim(VendorShimBase):
    """Workato Platform API -> MCP tool output."""

    def __init__(
        self,
        endpoint: str,
        auth: dict[str, Any] | None = None,
        request_fn: Optional[Callable[[str, str, dict, bytes | None], dict[str, Any]]] = None,
        timeout_seconds: float = 10.0,
    ):
        super().__init__(vendor_name="Workato", endpoint=endpoint, auth=auth)
        self._request_fn = request_fn or self._default_request
        self.timeout_seconds = timeout_seconds

    def list_discovery_tools(self) -> list[dict[str, Any]]:
        result = self._call("POST", "/workato/mcp/list_tools", body={})
        return list(result.get("tools") or [])

    def invoke_tool(self, name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if name == "list_recipes":
            return self._call("POST", "/workato/mcp/list_recipes", body=params)
        raise ValueError(f"WorkatoShim: unknown tool '{name}'. Supported: list_recipes")

    def fetch_records_path_for(self, pipe: dict[str, Any]) -> str:
        """Return the endpoint path to fetch records for a Workato recipe pipe."""
        path = (pipe.get("endpoint_ref") or {}).get("path")
        if not path:
            raise ValueError(f"WorkatoShim: pipe missing endpoint_ref.path pipe_id={pipe.get('pipe_id')}")
        return str(path)

    def _auth_headers(self) -> dict[str, str]:
        return {"X-API-Key": str(self.auth.get("api_key", ""))}

    def _call(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        body_bytes = json.dumps(body).encode("utf-8") if body is not None else None
        url = f"{self.endpoint}{path}"
        return self._request_fn(method, url, headers, body_bytes)

    def _default_request(self, method: str, url: str, headers: dict[str, str], body: bytes | None) -> dict[str, Any]:
        req = urllib.request.Request(url=url, data=body, method=method)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:500]
            except Exception:
                pass
            raise RuntimeError(f"Workato API {method} {url} returned {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Workato API {method} {url} connect error: {exc.reason}") from exc
