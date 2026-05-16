"""Persistent canonical registry — DISP #24 (architectural fix for aam_deferred_work.md#24).

Replaces the in-memory CanonicalRegistry at app/ingest/resolver.py:201 with
a Postgres-backed source of truth. The previous registry was:
  - process-local (lost on pm2 restart → Goal A violated)
  - unbounded per-tenant within the process (Goal B at risk)
  - fast for tier-1 hash lookups, O(N) for tier-4 fuzzy scans

This module exposes the same public interface as the in-memory class:
  - add_canonical(tenant_id, domain, value, canonical_id?, aliases?) → CanonicalEntry
  - find_exact(tenant_id, domain, value) → Optional[CanonicalEntry]
  - find_alias(tenant_id, domain, value) → Optional[CanonicalEntry]
  - iter_canonicals(tenant_id, domain) → Iterable[CanonicalEntry]
  - add_alias(tenant_id, domain, alias, canonical_id) → None
  - add_pattern_rule(tenant_id, domain, pattern, canonical_id, canonical_value) → None
  - find_pattern(tenant_id, domain, value) → Optional[CanonicalEntry]

Backing store: AAM Postgres table canonical_registry (see app/db/schema.py
migration 'create_canonical_registry_table').

Pattern rules: not yet persisted — today they're configured in code at
process boundary and behave the same way the in-memory class did. A future
migration can add a canonical_pattern_rules table; current call sites do
not mutate pattern rules at runtime.

Concurrency: discovery uses INSERT ... ON CONFLICT DO NOTHING RETURNING so
two concurrent workers minting the same normalized value converge to one
canonical_id. Aliases are JSONB array on the canonical row; alias additions
use a SELECT + UPDATE under no lock (alias contention is unusual; if it
becomes a problem we can switch to JSONB array set ops).

Performance: the in-memory class iterated a dict. PG-backed, that's a
SELECT per fuzzy scan call. To preserve the O(records-in-batch) cost the
resolver caller (webhooks._ingest_rows) typically resolves a list of
records against the same (tenant_id, domain). _SnapshotCache materializes
the list once per (tenant_id, domain) and TTLs out after 60s so memory
stays bounded (cache holds at most a few small lists, not the whole
table).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

_log = logging.getLogger("aam.db.canonical_registry")

_NORM_SEP = re.compile(r"[\s\-_./,;:]+")


def _normalize(s: str) -> str:
    """Lowercase + collapse separator runs to single space. Strip ends.

    Mirrors app/ingest/resolver._normalize. Kept duplicated here so this
    module doesn't import from app/ingest/ (which would create a cycle).
    """
    t = _NORM_SEP.sub(" ", str(s)).lower().strip()
    return t


# ---------------------------------------------------------------------------
# CanonicalEntry — public dataclass, matches resolver.CanonicalEntry shape
# ---------------------------------------------------------------------------

@dataclass
class CanonicalEntry:
    """One row in the per-domain canonical registry."""
    canonical_id: str
    value: str
    domain: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class PatternRule:
    """One pattern -> canonical_id binding. Regex pre-compiled."""
    domain: str
    pattern: re.Pattern
    canonical_id: str
    canonical_value: str


# ---------------------------------------------------------------------------
# Snapshot cache — bounded, TTL-evicted, source-of-truth-safe
# ---------------------------------------------------------------------------

# The cache holds list[CanonicalEntry] keyed by (tenant_id, domain). LRU
# eviction policy: at most _MAX_KEYS distinct (tenant_id, domain) tuples,
# each entry expires after _TTL_SECONDS. Eviction never loses persistent
# state — the source of truth is the canonical_registry table; cache is
# a recency optimization.
_TTL_SECONDS = 60.0
_MAX_KEYS = 64


class _SnapshotCache:
    """Thread-safe TTL+LRU cache of per-(tenant_id, domain) snapshots."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # value: (snapshot_list, expires_at_monotonic, last_access_monotonic)
        self._data: dict[tuple[str, str], tuple[list[CanonicalEntry], float, float]] = {}

    def get(self, key: tuple[str, str]) -> Optional[list[CanonicalEntry]]:
        with self._lock:
            tup = self._data.get(key)
            if tup is None:
                return None
            snapshot, expires_at, _ = tup
            now = time.monotonic()
            if now >= expires_at:
                self._data.pop(key, None)
                return None
            self._data[key] = (snapshot, expires_at, now)
            return snapshot

    def put(self, key: tuple[str, str], snapshot: list[CanonicalEntry]) -> None:
        with self._lock:
            now = time.monotonic()
            self._data[key] = (snapshot, now + _TTL_SECONDS, now)
            # LRU eviction if over capacity
            if len(self._data) > _MAX_KEYS:
                oldest_key = min(self._data, key=lambda k: self._data[k][2])
                self._data.pop(oldest_key, None)

    def invalidate(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        """Test helper — flush all entries."""
        with self._lock:
            self._data.clear()


_SNAPSHOTS = _SnapshotCache()


# ---------------------------------------------------------------------------
# CanonicalRegistry — PG-backed implementation
# ---------------------------------------------------------------------------

class CanonicalRegistry:
    """Canonical registry persisted in AAM Postgres.

    Public methods preserve the WP3 4-tier resolver contract. Process-local
    state is bounded to _SnapshotCache (TTL=60s, ≤64 keys). The
    canonical_registry table is the source of truth.
    """

    def __init__(self) -> None:
        # Pattern rules remain in-process; see module docstring.
        self._pattern_rules: dict[tuple[str, str], list[PatternRule]] = {}

    # ---- mutations -------------------------------------------------------

    def add_canonical(
        self,
        *,
        tenant_id: str,
        domain: str,
        value: str,
        canonical_id: Optional[str] = None,
        aliases: Optional[list[str]] = None,
    ) -> CanonicalEntry:
        """Insert or return existing canonical. Idempotent on (tenant, domain, norm)."""
        if not tenant_id or not domain or not value:
            raise ValueError(
                f"add_canonical: tenant_id, domain, value required "
                f"(got tenant_id={tenant_id!r} domain={domain!r} value={value!r})"
            )
        norm = _normalize(value)
        if not norm:
            raise ValueError(
                f"add_canonical: value normalizes to empty string ({value!r})"
            )
        cid = canonical_id or str(uuid.uuid4())
        alias_list = list(aliases or [])

        # INSERT ... ON CONFLICT DO NOTHING RETURNING. If another writer beat
        # us to this normalized value, fall back to SELECT for the existing
        # canonical_id (the returning will be empty on conflict).
        from . import supabase_client as sb
        from psycopg2 import sql as psql
        insert_sql = psql.SQL(
            "INSERT INTO canonical_registry "
            "(canonical_id, tenant_id, domain, normalized_value, original_value, aliases_jsonb) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb) "
            "ON CONFLICT (tenant_id, domain, normalized_value) DO NOTHING "
            "RETURNING canonical_id, original_value, aliases_jsonb"
        )
        rows = sb._execute_composed(
            insert_sql,
            (cid, tenant_id, domain, norm, str(value), json.dumps(alias_list)),
        )
        if rows:
            row = rows[0]
            _SNAPSHOTS.invalidate((tenant_id, domain))
            return CanonicalEntry(
                canonical_id=str(row["canonical_id"]),
                value=row["original_value"],
                domain=domain,
                aliases=list(row.get("aliases_jsonb") or []),
            )
        # Conflict — fetch the existing row.
        existing = sb._execute_composed(
            psql.SQL(
                "SELECT canonical_id, original_value, aliases_jsonb FROM canonical_registry "
                "WHERE tenant_id=%s AND domain=%s AND normalized_value=%s"
            ),
            (tenant_id, domain, norm),
        )
        if not existing:
            raise RuntimeError(
                f"add_canonical: ON CONFLICT returned nothing AND no row found "
                f"for (tenant_id={tenant_id!r}, domain={domain!r}, value={value!r}) — "
                f"DB inconsistency"
            )
        row = existing[0]
        return CanonicalEntry(
            canonical_id=str(row["canonical_id"]),
            value=row["original_value"],
            domain=domain,
            aliases=list(row.get("aliases_jsonb") or []),
        )

    def add_alias(self, *, tenant_id: str, domain: str, alias: str, canonical_id: str) -> None:
        if not alias or not canonical_id:
            raise ValueError("add_alias: alias and canonical_id required")
        from . import supabase_client as sb
        from psycopg2 import sql as psql
        # Append alias to aliases_jsonb if not already present.
        update_sql = psql.SQL(
            "UPDATE canonical_registry "
            "SET aliases_jsonb = CASE "
            "  WHEN aliases_jsonb @> to_jsonb(%s::text) THEN aliases_jsonb "
            "  ELSE aliases_jsonb || to_jsonb(%s::text) "
            "END, "
            "updated_at = now() "
            "WHERE canonical_id=%s AND tenant_id=%s AND domain=%s"
        )
        sb._execute_composed(
            update_sql, (alias, alias, canonical_id, tenant_id, domain), fetch=False,
        )
        _SNAPSHOTS.invalidate((tenant_id, domain))

    def add_pattern_rule(
        self, *, domain: str, pattern: str, canonical_id: str,
        canonical_value: str, tenant_id: str,
    ) -> None:
        """Pattern rules remain in-process (no runtime mutation today)."""
        rule = PatternRule(
            domain=domain,
            pattern=re.compile(pattern, re.IGNORECASE),
            canonical_id=canonical_id,
            canonical_value=canonical_value,
        )
        self._pattern_rules.setdefault((tenant_id, domain), []).append(rule)

    # ---- queries ---------------------------------------------------------

    def _snapshot(self, *, tenant_id: str, domain: str) -> list[CanonicalEntry]:
        """Load or return cached list of all canonicals for (tenant, domain).

        The snapshot is the unit shared across tier-1 hash lookup, tier-2
        alias scan, tier-4 fuzzy scan within a single webhook batch. The
        TTL cache amortizes the PG read across the batch.
        """
        key = (tenant_id, domain)
        cached = _SNAPSHOTS.get(key)
        if cached is not None:
            return cached
        from . import supabase_client as sb
        from psycopg2 import sql as psql
        rows = sb._execute_composed(
            psql.SQL(
                "SELECT canonical_id, original_value, aliases_jsonb FROM canonical_registry "
                "WHERE tenant_id=%s AND domain=%s"
            ),
            (tenant_id, domain),
        )
        snapshot = [
            CanonicalEntry(
                canonical_id=str(r["canonical_id"]),
                value=r["original_value"],
                domain=domain,
                aliases=list(r.get("aliases_jsonb") or []),
            )
            for r in rows
        ]
        _SNAPSHOTS.put(key, snapshot)
        return snapshot

    def find_exact(self, *, tenant_id: str, domain: str, value: str) -> Optional[CanonicalEntry]:
        norm = _normalize(value)
        if not norm:
            return None
        # Use snapshot if warm; otherwise direct lookup is cheaper for a cold
        # tier-1 hit (avoids loading the whole list to find one).
        cached = _SNAPSHOTS.get((tenant_id, domain))
        if cached is not None:
            for e in cached:
                if _normalize(e.value) == norm:
                    return e
            return None
        from . import supabase_client as sb
        from psycopg2 import sql as psql
        rows = sb._execute_composed(
            psql.SQL(
                "SELECT canonical_id, original_value, aliases_jsonb FROM canonical_registry "
                "WHERE tenant_id=%s AND domain=%s AND normalized_value=%s"
            ),
            (tenant_id, domain, norm),
        )
        if not rows:
            return None
        r = rows[0]
        return CanonicalEntry(
            canonical_id=str(r["canonical_id"]),
            value=r["original_value"],
            domain=domain,
            aliases=list(r.get("aliases_jsonb") or []),
        )

    def find_alias(self, *, tenant_id: str, domain: str, value: str) -> Optional[CanonicalEntry]:
        """Scan the snapshot for any canonical whose aliases contain the normalized value."""
        norm = _normalize(value)
        if not norm:
            return None
        for entry in self._snapshot(tenant_id=tenant_id, domain=domain):
            for alias in entry.aliases:
                if _normalize(alias) == norm:
                    return entry
        return None

    def find_pattern(self, *, tenant_id: str, domain: str, value: str) -> Optional[CanonicalEntry]:
        """Pattern rules remain in-process. Synthesize canonical row if rule matches but no row exists."""
        for rule in self._pattern_rules.get((tenant_id, domain), []):
            if rule.pattern.search(value):
                snapshot = self._snapshot(tenant_id=tenant_id, domain=domain)
                for entry in snapshot:
                    if entry.canonical_id == rule.canonical_id:
                        return entry
                # Canonical doesn't exist yet — mint with the rule's value.
                return self.add_canonical(
                    tenant_id=tenant_id, domain=domain,
                    canonical_id=rule.canonical_id, value=rule.canonical_value,
                )
        return None

    def iter_canonicals(self, *, tenant_id: str, domain: str) -> Iterable[CanonicalEntry]:
        return iter(self._snapshot(tenant_id=tenant_id, domain=domain))

    # ---- test helpers ----------------------------------------------------

    def reset_for_tenant(self, *, tenant_id: str) -> int:
        """Delete all canonical entries for a tenant. Test-only.

        Mirrors hitl_store.reset_for_tenant for symmetry. Returns the row
        count deleted.
        """
        if not tenant_id:
            raise ValueError("reset_for_tenant: tenant_id required")
        from . import supabase_client as sb
        from psycopg2 import sql as psql
        sb._execute_composed(
            psql.SQL("DELETE FROM canonical_registry WHERE tenant_id=%s"),
            (tenant_id,), fetch=False,
        )
        # Invalidate all snapshot keys for this tenant. There's no
        # tenant-scoped iteration on _SnapshotCache, so the simplest correct
        # action is to clear the whole cache — under test usage that's fine.
        _SNAPSHOTS.clear()
        # Row count isn't returned by _execute_composed for non-fetch ops;
        # callers that need a count can SELECT before delete.
        return 0
