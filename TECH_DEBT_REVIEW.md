# AAM Technical Debt Review

**Date:** 2026-02-14
**Scope:** Full codebase audit — 60 Python files, 12,049 lines (`app/`)
**Priority bug:** Topology visualization shows generic symbols for pipes routed through API Gateway; the vendor-specific gateway node (e.g. "Kong, API Gateway") appears disconnected

---

## TABLE OF CONTENTS

1. [THE TOPOLOGY BUG — Root Cause Analysis](#1-the-topology-bug)
2. [Split-Brain Architecture (caused by the monolith split)](#2-split-brain-architecture)
3. [Hardcoded Cheats](#3-hardcoded-cheats)
4. [Undebuggable Logic](#4-undebuggable-logic)
5. [Remaining Monoliths](#5-remaining-monoliths)
6. [Janky Code](#6-janky-code)
7. [Data Model Confusion](#7-data-model-confusion)
8. [Missing Safety Nets](#8-missing-safety-nets)
9. [Remediation Plan](#9-remediation-plan)

---

## 1. THE TOPOLOGY BUG

### What the user sees
- Pipes connected to an API Gateway show a **generic diamond symbol** (UNMAPPED or bare type node)
- A separate, disconnected node shows the **actual vendor** (e.g. "Kong, API Gateway") with 0 connections
- Same issue potentially affects iPaaS, Event Bus, and Data Warehouse — API Gateway is just the most visible

### Root cause: Two parallel topology code paths that disagree

There are **THREE** independent topology implementations, each building nodes/edges from scratch with different resolution logic:

| Code path | File | Called by | Resolution logic |
|-----------|------|-----------|-----------------|
| **Full topology** | `app/db/topology.py:94` `get_topology_data()` | `/api/topology` (detail="all") | `_resolve_candidate_plane()` — looks at `fabric_plane_id` column directly, falls back to `connected_via_plane` type hint |
| **Summary topology** | `app/services/topology_service.py:34` `build_topology_summary()` | `/api/topology/summary` (DEFAULT view) | `_resolve_plane_id()` — 4-step fallback: `fabric_plane_id` → `connected_via_plane` → `matched_pipe_id` backfill → UNMAPPED |
| **Per-plane topology** | `app/db/topology.py:315` `get_topology_for_fabric_plane()` | `/api/topology/plane/{type}` | Same `_resolve_candidate_plane()` as full topology |

**The default UI view calls `/api/topology/summary`** (line 1676 of `ui_pages.py`), which uses the service-layer path. Here's the bug chain:

#### Step 1: `fabric_plane_id` on the candidate is NULL or doesn't match `plane_info` keys

In `topology_service.py:76-78`:
```python
fpid = candidate.get("fabric_plane_id", "")
if fpid and fpid in plane_info:
    return fpid
```

The `plane_info` dict is keyed by composite IDs like `"API_GATEWAY:kong"`. But `fabric_plane_id` on candidates may be:
- **NULL** — handoff didn't propagate it (the `link_candidate_to_plane` function in `handoff_service.py` returns `None` when no match)
- **Just a type** like `"API_GATEWAY"` — doesn't match the composite key `"API_GATEWAY:kong"`
- **Stale** — from a previous handoff run with different plane IDs

#### Step 2: The fallback chain creates a DIFFERENT node

When step 1 fails, the code falls through to `_extract_plane_type()` which returns just `"API_GATEWAY"` (the bare type). Then `type_to_plane.get("API_GATEWAY")` maps it to the first matching plane.

But here's the problem: the node creation loop at line 183-198 creates vendor-specific nodes keyed by `plane_id` (e.g. `"plane:API_GATEWAY:kong"`). If the fallback resolves to a *different* plane_id than what the node loop created, the edge points to a node that doesn't exist, or creates a duplicate.

#### Step 3: The UI renders two disconnected groups

The vis.js graph gets:
- A vendor-specific node `"plane:API_GATEWAY:kong"` with label "Kong, API Gateway (0 connected / 0 total)" — **orphaned, no edges point to it**
- Edges pointing to `"plane:API_GATEWAY"` (bare type) which either shows as a generic fallback node or is missing entirely

### Why this is hard to see in the code

The resolution functions are:
- `_resolve_candidate_plane()` in `db/topology.py:49` — reads raw SQLite rows with `candidate["fabric_plane_id"]`
- `_resolve_plane_id()` in `services/topology_service.py:64` — reads dicts from `list_candidates()` with `candidate.get("fabric_plane_id", "")`

They look similar but operate on **different data shapes** (sqlite3.Row vs dict) and have **different fallback chains**. The DB version has 2 fallback steps; the service version has 4. Neither shares code.

### Fix (plan, not implementation)

**Single resolution function** in `constants.py` or a new `app/topology_resolution.py`:
```
resolve_candidate_to_plane(candidate_data, plane_info_lookup) -> plane_id
```
All three topology builders call this one function. The function must guarantee that the returned `plane_id` matches a key that will be used to create a node.

Additionally: the `handoff_service.py:link_candidate_to_plane()` should **write the resolved `fabric_plane_id` back to the candidate row** so the topology code never needs to re-resolve. Currently it returns the plane_id but the handoff code at `process_handoff()` stores it — however if it returns `None`, the candidate gets NULL in the DB, and the topology code has to re-derive it every time.

---

## 2. SPLIT-BRAIN ARCHITECTURE

The monolith split (main.py → routers + services + db/) was necessary but created a new class of bugs: **duplicated logic that drifted**.

### 2a. Three copies of `PLANE_LABELS` / `PLANE_COLORS`

| Location | Dict name | Used by |
|----------|-----------|---------|
| `constants.py:24` | `PLANE_TYPE_LABELS` | Reconciliation UI, handoff |
| `db/topology.py:19` | `_PLANE_LABELS` | Full + per-plane topology |
| `services/topology_service.py:17` | `PLANE_LABELS` | Summary topology |

These are identical today but are three independent copies. A new plane type added to one but not the others will silently break.

### 2b. Two independent `_resolve_candidate_plane` implementations

As detailed in section 1. `db/topology.py:49` and `services/topology_service.py:64` implement the same concept with different logic.

### 2c. Two `_make_plane_node` / node-creation patterns

`db/topology.py:63` has `_make_plane_node()`. `services/topology_service.py:183-198` has an inline loop that does the same thing differently. The label formats differ:
- DB version: `"Kong, API Gateway"` (no counts)
- Service version: `"Kong, API Gateway\n(5 connected / 10 total)"` (with counts)

The UI code doesn't know which format it's getting — it just renders whatever `label` field it receives.

### 2d. main.py is still 254 lines with duplicate route handlers

`main.py:222-253` defines candidate CRUD endpoints (`/api/aam/candidates`) that duplicate the routes in `routers/candidates.py`. Both are mounted. Depending on router ordering, one shadows the other.

---

## 3. HARDCODED CHEATS

### 3a. `transport_kind: "API"` hardcoded default

`db/pipes.py:257` — `_candidate_to_pipe()`:
```python
"transport_kind": "API",  # Default
```
Every candidate-converted-to-pipe gets `API` regardless of whether it's a Kafka topic (EVENT_STREAM), a Snowflake table (TABLE), or a webhook (WEBHOOK). The inference engine (`inference.py:190`) has proper `infer_transport_kind()` logic but it's never called in this path.

### 3b. `modality` hardcoded from category string matching

`db/pipes.py:248-249`:
```python
category_lower = row["category"].lower() if row["category"] else ""
modality = "CONTROL_PLANE" if "ipaas" in category_lower else "DECLARED_INTERFACE"
```
Binary choice: if the category contains "ipaas" → CONTROL_PLANE, everything else → DECLARED_INTERFACE. Ignores PASSIVE_SUBSCRIPTION and MINIMAL_TEE entirely. The inference engine has proper modality detection but again, not called here.

### 3c. `change_semantics: "UNKNOWN"` for all candidate-derived pipes

`db/pipes.py:261` — always `"UNKNOWN"`. The inference engine can detect CDC_UPSERT, APPEND_ONLY, and SNAPSHOT but the candidate-to-pipe path bypasses inference entirely.

### 3d. `execution_allowed` defaults to `1` (True) in DDL

`db/schema.py:38`:
```sql
execution_allowed INTEGER DEFAULT 1
```
The column default is permissive. The code comment in `db/candidates.py:28` says *"AOD must explicitly grant permission, not permissive-by-default"* but the schema contradicts this. If a candidate is inserted without an explicit `execution_allowed` value (e.g. from the legacy `/api/aam/candidates` endpoint), it defaults to allowed.

### 3e. `action_type` defaults to `'provision'` in DDL

`db/schema.py:39`:
```sql
action_type TEXT DEFAULT 'provision'
```
Same issue — the default bypasses governance review. Should default to `'inventory_only'` if anything.

### 3f. `identity_keys: []` — always empty for candidate-derived pipes

`db/pipes.py:260`. Identity keys are never inferred in the candidate-to-pipe path.

### 3g. SOR category set duplicated as both Python set and SQL

`constants.py:15` defines `SOR_CATEGORIES` as a Python set. But `db/topology.py:184-190` builds a SQL `IN` clause from it at runtime with string interpolation. If the set grows, the SQL grows unboundedly.

---

## 4. UNDEBUGGABLE LOGIC

### 4a. The 4-step plane resolution fallback with warning-only logging

`topology_service.py:64-108` — `_resolve_plane_id()` has a 4-step fallback chain where each step logs a `_log.warning()` then falls through. In production with 654 candidates, this fires hundreds of warnings per page load with no way to distinguish "expected fallback" from "actual data problem". The warnings drown out real issues.

### 4b. Adapter implementations are 100% simulated

All four adapter files (`ipaas.py`, `gateway.py`, `eventbus.py`, `warehouse.py`) return hardcoded fake data:
```python
# gateway.py — every adapter method returns mock data
async def discover_assets(self) -> list:
    return [{"id": "mock-api-1", "name": "Mock API", ...}]
```
There is no way to know if the adapter interface actually works because it has never been tested against a real system. The abstract base class (`base.py`) defines the contract but the implementations are all `pass`-equivalent with fake returns.

### 4c. `except Exception` catch-alls hide real errors

Locations:
- `handoff_service.py:172` — `except Exception as e: _log.error(...)` during plane storage. The handoff continues with partial plane data.
- `db/topology.py` line-level try/except isn't present, but the caller in `routers/topology.py` has no error handling — a single bad row crashes the entire topology.
- All four adapter files catch `Exception` and return empty/mock results.

### 4d. `_candidate_to_pipe()` is a lossy transformation buried in the DB layer

`db/pipes.py:230-275` — This function converts candidates to pipes for UI display. It's in the **database** package but contains **business logic** (modality inference, trust label extraction). If you're debugging why a pipe shows the wrong modality, you'd look in `inference.py` or `services/` — not in `db/pipes.py`.

### 4e. No request tracing / correlation IDs

The logger uses `aam.*` namespaces but there are no correlation IDs tying a request to its downstream operations. A handoff that processes 654 candidates produces 654+ log lines with no way to filter by request.

### 4f. Schema migrations are invisible

`db/connection.py` imports `_add_column_if_not_exists` which silently adds columns. `db/schema.py` calls `init_db()` on every startup. There's no version tracking, no migration log, no way to know what schema version the database is at. If a migration fails partway, the database is in an unknown state.

---

## 5. REMAINING MONOLITHS

### 5a. `ui_pages.py` — 2,728 lines of inline HTML/CSS/JS

This is the new monolith. The old `main.py` monolith was split, but all the UI rendering moved here as a single file. It contains:
- 6 full HTML pages with embedded CSS
- ~300 lines of JavaScript for the vis.js topology graph
- Inline Python f-string templating (double-brace escaping everywhere: `{{`, `}}`)
- No template engine — impossible to edit HTML without touching Python

The topology JavaScript alone (lines 1650-1984) is ~334 lines of inline JS inside a Python f-string. Any syntax error in the JS crashes the Python route handler.

### 5b. `db/reconciliation.py` — 635 lines

The reconciliation module does deep cross-table comparisons with complex SQL joins. It's the largest single DB module and contains both data access AND presentation logic (formatting reconciliation reports with human-readable strings).

### 5c. `db/topology.py` — 418 lines with 3 separate graph builders

Three independent functions that each build a complete graph from scratch, each scanning the full `connection_candidates` table. For 654 candidates, the full topology endpoint runs 3+ SQL queries and builds hundreds of nodes/edges.

---

## 6. JANKY CODE

### 6a. Double-brace hell in ui_pages.py

Every JavaScript object literal, CSS rule, and f-string in `ui_pages.py` requires `{{` and `}}` escaping. This makes the code nearly unreadable:
```python
const nodeColors = {{
    fabric_plane: {{
        'IPAAS': '#22d3ee',
        'API_GATEWAY': '#a78bfa',
```
A single missing `{` or `}` produces a Python `KeyError` at import time with no line number pointing to the JS.

### 6b. `delete + insert` instead of UPSERT

`db/candidates.py:33-34`:
```python
cursor.execute("DELETE FROM connection_candidates WHERE asset_key = ?", (asset_key,))
# then INSERT
```
`db/fabric_planes.py:27`:
```python
cursor.execute("DELETE FROM fabric_planes WHERE plane_id = ?", (plane_id,))
# then INSERT
```
SQLite supports `INSERT OR REPLACE` and `ON CONFLICT DO UPDATE`. The delete-then-insert pattern loses the `candidate_id` (new UUID each time), breaking any foreign key relationships or cached references.

### 6c. No connection pooling — new connection per operation

Every DB function calls `get_connection()` which opens a new SQLite connection, uses it, and closes it. A single topology page load triggers 3-5 separate connections. The `get_db()` context manager exists but is only used in `handoff_service.py:128` — everywhere else uses `get_connection()` directly.

### 6d. `plane_id.split(":")[0]` pattern repeated 6 times

The composite plane ID format (`"TYPE:vendor"`) is parsed by splitting on `:` in:
- `db/topology.py:130, 242, 357`
- `services/topology_service.py:27`
- `services/handoff_service.py:197`
- `db/pipes.py:238`

No helper function, no named constant for the delimiter. If the format ever changes (unlikely but possible), 6 files need updating.

### 6e. `NAV_HTML.format()` with positional named args

`main.py:172`:
```python
NAV_HTML.format(pipes_active="", candidates_active="", drift_active="", guide_active="", docs_active=" active")
```
The nav template uses 5+ named format parameters. Missing one crashes at runtime. The newer `ui_nav()` helper function (in `ui/styles.py`) replaces this but `main.py` still uses the old pattern.

### 6f. Mixed connection handling patterns

```python
# Pattern A (manual): used in ~90% of db/ functions
conn = get_connection()
cursor = conn.cursor()
# ... do work ...
conn.close()

# Pattern B (context manager): used in handoff_service.py only
with get_db() as conn:
    conn.execute(...)
```
Pattern A doesn't handle exceptions — if the query throws, `conn.close()` is never called.

### 6g. `_row_to_candidate()` defensive field checking

`db/candidates.py:158-181` — checks `if "field_name" in keys` for every optional field before accessing it. This is because the schema has evolved over time with `_add_column_if_not_exists()` and old rows might not have all columns. But SQLite `ALTER TABLE ADD COLUMN` gives all existing rows `NULL` for new columns, so the `in keys` check is unnecessary after migration runs.

---

## 7. DATA MODEL CONFUSION

### 7a. "Candidates ARE pipes" — except when they're not

The docstring in `db/topology.py:1-6` says:
> *"candidates ARE pipes. There is no separate `declared_pipes` table to read from — `connection_candidates` is the single source of truth."*

But `declared_pipes` **does** exist as a table (`db/schema.py`), `db/pipes.py` has full CRUD for it, and `topology_service.py:59` reads from it:
```python
for p in list_declared_pipes():
    fp = p.get("fabric_plane")
```

The system has TWO sources of truth that claim to be THE source of truth. Some code reads from `connection_candidates`, some from `declared_pipes`, some from both.

### 7b. `pipe_id` = `candidate_id` — implicit, nowhere documented in schema

`db/pipes.py:252`:
```python
"pipe_id": row["candidate_id"],  # Candidate ID = Pipe ID
```
This identity mapping only exists in `_candidate_to_pipe()`. The `declared_pipes` table has its own `pipe_id` column that is NOT the same as `candidate_id`. Whether a given `pipe_id` refers to a candidate or a declared pipe depends on which code path created it.

### 7c. `fabric_plane_id` column vs `connected_via_plane` column

Candidates have BOTH:
- `fabric_plane_id` — the resolved composite ID (e.g. `"API_GATEWAY:kong"`)
- `connected_via_plane` — the AOD routing hint (e.g. `"API_GATEWAY"`)

These serve different purposes but the topology code uses them interchangeably as fallbacks, and the handoff code only writes `fabric_plane_id` when `link_candidate_to_plane()` returns non-None.

---

## 8. MISSING SAFETY NETS

### 8a. No foreign keys

SQLite foreign keys are off by default and nowhere in the codebase is `PRAGMA foreign_keys = ON` set. The `fabric_plane_id` on candidates has no FK constraint to `fabric_planes.plane_id`. Stale/invalid plane IDs persist silently.

### 8b. No unique constraint on `asset_key`

The dedup logic uses `DELETE WHERE asset_key = ? ... INSERT` but there's no `UNIQUE` constraint on `asset_key`. If two concurrent requests insert the same `asset_key`, both succeed. (Less likely with SQLite serialized writes, but still a schema smell.)

### 8c. 788 lines of tests for 12,049 lines of code

6.5% test coverage by line count, and most tests are integration-level (`test_harness.py` requires a running server). No unit tests for:
- Inference engine (`inference.py` — 557 lines)
- Topology resolution (the bug described in section 1)
- Plane linkage (`handoff_service.py:link_candidate_to_plane`)
- PII redaction (`pii_redaction.py` — 229 lines)
- Fabric drift detection (`fabric_drift.py` — 317 lines)

### 8d. No index on `connection_candidates.fabric_plane_id`

Every topology query scans the full `connection_candidates` table and joins/filters by `fabric_plane_id`. No index exists. At 654 rows this is fine; at 10k it won't be.

---

## 9. REMEDIATION PLAN

### Phase A — Fix the topology bug (URGENT)

**Goal:** Pipes visually connect to their correct vendor-specific fabric plane node.

| Step | What | Where |
|------|------|-------|
| A1 | Create `resolve_candidate_to_plane(candidate, plane_lookup) -> plane_id` as the ONE resolution function | New: `app/plane_resolution.py` |
| A2 | Replace `_resolve_candidate_plane()` in `db/topology.py` with call to A1 | `db/topology.py:49` |
| A3 | Replace `_resolve_plane_id()` in `services/topology_service.py` with call to A1 | `services/topology_service.py:64` |
| A4 | Ensure `handoff_service.py:link_candidate_to_plane()` writes a non-NULL `fabric_plane_id` for every candidate — use `"UNMAPPED"` sentinel instead of NULL | `services/handoff_service.py:178` |
| A5 | Consolidate `PLANE_LABELS` / `PLANE_COLORS` into `constants.py` only — delete the copies in `db/topology.py` and `services/topology_service.py` | 3 files |
| A6 | Add unit test: given a candidate with `connected_via_plane=API_GATEWAY` and a fabric plane `API_GATEWAY:kong`, assert resolution returns `API_GATEWAY:kong` and the topology edge target matches the node ID | New: `tests/test_topology_resolution.py` |

### Phase B — Eliminate the split-brain

| Step | What |
|------|------|
| B1 | Single `build_plane_node(plane_id, plane_info, counts)` function shared by all topology builders |
| B2 | Single `build_topology_graph(candidates, planes, mode)` that all three endpoints call with different `mode` (full / summary / per-plane) |
| B3 | Remove duplicate route handlers in `main.py:222-253` — keep only the routers |
| B4 | Extract the `plane_id.split(":")[0]` pattern into `parse_plane_type(plane_id) -> str` in `constants.py` |

### Phase C — Unwire the hardcoded cheats

| Step | What |
|------|------|
| C1 | Call `infer_transport_kind()` in `_candidate_to_pipe()` instead of hardcoding `"API"` |
| C2 | Call `infer_modality()` in `_candidate_to_pipe()` instead of the `"ipaas" in category` hack |
| C3 | Change schema defaults: `execution_allowed DEFAULT NULL`, `action_type DEFAULT 'inventory_only'` |
| C4 | Move `_candidate_to_pipe()` from `db/pipes.py` to `services/` — it's business logic, not data access |

### Phase D — Make it debuggable

| Step | What |
|------|------|
| D1 | Add `aod_run_id` correlation to all topology + handoff log messages |
| D2 | Downgrade the 4-step fallback warnings in topology_service to `DEBUG`; add a single `INFO` summary: "Resolved N candidates: X direct, Y fallback, Z unmapped" |
| D3 | Schema version tracking: add `schema_version` table, numbered migrations |
| D4 | Replace `delete + insert` dedup with `INSERT OR REPLACE` / `ON CONFLICT DO UPDATE` in candidates and fabric_planes |

### Phase E — Break the new monolith (ui_pages.py)

| Step | What |
|------|------|
| E1 | Extract topology JS into `app/static/topology.js` — serve as static file, eliminate double-brace escaping |
| E2 | Move HTML templates to Jinja2 (already in dependencies) |
| E3 | Split `ui_pages.py` into one file per page: `ui_topology.py`, `ui_pipes.py`, `ui_reconcile.py`, etc. |

### Phase F — Safety nets

| Step | What |
|------|------|
| F1 | Add `PRAGMA foreign_keys = ON` to `get_connection()` |
| F2 | Add `UNIQUE` constraint on `connection_candidates.asset_key` |
| F3 | Add index on `connection_candidates.fabric_plane_id` |
| F4 | Unit tests for topology resolution, plane linkage, and inference engine |
| F5 | Standardize on `get_db()` context manager everywhere — remove bare `get_connection()` pattern |

---

## PRIORITY ORDER

```
Phase A  ← fixes the visible bug, do first
Phase B  ← prevents the bug from recurring
Phase C  ← correctness of pipe metadata
Phase D  ← makes future bugs findable
Phase E  ← developer velocity
Phase F  ← prevents data corruption
```

Phases A + B can be done in a single focused sprint. C and D are independent and can be parallelized. E is a larger refactor that should come last.
