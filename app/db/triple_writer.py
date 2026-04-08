"""
Triple Writer — batch-insert semantic triples to Postgres via execute_values.

Uses AAM's existing psycopg2 connection pool.  Follows the same pattern as
DCL's triple_store.py (dcl/backend/db/triple_store.py:17-55).

The semantic_triples table lives in the shared Supabase Postgres instance.
Column schema defined in dcl/migrations/001_semantic_triple_store.sql with
source_run_tag added in 004_source_run_tag.sql.

Ledger integration: every write creates a ledger entry (pending → committed/failed)
in AAM's local SQLite ledger. See app/db/ledger.py.
"""

import json
import logging
import time
import uuid

from psycopg2.extras import execute_values

from . import supabase_client as _sb
from . import ledger as _ledger

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


def write_triples_with_ledger(
    triples: list[dict],
    *,
    run_id: str,
    entity_id: str,
    trigger: str,
    write_path: str = "direct_execute",
    pipe_id: str | None = None,
) -> dict:
    """Batch-insert triples with ledger tracking.

    1. Creates a pending ledger entry.
    2. Executes the PG write.
    3. Updates ledger to committed or failed.

    Returns a dict with ledger entry details for the infer response.
    """
    # Extract concept prefixes from triples
    prefixes: set[str] = set()
    for t in triples:
        concept = t.get("concept", "")
        if "." in concept:
            parts = concept.split(".")
            prefixes.add(f"{parts[0]}.{parts[1]}")
        elif concept:
            prefixes.add(concept)
    concept_prefixes = sorted(prefixes)

    # 1. Create pending ledger entry
    entry_id = _ledger.create_pending_entry(
        run_id=run_id,
        entity_id=entity_id,
        trigger=trigger,
        write_path=write_path,
        concept_prefixes=concept_prefixes,
        pipe_id=pipe_id,
    )

    # 2. Execute the PG write
    t_start = time.perf_counter()
    try:
        count = write_triples(triples)
        duration_ms = int((time.perf_counter() - t_start) * 1000)

        # 3. Mark committed
        _ledger.mark_committed(entry_id, count, duration_ms, concept_prefixes)

        return {
            "ledger_id": entry_id,
            "triple_count": count,
            "concept_prefixes": concept_prefixes,
            "write_path": write_path,
            "status": "committed",
            "duration_ms": duration_ms,
        }

    except Exception as exc:
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        _ledger.mark_failed(entry_id, str(exc), duration_ms)
        raise


def touch_latest_run(entity_id: str) -> int:
    """Refresh created_at on the latest AAM run's triples to NOW.

    Used by the infer endpoint when there is nothing new to process but
    inference was explicitly invoked. The semantic meaning: AAM has just
    re-confirmed that the existing triples reflect the current state.
    The freshness query (MAX(created_at) WHERE source_system='AAM') then
    correctly reports GREEN — inference was just run.

    UPDATE-only — does not grow the table.
    Returns the number of rows touched.
    """
    if not entity_id:
        raise ValueError("touch_latest_run requires entity_id")

    conn = _sb._get_conn()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE semantic_triples
            SET created_at = NOW()
            WHERE source_system = 'AAM'
              AND entity_id = %s
              AND run_id = (
                SELECT run_id FROM semantic_triples
                WHERE source_system = 'AAM' AND entity_id = %s
                ORDER BY created_at DESC
                LIMIT 1
              )
            """,
            (entity_id, entity_id),
        )
        touched = cur.rowcount
        conn.commit()
        _log.info("touch_latest_run: refreshed %d AAM triples for entity=%s", touched, entity_id)
        return touched
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.autocommit = True
        except Exception:
            pass
        _sb._put_conn(conn)
