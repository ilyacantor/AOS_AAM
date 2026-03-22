"""
Triple Writer — batch-insert semantic triples to Postgres via execute_values.

Uses AAM's existing psycopg2 connection pool.  Follows the same pattern as
DCL's triple_store.py (dcl/backend/db/triple_store.py:17-55).

The semantic_triples table lives in the shared Supabase Postgres instance.
Column schema defined in dcl/migrations/001_semantic_triple_store.sql with
source_run_tag added in 004_source_run_tag.sql.
"""

import json
import logging
import uuid

from psycopg2.extras import execute_values

from . import supabase_client as _sb

_log = logging.getLogger("aam.db.triple_writer")

# Column order matches DCL's TripleStore.insert_triples exactly.
_COLS = [
    "tenant_id", "entity_id", "concept", "property", "value",
    "period", "currency", "unit",
    "source_system", "source_table", "source_field",
    "pipe_id", "run_id", "source_run_tag",
    "confidence_score", "confidence_tier",
    "canonical_id", "resolution_method", "resolution_confidence",
]

_COL_NAMES = ", ".join(_COLS)
_TEMPLATE = "(" + ", ".join(["%s"] * len(_COLS)) + ")"
_SQL = f"INSERT INTO semantic_triples ({_COL_NAMES}) VALUES %s"


def _to_uuid_or_none(val) -> str | None:
    """Ensure a value is a valid UUID string, or None."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        uuid.UUID(s)
        return s
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, s))


def write_triples(triples: list[dict]) -> int:
    """Batch-insert triples into semantic_triples.  Returns count inserted.

    Uses execute_values for 10-50x speedup over individual INSERTs.
    Raises on failure (caller decides whether to swallow or propagate).
    """
    if not triples:
        return 0

    conn = _sb._get_conn()
    try:
        # Use explicit transaction for atomic batch
        conn.autocommit = False
        cur = conn.cursor()

        rows = []
        for t in triples:
            row = []
            for col in _COLS:
                val = t.get(col)
                if col == "value":
                    val = json.dumps(val) if val is not None else json.dumps("")
                elif col in ("tenant_id", "run_id"):
                    val = _to_uuid_or_none(val)
                elif col in ("pipe_id", "canonical_id"):
                    val = _to_uuid_or_none(val)
                row.append(val)
            rows.append(tuple(row))

        execute_values(cur, _SQL, rows, template=_TEMPLATE, page_size=1000)
        conn.commit()

        _log.info(
            "write_triples: inserted %d triples into semantic_triples",
            len(rows),
        )
        return len(rows)

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        _log.error(
            "write_triples FAILED: %d triples, error=%s. "
            "Sample triple concept=%s property=%s. Rolling back.",
            len(triples),
            exc,
            triples[0].get("concept") if triples else "?",
            triples[0].get("property") if triples else "?",
        )
        raise
    finally:
        # Restore autocommit before returning to pool
        try:
            conn.autocommit = True
        except Exception:
            pass
        _sb._put_conn(conn)


