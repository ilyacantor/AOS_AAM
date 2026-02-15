"""
Supabase PostgreSQL client for AAM.

Uses psycopg2 with connection pooling via the Supabase session pooler.
Provides low-level CRUD helpers that all db modules use.
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Any

import psycopg2
import psycopg2.pool
import psycopg2.extras
from ..logger import get_logger

_log = get_logger("db.supabase")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
_PROJECT_REF = SUPABASE_URL.replace("https://", "").split(".")[0] if SUPABASE_URL else ""
_DB_PASSWORD = os.environ.get("SUPABASE_DB_PASSWORD", "").strip()

_DSN = (
    f"host=aws-0-us-west-2.pooler.supabase.com "
    f"port=5432 "
    f"dbname=postgres "
    f"user=postgres.{_PROJECT_REF} "
    f"password={_DB_PASSWORD} "
    f"sslmode=require "
    f"connect_timeout=10"
)

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=_DSN,
        )
        _log.info("PostgreSQL connection pool created (pooler: us-west-2)")
    return _pool


def _get_conn():
    """Get a connection from the pool with retry logic."""
    pool = _get_pool()
    try:
        conn = pool.getconn()
        conn.autocommit = True
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        except Exception:
            pool.putconn(conn, close=True)
            conn = pool.getconn()
            conn.autocommit = True
        return conn
    except psycopg2.pool.PoolError:
        global _pool
        if _pool:
            try:
                _pool.closeall()
            except Exception:
                pass
        _pool = None
        pool = _get_pool()
        conn = pool.getconn()
        conn.autocommit = True
        return conn


def _put_conn(conn):
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


def _execute(query: str, params: tuple = (), *, fetch: bool = True) -> list[dict]:
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, params)
        if fetch and cur.description:
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        return []
    except Exception as e:
        _log.error("SQL error: %s | query: %s", e, query[:200])
        raise
    finally:
        _put_conn(conn)


def insert(table: str, data: dict, *, on_conflict: Optional[str] = None) -> dict:
    cols = list(data.keys())
    vals = list(data.values())
    placeholders = ", ".join(["%s"] * len(cols))
    col_str = ", ".join(cols)

    if on_conflict:
        update_cols = [c for c in cols if c != on_conflict]
        update_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        query = (
            f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) "
            f"ON CONFLICT ({on_conflict}) DO UPDATE SET {update_str} "
            f"RETURNING *"
        )
    else:
        query = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) RETURNING *"

    rows = _execute(query, tuple(vals))
    return rows[0] if rows else {}


def insert_many(table: str, data: list[dict]) -> list[dict]:
    if not data:
        return []
    cols = list(data[0].keys())
    col_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))

    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        results = []
        for row in data:
            vals = tuple(row.get(c) for c in cols)
            cur.execute(
                f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) RETURNING *",
                vals,
            )
            if cur.description:
                results.extend([dict(r) for r in cur.fetchall()])
        return results
    except Exception as e:
        _log.error("insert_many error: %s", e)
        raise
    finally:
        _put_conn(conn)


def _build_where(
    filters: Optional[dict[str, Any]] = None,
    eq_filters: Optional[list[tuple[str, Any]]] = None,
    raw_params: Optional[dict[str, str]] = None,
) -> tuple[str, list]:
    """Build WHERE clause from filter dicts. Returns (clause_str, param_list)."""
    conditions = []
    params = []

    if filters:
        for col, val in filters.items():
            conditions.append(f"{col} = %s")
            params.append(val)

    if eq_filters:
        for col, val in eq_filters:
            conditions.append(f"{col} = %s")
            params.append(val)

    if raw_params:
        for col, expr in raw_params.items():
            if expr == "eq.true":
                conditions.append(f"{col} = %s")
                params.append(True)
            elif expr == "eq.false":
                conditions.append(f"{col} = %s")
                params.append(False)
            elif expr.startswith("eq."):
                conditions.append(f"{col} = %s")
                params.append(expr[3:])
            elif expr == "not.is.null":
                conditions.append(f"{col} IS NOT NULL")
            elif expr.startswith("is."):
                val = expr[3:]
                if val == "null":
                    conditions.append(f"{col} IS NULL")
                else:
                    conditions.append(f"{col} = %s")
                    params.append(val)
            else:
                conditions.append(f"{col} = %s")
                params.append(expr)

    if conditions:
        return " WHERE " + " AND ".join(conditions), params
    return "", params


def _parse_order(order: Optional[str]) -> str:
    """Convert PostgREST-style order (col.desc) to SQL ORDER BY."""
    if not order:
        return ""
    parts = order.split(".")
    col = parts[0]
    direction = parts[1].upper() if len(parts) > 1 else "ASC"
    if direction not in ("ASC", "DESC"):
        direction = "ASC"
    return f" ORDER BY {col} {direction}"


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
    where_clause, params = _build_where(filters, eq_filters, raw_params)
    order_clause = _parse_order(order)
    limit_clause = f" LIMIT {limit}" if limit else ""

    query = f"SELECT {columns} FROM {table}{where_clause}{order_clause}{limit_clause}"
    rows = _execute(query, tuple(params))

    if single:
        return rows[0] if rows else None
    return rows


def update(
    table: str,
    data: dict,
    *,
    filters: Optional[dict[str, Any]] = None,
    eq_filters: Optional[list[tuple[str, Any]]] = None,
) -> list[dict]:
    set_cols = list(data.keys())
    set_str = ", ".join(f"{c} = %s" for c in set_cols)
    set_vals = list(data.values())

    where_clause, where_params = _build_where(filters, eq_filters)
    if not where_clause:
        raise ValueError("update() requires filters")

    query = f"UPDATE {table} SET {set_str}{where_clause} RETURNING *"
    return _execute(query, tuple(set_vals + where_params))


def delete(
    table: str,
    *,
    filters: Optional[dict[str, Any]] = None,
    eq_filters: Optional[list[tuple[str, Any]]] = None,
    raw_params: Optional[dict[str, str]] = None,
    delete_all: bool = False,
) -> list[dict]:
    where_clause, params = _build_where(filters, eq_filters, raw_params)

    if not where_clause and not delete_all:
        raise ValueError("delete() requires filters or delete_all=True")

    query = f"DELETE FROM {table}{where_clause} RETURNING *"
    return _execute(query, tuple(params))


def update_many_concurrent(
    table: str,
    updates: list[tuple[dict, dict]],
    *,
    max_workers: int = 10,
) -> int:
    """Fire many UPDATE calls concurrently (threaded).

    Each entry in *updates* is (filter_dict, data_dict).
    Returns the count of successful updates.
    """
    if not updates:
        return 0

    def _do_one(pair):
        filt, data = pair
        update(table, data, filters=filt)

    ok = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_do_one, pair) for pair in updates]
        for fut in as_completed(futures):
            try:
                fut.result()
                ok += 1
            except Exception as exc:
                _log.warning("concurrent update failed: %s", exc)
    return ok


def rpc(function_name: str, params: Optional[dict] = None) -> Any:
    """Call a stored function/procedure."""
    if params:
        param_str = ", ".join(f"%s" for _ in params)
        query = f"SELECT * FROM {function_name}({param_str})"
        rows = _execute(query, tuple(params.values()))
    else:
        query = f"SELECT * FROM {function_name}()"
        rows = _execute(query)
    return rows


def table_exists(table_name: str) -> bool:
    try:
        rows = _execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)",
            (table_name,),
        )
        return rows[0].get("exists", False) if rows else False
    except Exception:
        return False
