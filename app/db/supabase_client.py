"""
Supabase PostgreSQL client for AAM.

Uses psycopg2 with connection pooling via the Supabase session pooler.
Provides low-level CRUD helpers that all db modules use.
All identifiers (table names, column names) are quoted via psycopg2.sql
to prevent SQL injection.
"""
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Any

import psycopg2
import psycopg2.pool
import psycopg2.extras
from psycopg2 import sql
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

_IDENT_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _validate_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def _ident(name: str) -> sql.Identifier:
    _validate_ident(name)
    return sql.Identifier(name)


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=30,
            dsn=_DSN,
        )
        _log.info("PostgreSQL connection pool created (pooler: us-west-2)")
    return _pool


def _get_conn():
    """Get a connection from the pool — no health-check round trip."""
    for attempt in range(2):
        pool = _get_pool()
        try:
            conn = pool.getconn()
            conn.autocommit = True
            if conn.closed:
                pool.putconn(conn, close=True)
                continue
            return conn
        except (psycopg2.pool.PoolError, psycopg2.OperationalError):
            global _pool
            if _pool:
                try:
                    _pool.closeall()
                except Exception:
                    pass
            _pool = None
            continue
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    return conn


def _put_conn(conn, *, broken: bool = False):
    try:
        pool = _get_pool()
        if broken or conn.closed:
            pool.putconn(conn, close=True)
        else:
            pool.putconn(conn)
    except Exception:
        pass


def _execute_composed(query: sql.Composed, params: tuple = (), *, fetch: bool = True) -> list[dict]:
    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, params)
        if fetch and cur.description:
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        return []
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        _log.warning("Connection error (retrying): %s", e)
        _put_conn(conn, broken=True)
        conn = _get_conn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(query, params)
            if fetch and cur.description:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            return []
        except Exception as e2:
            _log.error("SQL error on retry: %s", e2)
            _put_conn(conn, broken=True)
            raise
        finally:
            _put_conn(conn)
    except Exception as e:
        _log.error("SQL error: %s", e)
        raise
    finally:
        _put_conn(conn)


def insert(table: str, data: dict, *, on_conflict: Optional[str] = None) -> dict:
    cols = list(data.keys())
    vals = list(data.values())
    col_ids = [_ident(c) for c in cols]
    placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(cols))

    if on_conflict:
        update_cols = [c for c in cols if c != on_conflict]
        update_parts = sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(_ident(c), _ident(c)) for c in update_cols
        )
        query = sql.SQL(
            "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {} RETURNING *"
        ).format(
            _ident(table),
            sql.SQL(", ").join(col_ids),
            placeholders,
            _ident(on_conflict),
            update_parts,
        )
    else:
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
            _ident(table),
            sql.SQL(", ").join(col_ids),
            placeholders,
        )

    rows = _execute_composed(query, tuple(vals))
    return rows[0] if rows else {}


def insert_many(table: str, data: list[dict]) -> list[dict]:
    if not data:
        return []
    cols = list(data[0].keys())
    col_ids = sql.SQL(", ").join(_ident(c) for c in cols)
    template = sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() for _ in cols))
    query_head = sql.SQL("INSERT INTO {} ({}) VALUES ").format(_ident(table), col_ids)

    values_list = [tuple(row.get(c) for c in cols) for row in data]

    conn = _get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query_str = query_head.as_string(conn)
        tpl_str = template.as_string(conn)
        full_sql = query_str + ", ".join(
            cur.mogrify(tpl_str, vals).decode() for vals in values_list
        ) + " RETURNING *"
        cur.execute(full_sql)
        if cur.description:
            return [dict(r) for r in cur.fetchall()]
        return []
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        _log.warning("insert_many conn error (retrying): %s", e)
        _put_conn(conn, broken=True)
        conn = _get_conn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            query_str = query_head.as_string(conn)
            tpl_str = template.as_string(conn)
            full_sql = query_str + ", ".join(
                cur.mogrify(tpl_str, vals).decode() for vals in values_list
            ) + " RETURNING *"
            cur.execute(full_sql)
            if cur.description:
                return [dict(r) for r in cur.fetchall()]
            return []
        finally:
            _put_conn(conn)
    except Exception as e:
        _log.error("insert_many error: %s", e)
        raise
    finally:
        _put_conn(conn)


def _build_where(
    filters: Optional[dict[str, Any]] = None,
    eq_filters: Optional[list[tuple[str, Any]]] = None,
    raw_params: Optional[dict[str, str]] = None,
) -> tuple[list[sql.Composable], list]:
    """Build WHERE conditions from filter dicts. Returns (condition_parts, param_list)."""
    conditions: list[sql.Composable] = []
    params: list[Any] = []

    if filters:
        for col, val in filters.items():
            conditions.append(sql.SQL("{} = %s").format(_ident(col)))
            params.append(val)

    if eq_filters:
        for col, val in eq_filters:
            conditions.append(sql.SQL("{} = %s").format(_ident(col)))
            params.append(val)

    if raw_params:
        for col, expr in raw_params.items():
            col_id = _ident(col)
            if expr == "eq.true":
                conditions.append(sql.SQL("{} = %s").format(col_id))
                params.append(True)
            elif expr == "eq.false":
                conditions.append(sql.SQL("{} = %s").format(col_id))
                params.append(False)
            elif expr.startswith("eq."):
                conditions.append(sql.SQL("{} = %s").format(col_id))
                params.append(expr[3:])
            elif expr == "not.is.null":
                conditions.append(sql.SQL("{} IS NOT NULL").format(col_id))
            elif expr.startswith("is."):
                val = expr[3:]
                if val == "null":
                    conditions.append(sql.SQL("{} IS NULL").format(col_id))
                else:
                    conditions.append(sql.SQL("{} = %s").format(col_id))
                    params.append(val)
            else:
                conditions.append(sql.SQL("{} = %s").format(col_id))
                params.append(expr)

    return conditions, params


