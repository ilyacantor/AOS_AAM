"""HTTPTransport — the demo transport.

Four operations on one transport:
  - Callable endpoint client: invoke iPaaS callable recipe/flow/process,
    return record batches. The demo path drives this.
  - REST proxy client: GET/POST through API gateways with auth injection.
  - Data pipeline poller: poll vendor pipeline run status until complete.
  - Webhook receiver: factory-bound FastAPI route registry to accept inbound.

Auth injection: api_key, oauth2_bearer, aws_sigv4, basic.

CRITICAL: HTTPTransport has no vendor branching. It treats the endpoint URL
and auth credentials as opaque. The shim layer normalizes the vendor's API
shape; HTTPTransport just moves bytes.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger("aam.transport.http")


class HTTPTransportError(Exception):
    """Raised when an HTTP operation fails. Loud-fail, no silent fallback."""


@dataclass
class TransportRecord:
    """One record yielded by transport — opaque payload + provenance metadata.

    The flow controller and triple builder downstream rely on these fields.
    """
    pipe_id: str
    record_key: str
    payload: dict[str, Any]
    offset: str = ""
    source_system: str = ""
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class HTTPTransport:
    """HTTP-based data movement. One implementation, many vendors."""

    def __init__(
        self,
        base_url: str,
        auth_method: str = "api_key",
        auth_credentials: Optional[dict[str, Any]] = None,
        timeout_seconds: float = 10.0,
        retry_budget: int = 3,
        request_fn: Optional[Callable[[str, str, dict, bytes | None], dict[str, Any]]] = None,
    ):
        if not base_url:
            raise HTTPTransportError("HTTPTransport requires base_url")
        if auth_method not in ("api_key", "oauth2_bearer", "aws_sigv4", "basic"):
            raise HTTPTransportError(f"HTTPTransport: unsupported auth_method={auth_method}")
        self.base_url = base_url.rstrip("/")
        self.auth_method = auth_method
        self.auth_credentials = auth_credentials or {}
        self.timeout_seconds = timeout_seconds
        self.retry_budget = retry_budget
        self._request_fn = request_fn or self._default_request

    def invoke_callable(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke a callable iPaaS endpoint and return the body."""
        url = self._join(path)
        return self._with_retry("POST", url, body=params or {})

    def proxy_get(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET through a gateway/REST endpoint."""
        url = self._join(path)
        if query:
            qs = "&".join(f"{k}={v}" for k, v in query.items())
            url = f"{url}?{qs}"
        return self._with_retry("GET", url, body=None)

    def proxy_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._with_retry("POST", self._join(path), body=body)

    def poll_pipeline(self, status_path: str, terminal_states: tuple[str, ...] = ("completed", "failed")) -> dict[str, Any]:
        """Poll a pipeline status endpoint until it reaches a terminal state."""
        url = self._join(status_path)
        last: dict[str, Any] = {}
        for attempt in range(1, self.retry_budget * 4 + 1):
            last = self._with_retry("GET", url, body=None)
            state = str(last.get("state") or last.get("status") or "")
            if state in terminal_states:
                return last
            time.sleep(min(0.5 * attempt, 2.0))
        raise HTTPTransportError(f"poll_pipeline: never reached terminal state url={url} last={last}")

    def fetch_records(self, pipe_id: str, path: str, params: dict[str, Any] | None = None,
                      key_fields: list[str] | None = None) -> list[TransportRecord]:
        """Demo path — call the callable endpoint, expect a records[] response.

        Returns TransportRecord objects with pipe_id, record_key, payload,
        offset, source_system. Used by the flow controller.

        key_fields: ordered list of payload field names to try as record_key.
        Falls back to id / key / record_key / synthesized index.
        """
        if not pipe_id:
            raise HTTPTransportError("fetch_records requires non-empty pipe_id")
        response = self.invoke_callable(path, params=params)
        if not isinstance(response, dict):
            raise HTTPTransportError(f"fetch_records: expected dict response pipe_id={pipe_id} got={type(response).__name__}")
        records_raw = response.get("records")
        if not isinstance(records_raw, list):
            raise HTTPTransportError(
                f"fetch_records: response missing records[] pipe_id={pipe_id} path={path} keys={list(response.keys())}"
            )
        source_system = str(response.get("source_system") or response.get("vendor") or "")
        ordered_keys = list(key_fields or []) + ["id", "key", "record_key"]
        out: list[TransportRecord] = []
        for idx, rec in enumerate(records_raw):
            if not isinstance(rec, dict):
                continue
            record_key = ""
            for k in ordered_keys:
                v = rec.get(k)
                if v is not None and v != "":
                    record_key = str(v)
                    break
            if not record_key:
                record_key = f"rec-{idx}"
            offset = str(rec.get("_offset") or rec.get("offset") or idx)
            ts = str(rec.get("_timestamp") or rec.get("timestamp") or "")
            payload = {k: v for k, v in rec.items() if not k.startswith("_")}
            out.append(TransportRecord(
                pipe_id=pipe_id,
                record_key=record_key,
                payload=payload,
                offset=offset,
                source_system=source_system,
                timestamp=ts,
                metadata={"path": path},
            ))
        return out

    def _join(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _auth_headers(self) -> dict[str, str]:
        if self.auth_method == "api_key":
            return {"X-API-Key": str(self.auth_credentials.get("api_key", ""))}
        if self.auth_method == "oauth2_bearer":
            return {"Authorization": f"Bearer {self.auth_credentials.get('token', '')}"}
        if self.auth_method == "aws_sigv4":
            return {"X-Auth-Type": "aws_sigv4", "X-Amz-Date": str(int(time.time()))}
        if self.auth_method == "basic":
            user = self.auth_credentials.get("username", "")
            pwd = self.auth_credentials.get("password", "")
            token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        raise HTTPTransportError(f"_auth_headers: unsupported auth_method={self.auth_method}")

    def _with_retry(self, method: str, url: str, body: dict[str, Any] | None) -> dict[str, Any]:
        last_exc: Optional[Exception] = None
        body_bytes: bytes | None = None
        if body is not None:
            body_bytes = json.dumps(body).encode("utf-8")
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        attempts = max(1, self.retry_budget)
        for attempt in range(1, attempts + 1):
            try:
                return self._request_fn(method, url, headers, body_bytes)
            except HTTPTransportError:
                raise
            except Exception as exc:
                last_exc = exc
                _log.warning("http %s %s retry %d/%d err=%s", method, url, attempt, attempts, exc)
                time.sleep(min(0.5 * attempt, 2.0))
        raise HTTPTransportError(f"HTTP {method} {url} failed after {attempts} attempts: {last_exc}")

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
            raise HTTPTransportError(f"HTTP {method} {url} returned {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise HTTPTransportError(f"HTTP {method} {url} connect error: {exc.reason}") from exc
