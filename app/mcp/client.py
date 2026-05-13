"""Universal MCP Client.

One client serves every vendor — native MCP servers and shims alike. The
client speaks the MCP tool surface (list_tools / invoke_tool) and does not
know or care which vendor is on the other side. That property is what makes
"same AAM code path across Workato and Boomi" testable.

Auth methods: api_key, oauth2_bearer, azure_ad, aws_sigv4. The client passes
auth headers through to the underlying transport (or shim). Connection
health monitoring with a retry budget — no infinite retries.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .shim_base import VendorShimBase

_log = logging.getLogger("aam.mcp.client")


class MCPClientError(Exception):
    """Raised when an MCP tool call cannot complete.

    Loud-fail by design. Caller surfaces this — no silent fallback.
    """


@dataclass
class MCPTool:
    """One discovery tool exposed by an MCP server (or shim)."""
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MCPTool":
        if "name" not in d:
            raise MCPClientError(f"MCP tool definition missing 'name': {d}")
        return cls(
            name=str(d["name"]),
            description=str(d.get("description", "")),
            input_schema=dict(d.get("input_schema") or d.get("inputSchema") or {}),
        )


@dataclass
class MCPToolResult:
    """Result of one invoke_tool call. Shape matches MCP spec."""
    content: list[dict[str, Any]] = field(default_factory=list)
    structured: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MCPToolResult":
        return cls(
            content=list(d.get("content") or []),
            structured=dict(d.get("structured") or {}),
            is_error=bool(d.get("isError", False)),
            raw=d,
        )


class MCPClient:
    """Universal client that talks to either an MCP server or a vendor shim.

    For the demo, we drive both Workato and Boomi via shims — same client
    code, same translator code, same downstream pipeline.
    """

    AUTH_METHODS = ("api_key", "oauth2_bearer", "azure_ad", "aws_sigv4")

    def __init__(
        self,
        vendor: str,
        shim: Optional[VendorShimBase] = None,
        http_invoker: Optional[Callable[[str, str, dict, dict], dict]] = None,
        endpoint: Optional[str] = None,
        auth_method: str = "api_key",
        auth_credentials: Optional[dict[str, Any]] = None,
        timeout_seconds: float = 10.0,
        retry_budget: int = 3,
    ):
        if not vendor or not vendor.strip():
            raise MCPClientError("MCPClient requires non-empty vendor")
        if shim is None and http_invoker is None:
            raise MCPClientError(
                f"MCPClient for vendor={vendor} requires either a shim instance "
                f"or an http_invoker callable. Native MCP-over-HTTP needs http_invoker; "
                f"vendor shims need shim."
            )
        if auth_method not in self.AUTH_METHODS:
            raise MCPClientError(f"Unsupported auth_method={auth_method}. Allowed: {self.AUTH_METHODS}")
        self.vendor = vendor
        self.shim = shim
        self.http_invoker = http_invoker
        self.endpoint = endpoint
        self.auth_method = auth_method
        self.auth_credentials = auth_credentials or {}
        self.timeout_seconds = timeout_seconds
        self.retry_budget = retry_budget
        self._is_connected = False

    def connect(self) -> bool:
        """Establish (or verify) reachability. For shims this is a no-op probe."""
        if self.shim is not None:
            self.shim.health_check()
            self._is_connected = True
            return True
        if self.http_invoker is None or self.endpoint is None:
            raise MCPClientError(f"MCPClient.connect: native MCP path needs endpoint + invoker (vendor={self.vendor})")
        self._is_connected = True
        return True

    def list_tools(self) -> list[MCPTool]:
        """Discover tools exposed by the vendor (shim or native)."""
        if not self._is_connected:
            self.connect()
        if self.shim is not None:
            tool_defs = self.shim.list_discovery_tools()
        else:
            result = self._http_call("list_tools", {})
            tool_defs = result.get("tools") or []
        return [MCPTool.from_dict(t) for t in tool_defs]

    def invoke_tool(self, name: str, params: dict[str, Any] | None = None) -> MCPToolResult:
        """Invoke a discovery tool. Loud-fail on error."""
        if not self._is_connected:
            self.connect()
        params = params or {}
        last_exc: Optional[Exception] = None
        attempts = max(1, self.retry_budget)
        for attempt in range(1, attempts + 1):
            try:
                if self.shim is not None:
                    raw = self.shim.invoke_tool(name, params)
                else:
                    raw = self._http_call(name, params)
                result = MCPToolResult.from_dict(raw)
                if result.is_error:
                    raise MCPClientError(
                        f"MCP tool error: vendor={self.vendor} tool={name} attempt={attempt} content={result.content}"
                    )
                return result
            except MCPClientError:
                raise
            except Exception as exc:
                last_exc = exc
                _log.warning("mcp invoke retry %d/%d vendor=%s tool=%s err=%s", attempt, attempts, self.vendor, name, exc)
                time.sleep(min(0.5 * attempt, 2.0))
        raise MCPClientError(
            f"MCP tool {name} on vendor={self.vendor} failed after {attempts} attempts: {last_exc}"
        )

    def _http_call(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.http_invoker is None or self.endpoint is None:
            raise MCPClientError(f"_http_call requires endpoint + invoker (vendor={self.vendor})")
        headers = self._auth_headers()
        return self.http_invoker(self.endpoint, tool, params, headers)

    def _auth_headers(self) -> dict[str, str]:
        if self.auth_method == "api_key":
            key = self.auth_credentials.get("api_key", "")
            return {"X-API-Key": key}
        if self.auth_method == "oauth2_bearer":
            token = self.auth_credentials.get("token", "")
            return {"Authorization": f"Bearer {token}"}
        if self.auth_method == "azure_ad":
            token = self.auth_credentials.get("token", "")
            return {"Authorization": f"Bearer {token}", "X-Auth-Type": "azure_ad"}
        if self.auth_method == "aws_sigv4":
            return {"X-Amz-Date": str(int(time.time())), "X-Auth-Type": "aws_sigv4"}
        raise MCPClientError(f"_auth_headers: unsupported auth_method={self.auth_method}")