def _compose_where(conditions: list[sql.Composable]) -> sql.Composable:
    if conditions:
        return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
    return sql.SQL("")


def _parse_order(order: Optional[str]) -> sql.Composable:
    """Convert PostgREST-style order (col.desc) to SQL ORDER BY."""
    if not order:
        return sql.SQL("")
    parts = order.split(".")
    col = parts[0]
    direction = parts[1].upper() if len(parts) > 1 else "ASC"
    if direction not in ("ASC", "DESC"):
        direction = "ASC"
    return sql.SQL(" ORDER BY {} {}").format(_ident(col), sql.SQL(direction))


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
    conditions, params = _build_where(filters, eq_filters, raw_params)
    where_clause = _compose_where(conditions)
    order_clause = _parse_order(order)
    limit_clause = sql.SQL(" LIMIT {}").format(sql.Literal(limit)) if limit else sql.SQL("")

    if columns == "*":
        col_sql = sql.SQL("*")
    else:
        col_parts = [c.strip() for c in columns.split(",")]
        col_sql = sql.SQL(", ").join(_ident(c) for c in col_parts)

    query = sql.SQL("SELECT {} FROM {}").format(col_sql, _ident(table)) + where_clause + order_clause + limit_clause
    rows = _execute_composed(query, tuple(params))

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
    set_parts = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(_ident(c)) for c in data.keys()
    )
    set_vals = list(data.values())

    conditions, where_params = _build_where(filters, eq_filters)
    if not conditions:
        raise ValueError("update() requires filters")
    where_clause = _compose_where(conditions)

    query = sql.SQL("UPDATE {} SET {} {} RETURNING *").format(
        _ident(table), set_parts, where_clause
    )
    return _execute_composed(query, tuple(set_vals + where_params))


def delete(
    table: str,
    *,
    filters: Optional[dict[str, Any]] = None,
    eq_filters: Optional[list[tuple[str, Any]]] = None,
    raw_params: Optional[dict[str, str]] = None,
    delete_all: bool = False,
) -> list[dict]:
    conditions, params = _build_where(filters, eq_filters, raw_params)
    where_clause = _compose_where(conditions)

    if not conditions and not delete_all:
        raise ValueError("delete() requires filters or delete_all=True")

    query = sql.SQL("DELETE FROM {} {} RETURNING *").format(_ident(table), where_clause)
    return _execute_composed(query, tuple(params))


def update_many_concurrent(
    table: str,
    updates: list[tuple[dict, dict]],
    *,
    max_workers: int = 10,
) -> int:
    """Batch UPDATE using a single connection for speed.

    Each entry in *updates* is (filter_dict, data_dict).
    Returns the count of successful updates.
    """
    if not updates:
        return 0

    _validate_ident(table)
    conn = _get_conn()
    ok = 0
    try:
        cur = conn.cursor()
        stmts = []
        for filt, data in updates:
            set_parts = []
            params = []
            for col, val in data.items():
                set_parts.append(sql.SQL("{} = %s").format(_ident(col)))
                params.append(val)
            where_parts = []
            for col, val in filt.items():
                where_parts.append(sql.SQL("{} = %s").format(_ident(col)))
                params.append(val)
            query = sql.SQL("UPDATE {} SET {} WHERE {}").format(
                _ident(table),
                sql.SQL(", ").join(set_parts),
                sql.SQL(" AND ").join(where_parts),
            )
            stmts.append(cur.mogrify(query.as_string(conn), tuple(params)).decode())
        if stmts:
            cur.execute("; ".join(stmts))
            ok = len(stmts)
    except Exception as exc:
        _log.error("update_many_concurrent error: %s", exc)
        _put_conn(conn, broken=True)
        raise
    finally:
        _put_conn(conn)
    return ok


def rpc(function_name: str, params: Optional[dict] = None) -> Any:
    """Call a stored function/procedure."""
    _validate_ident(function_name)
    if params:
        placeholders = sql.SQL(", ").join([sql.Placeholder()] * len(params))
        query = sql.SQL("SELECT * FROM {}({})").format(_ident(function_name), placeholders)
        rows = _execute_composed(query, tuple(params.values()))
    else:
        query = sql.SQL("SELECT * FROM {}()").format(_ident(function_name))
        rows = _execute_composed(query)
    return rows


def table_exists(table_name: str) -> bool:
    try:
        query = sql.SQL(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=%s)"
        )
        rows = _execute_composed(query, (table_name,))
        return rows[0].get("exists", False) if rows else False
    except Exception:
        return False
