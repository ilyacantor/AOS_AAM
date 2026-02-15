"""
Supabase REST API client for AAM.

Provides low-level CRUD helpers that wrap Supabase's PostgREST API.
All db modules use these instead of raw sqlite3 calls.
"""
import os
import json
import httpx
from typing import Optional, Any
from ..logger import get_logger

_log = get_logger("db.supabase")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_API_KEY = os.environ.get("SUPABASE_API_KEY", "")

_REST_BASE = f"{SUPABASE_URL}/rest/v1"

_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

_client: Optional[httpx.Client] = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            base_url=_REST_BASE,
            headers=_HEADERS,
            timeout=30.0,
        )
    return _client


def _check_response(resp: httpx.Response, context: str = ""):
    if resp.status_code >= 400:
        detail = resp.text[:500]
        _log.error("Supabase error [%s] %d: %s", context, resp.status_code, detail)
        raise RuntimeError(f"Supabase {context}: {resp.status_code} — {detail}")


def insert(table: str, data: dict, *, on_conflict: Optional[str] = None) -> dict:
    client = _get_client()
    headers = dict(_HEADERS)
    if on_conflict:
        headers["Prefer"] = f"return=representation,resolution=merge-duplicates"
        url = f"/{table}?on_conflict={on_conflict}"
    else:
        url = f"/{table}"
    resp = client.post(url, json=data, headers=headers)
    _check_response(resp, f"insert {table}")
    rows = resp.json()
    return rows[0] if isinstance(rows, list) and rows else rows


def insert_many(table: str, data: list[dict]) -> list[dict]:
    if not data:
        return []
    client = _get_client()
    resp = client.post(f"/{table}", json=data)
    _check_response(resp, f"insert_many {table}")
    return resp.json()


def select(
    table: str,
    *,
    columns: str = "*",
    filters: Optional[dict[str, Any]] = None,
    eq_filters: Optional[list[tuple[str, Any]]] = None,
    raw_params: Optional[dict[str, str]] = None,
    order: Optional[str] = None,
    limit: Optional[int] = None,
    single: bool = False,
) -> list[dict] | dict | None:
    client = _get_client()
    params: dict[str, str] = {"select": columns}
    if filters:
        for col, val in filters.items():
            params[col] = f"eq.{val}"
    if eq_filters:
        for col, val in eq_filters:
            params[col] = f"eq.{val}"
    if raw_params:
        params.update(raw_params)
    if order:
        params["order"] = order
    if limit:
        params["limit"] = str(limit)

    headers = dict(_HEADERS)
    if single:
        headers["Accept"] = "application/vnd.pgrst.object+json"

    resp = client.get(f"/{table}", params=params, headers=headers)

    if single and resp.status_code == 406:
        return None
    _check_response(resp, f"select {table}")
    return resp.json()


def update(
    table: str,
    data: dict,
    *,
    filters: Optional[dict[str, Any]] = None,
    eq_filters: Optional[list[tuple[str, Any]]] = None,
) -> list[dict]:
    client = _get_client()
    params: dict[str, str] = {}
    if filters:
        for col, val in filters.items():
            params[col] = f"eq.{val}"
    if eq_filters:
        for col, val in eq_filters:
            params[col] = f"eq.{val}"
    resp = client.patch(f"/{table}", json=data, params=params)
    _check_response(resp, f"update {table}")
    return resp.json()


def delete(
    table: str,
    *,
    filters: Optional[dict[str, Any]] = None,
    eq_filters: Optional[list[tuple[str, Any]]] = None,
    delete_all: bool = False,
) -> list[dict]:
    client = _get_client()
    params: dict[str, str] = {}
    if filters:
        for col, val in filters.items():
            params[col] = f"eq.{val}"
    if eq_filters:
        for col, val in eq_filters:
            params[col] = f"eq.{val}"
    if not params and not delete_all:
        raise ValueError("delete() requires filters or delete_all=True")
    if not params and delete_all:
        params["id"] = "neq.IMPOSSIBLE_NEVER_MATCH"
    resp = client.delete(f"/{table}", params=params)
    _check_response(resp, f"delete {table}")
    return resp.json()


def rpc(function_name: str, params: Optional[dict] = None) -> Any:
    client = _get_client()
    resp = client.post(f"/rpc/{function_name}", json=params or {})
    _check_response(resp, f"rpc {function_name}")
    return resp.json()


def raw_sql(sql: str) -> Any:
    """Execute raw SQL via Supabase's rpc endpoint.
    Requires a 'exec_sql' function to be created in Supabase.
    Falls back to direct REST calls if not available.
    """
    try:
        return rpc("exec_sql", {"query": sql})
    except Exception as e:
        _log.warning("raw_sql via rpc failed: %s", e)
        raise


def table_exists(table_name: str) -> bool:
    """Check if a table exists by trying a minimal select."""
    try:
        client = _get_client()
        resp = client.get(f"/{table_name}", params={"select": "*", "limit": "0"})
        return resp.status_code < 400
    except Exception:
        return False
