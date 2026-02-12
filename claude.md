# AOS_AAM — Adaptive API Mesh

## Project Overview

AAM is the integration-fabric discovery and cataloging layer within the AutonomOS (AOS) platform. It sits between **AOD** (Asset & Operations Discovery) and **DCL** (Data Contract Layer):

```
AOD (discovers assets + governance) → AAM (catalogs pipes) → DCL (unifies meaning)
```

AAM does **not** move data. It observes existing connections, catalogs them as `DeclaredPipe` objects, documents their behavior/metadata, and self-heals connectivity drift.

## Tech Stack

- **Runtime:** Python 3.11
- **Framework:** FastAPI + Uvicorn (ASGI)
- **Models:** Pydantic v2
- **Database:** SQLite (file: `aam.db`)
- **HTTP Client:** httpx
- **Package Manager:** uv

## Architecture & Key Modules

```
app/
├── main.py              # ~256 lines — App factory, globals, legacy endpoints
├── config.py            # Settings from environment variables
├── constants.py         # SOR_CATEGORIES, infer_plane_type_from_category
├── logger.py            # Structured logging (aam.* namespace)
├── models.py            # Pydantic models & enums
├── inference.py         # Observation → DeclaredPipe heuristics
├── fabric_drift.py      # Connectivity drift detection
├── preset_config.py     # Enterprise maturity presets (6/8/9/11)
├── pii_redaction.py     # Regex-based PII masking
├── dcl_export.py        # DeclaredPipe export for DCL
├── services/            # Business logic (extracted from main.py)
│   ├── handoff_service.py    # AOD→AAM handoff orchestration (idempotent)
│   ├── matching_service.py   # 4-strategy candidate auto-matching
│   ├── topology_service.py   # Topology summary builder
│   ├── collector_service.py  # Collector run orchestration
│   ├── tee_service.py        # TEE workflow enforcement
│   └── export_service.py     # CSV reconciliation export
├── routers/             # FastAPI route handlers (extracted from main.py)
│   ├── handoff.py       # AOD handoff + fabric-plane endpoints
│   ├── candidates.py    # Candidate match/defer
│   ├── pipes.py         # Pipe CRUD
│   ├── collectors.py    # Collector execution
│   ├── drift.py         # Schema + fabric drift
│   ├── tee.py           # TEE request management
│   ├── adapters.py      # Fabric plane adapters
│   ├── presets.py       # Preset configuration + seed data
│   ├── topology.py      # Topology graph endpoints
│   ├── export.py        # DCL export + stats
│   ├── admin.py         # Admin/debug endpoints
│   └── ui_pages.py      # Operator UI HTML pages
├── ui/                  # UI styling constants
│   └── styles.py        # NAV_STYLE, UI_STYLE, ui_nav(), aod_run_banner()
├── db/                  # Database package (was single 2,831-line file)
│   ├── connection.py    # get_db(), get_connection(), DATABASE
│   ├── schema.py        # init_db() + migrations
│   ├── candidates.py    # Candidate CRUD
│   ├── pipes.py         # Pipe CRUD
│   ├── drift.py         # Drift event operations
│   ├── observations.py  # Observation operations
│   ├── collectors.py    # Collector operations
│   ├── tee.py           # TEE request operations
│   ├── handoff.py       # Handoff log operations
│   ├── policy.py        # Policy manifest operations
│   ├── fabric_planes.py # Fabric plane operations
│   ├── topology.py      # Topology graph queries
│   ├── reconciliation.py # AOD reconciliation deep checks
│   ├── stats.py         # Canonical KPI stats
│   └── admin.py         # Clear/reset operations
├── adapters/
│   ├── base.py          # Abstract FabricAdapter interface
│   ├── factory.py       # get_adapter_for_plane() factory
│   ├── ipaas.py         # Workato, MuleSoft, Boomi, Tray, Zapier
│   ├── gateway.py       # Kong, Apigee, AWS APIGW, Azure APIM
│   ├── eventbus.py      # Kafka, EventBridge, Pulsar
│   └── warehouse.py     # Snowflake, BigQuery, Redshift
└── collectors/
    └── mock.py          # Mock collector for testing
```

### Data Flow

1. **AOD Handoff** — `POST /api/handoff/aod/receive` accepts `AODHandoffRequest` with batch candidates + fabric planes + governance policy version.
2. **Candidate Storage** — Each candidate is deduplicated by `asset_key` (delete + insert) into `connection_candidates`.
3. **Fabric Plane Resolution** — Planes come explicitly from AOD or are auto-inferred from SOR category heuristics.
4. **Collector Runs** — Collectors produce `Observation` rows from candidates.
5. **Inference** — `infer_pipes_from_observations()` converts observations into `DeclaredPipe` objects via pattern-matching heuristics (entity scope, identity keys, change semantics, ownership signals).
6. **DCL Export** — `export_pipes_to_dcl()` serializes pipes for downstream consumption.

### Key Enums

| Enum | Values |
|------|--------|
| `FabricPlane` | IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE |
| `Modality` | CONTROL_PLANE, DECLARED_INTERFACE, PASSIVE_SUBSCRIPTION, MINIMAL_TEE |
| `TransportKind` | API, EVENT_STREAM, TABLE, FILE, WEBHOOK |
| `ChangeSemantics` | SNAPSHOT, APPEND_ONLY, CDC_UPSERT, UNKNOWN |
| `CandidateStatus` | NEW, TRIAGED, CONNECTED, DEFERRED |

### Database Tables (SQLite)

`connection_candidates`, `declared_pipes`, `pipe_versions`, `drift_events`, `observations`, `collectors`, `collector_runs`, `aod_policy_manifest`, `fabric_planes`, `aod_handoff_log`, `tee_requests`

---

## AOD → AAM Handoff: Detailed Contract

The single ingestion endpoint is `POST /api/handoff/aod/receive` (`app/main.py:2723`).

**Input model** (`AODHandoffRequest` in `app/models.py`):
- `run_id` — AOD discovery run identifier
- `snapshot_name` — human-readable label (e.g. "TechWave-0XPX")
- `candidates[]` — list of `AODHandoffCandidate` (extends `ConnectionCandidate` with `aod_run_id`, `aod_asset_id`)
- `fabric_planes[]` — detected integration fabric control planes
- `policy_version` — governance policy version applied

Each candidate carries governance fields from AOD:
- `execution_allowed` (bool), `action_type` ("inventory_only" | "provision"), `blocking_findings[]`, `connected_via_plane`

**Processing pipeline** (`app/main.py:2723-2920`):
1. Save raw payload to disk (`aod_last_payload.json`) for replay after resets
2. Store/upsert fabric planes → `fabric_planes` table
3. If no explicit planes, auto-create from SOR category heuristics (duplicated logic at lines 2756-2790 and 2870-2887)
4. Loop candidates: enum conversion → dedup by `asset_key` (DELETE + INSERT) → vendor-match to fabric plane → insert into `connection_candidates`
5. Create audit entry in `aod_handoff_log`
6. Return `AODHandoffResponse` with accepted/rejected counts

---

## Tech Debt & Monolith Inventory

### Critical: `main.py` is a 5,444-line monolith

`app/main.py` is a single file containing:
- All 30+ REST API route handlers
- All 10+ HTML UI page renderers (returning `HTMLResponse`)
- ~300 lines of embedded CSS/HTML (`NAV_STYLE`, `NAV_HTML`, `UI_STYLE`)
- Business logic for AOD handoff processing (lines 2723-2920)
- Business logic for candidate matching, topology, reconciliation
- Global mutable state (`preset_loader`, `drift_detector`, `adapter_registry` at lines 89-92)
- File I/O helpers (`_save_aod_payload`, `_load_aod_payload`)
- Multiple `import json as _json` / `import json as json_module` aliases (lines 1013, 2707, 2716)

**Impact:** Cannot test route handlers in isolation, cannot reuse business logic outside HTTP context, merge conflicts inevitable with multiple contributors.

### Critical: `db.py` is a 2,831-line data-access monolith

`app/db.py` contains:
- Schema creation (`init_db`) with dynamic `ALTER TABLE` migrations (`_add_column_if_not_exists` called 20+ times)
- 60+ CRUD functions with no grouping beyond comments
- Raw SQL with f-string interpolation for table/column names (`app/db.py:28,36`) — SQL injection risk on internal calls
- Hardcoded database path: `DATABASE = "aam.db"` (line 16)
- No connection pooling — `get_connection()` opens a new connection per call
- `create_candidate()` uses DELETE + INSERT for dedup instead of UPSERT (line 315)

### High: Duplicated fabric-plane inference logic

The category-to-plane-type mapping is duplicated in two places within the same function:
- Lines 2756-2790: auto-create fabric planes when AOD doesn't provide them
- Lines 2870-2887: derive fabric plane data for reconciliation logging

Both blocks use the same `sor_categories` set and identical `if/elif` chains. A change in one must be mirrored in the other.

### High: No service/domain layer

Route handlers in `main.py` call `db.py` functions directly. There is no intermediate service layer:
```
HTTP handler → db function → SQLite
```
Business rules (governance enforcement, dedup, plane inference) live inside route handlers, making them untestable without spinning up FastAPI.

### High: Broad exception swallowing

Multiple `except Exception` blocks that silently discard errors or log only with `print()`:
- `app/main.py:2710` — `except Exception as e: print(...)` (payload save failure)
- `app/main.py:2719` — `except Exception: return None` (payload load failure, fully silent)
- `app/main.py:2752, 2789, 2851` — catch-all in handoff loop
- All four adapter files (`ipaas.py:59`, `gateway.py:66`, `eventbus.py:60`, `warehouse.py:65`)

### High: No real logging framework

All logging is via `print()` statements. No structured logging, no log levels, no correlation IDs. Examples:
- `print(f"[AAM HANDOFF] run_id=...")` at `main.py:2739`
- `print(f"[AAM] Auto-created fabric plane...")` at `main.py:2788`
- `print("✓ AAM Database initialized")` in `db.py`

### Medium: Dead / legacy code

- `app/dcl_export_old.py` (171 lines) — superseded by `dcl_export.py`, never imported
- Abstract adapter base class has 15 `pass` stubs that are never overridden with real implementations (all adapters return mock/simulated data)

### Medium: Hardcoded configuration

| Item | Location | Should be |
|------|----------|-----------|
| DB path `"aam.db"` | `db.py:16` | Env var |
| Drift thresholds (1000ms, 10k lag, 30s timeout) | `fabric_drift.py:64-66` | Config |
| PII regex patterns and field names | `pii_redaction.py:21-45` | Config |
| AOD payload file path | `main.py:2702` | Env var |
| SOR category sets | `main.py:2756, 2891` | Shared constant |

### Medium: Embedded UI in API server

HTML/CSS/JS is generated inside Python route handlers via string concatenation and returned as `HTMLResponse`. This means:
- No template engine (Jinja2 or similar)
- No static asset pipeline
- UI changes require modifying Python source
- No client-side framework or build step

### Medium: SQLite schema migration strategy

Schema evolution is handled by `_add_column_if_not_exists()` called ~20 times in `init_db()`. There is no migration tool (Alembic, etc.), no version tracking, and no rollback capability. Column additions accumulate as imperative code.

### Medium: Missing test coverage

- `tests/test_harness.py` is an integration harness (HTTP calls to running server), not unit tests
- No unit tests for: `db.py`, `inference.py`, `fabric_drift.py`, `pii_redaction.py`, `preset_config.py`
- No test framework configured (no pytest in dependencies)
- Adapter implementations are entirely mock/simulated — no integration tests

### Low: Inconsistent JSON handling

`json` is imported under multiple aliases within `main.py`:
- `import json as _json` (line 2707)
- `import json as json_module` (line 1013)
- Standard `import json` elsewhere

### Low: Deprecated FastAPI lifecycle

`@app.on_event("startup")` at `main.py:95` is deprecated in modern FastAPI. Should use `lifespan` context manager.

### Low: `package.json` naming mismatch

`package.json` names the project `"salesforce-oauth-connector"` — a leftover from a prior project scaffold, not reflective of AAM.

---

## Remediation Plan

Six phases, ordered by dependency. Each phase is independently shippable and should pass the existing integration harness (`tests/test_harness.py`) before merging.

### Phase 0 — Foundation (prerequisites for everything else)

**Goal:** Add pytest, structured logging, and a central config module so that subsequent phases can write tests and emit real logs from day one.

**0a. Add pytest + test infrastructure**
- Add `pytest` and `pytest-asyncio` to `pyproject.toml` dependencies.
- Create `tests/conftest.py` with a fixture that creates an in-memory SQLite database (`":memory:"`) and calls `init_db()` against it, so tests never touch `aam.db`.
- Create `tests/test_smoke.py` — a single test that calls `init_db()` on the in-memory db and asserts the 11 tables exist. This validates the fixture works.

**0b. Introduce `app/config.py`**
- Single `Settings` class (Pydantic `BaseSettings`) that reads from env vars with defaults:
  - `DATABASE_URL` (default `"aam.db"`)
  - `AOD_PAYLOAD_FILE` (default `"aod_last_payload.json"`)
  - `LOG_LEVEL` (default `"INFO"`)
  - `DRIFT_LATENCY_THRESHOLD_MS` (default `1000`)
  - `DRIFT_CONSUMER_LAG_THRESHOLD` (default `10000`)
  - `DRIFT_CONNECTION_TIMEOUT_S` (default `30`)
- Instantiate a module-level `settings = Settings()`.
- Update `db.py:16` to use `settings.DATABASE_URL` instead of the hardcoded `"aam.db"`.
- Update `main.py:2702` to use `settings.AOD_PAYLOAD_FILE`.
- Update `fabric_drift.py:64-66` to use `settings.DRIFT_*` thresholds.

**0c. Introduce `app/logging.py`**
- Configure Python `logging` module with structured format: `%(asctime)s [%(name)s] %(levelname)s %(message)s`.
- Create a `get_logger(name)` factory that returns a stdlib logger.
- Replace all `print()` calls across the codebase with appropriate `logger.info()` / `logger.warning()` / `logger.error()` calls. Key locations:
  - `db.py` — `print("✓ AAM Database initialized")` → `logger.info("Database initialized")`
  - `main.py:2739` — `print(f"[AAM HANDOFF]...")` → `logger.info("AOD handoff received", extra={...})`
  - `main.py:2710,2752,2789,2851` — `print(f"[AAM] Failed...")` → `logger.error(...)`
  - All four adapter files

**0d. Delete dead code**
- Remove `app/dcl_export_old.py` (171 lines, never imported).
- Fix `package.json` name from `"salesforce-oauth-connector"` to `"aam"`.

**0e. Fix deprecated FastAPI lifecycle**
- Replace `@app.on_event("startup")` (line 95) with `lifespan` async context manager.

**Deliverables:** `app/config.py`, `app/logging.py`, updated `pyproject.toml`, `tests/conftest.py`, `tests/test_smoke.py`. Dead code removed. All `print()` → `logger.*()`. Existing integration harness still passes.

---

### Phase 1 — Extract service layer (the critical refactoring)

**Goal:** Move all business logic out of route handlers into testable service modules. After this phase the pattern is:
```
HTTP handler → service function → db function → SQLite
```

**1a. Create `app/services/handoff_service.py`** — AOD handoff orchestration

Extract from `main.py:2704-2920` (`receive_aod_handoff` and helpers):

| Function | Source lines | Purpose |
|----------|-------------|---------|
| `save_aod_payload(request)` | 2704-2711 | Persist raw payload to disk |
| `load_aod_payload()` | 2713-2720 | Load last payload |
| `infer_plane_type_from_category(category: str) -> str` | 2766-2774 + 2878-2882 | **Single source of truth** for the duplicated category→plane mapping |
| `resolve_fabric_planes(request) -> dict[str,str]` | 2741-2790 | Store explicit planes or auto-create from SOR categories |
| `link_candidate_to_plane(candidate, fabric_plane_map, fabric_planes) -> str\|None` | 2810-2840 | Vendor-match + category-fallback plane linking |
| `process_handoff(request) -> AODHandoffResponse` | 2723-2923 | Full orchestration: planes → candidates → log → response |

Key fix: `infer_plane_type_from_category()` replaces the duplicated `if/elif` chains at lines 2756-2774 and 2870-2882 with a single function. Both call sites collapse to one call.

**1b. Create `app/services/matching_service.py`** — Candidate matching

Extract from `main.py:4214-4407` (`match_candidate`):

| Function | Source lines | Purpose |
|----------|-------------|---------|
| `validate_aod_governance(candidate) -> tuple[bool, str]` | 4228-4259 | Check execution_allowed, action_type, blocking_findings |
| `validate_direct_api_access(candidate, preset_loader) -> tuple[bool, str]` | 4261-4279 | Preset policy enforcement |
| `find_matching_pipe(candidate, preset_loader) -> tuple[str, str, float]` | 4285-4398 | Four-strategy matching: exact vendor → partial vendor → category hint → create new |
| `match_candidate(candidate_id, pipe_id_hint, preset_loader) -> dict` | Full handler | Orchestration |

**1c. Create `app/services/topology_service.py`** — Topology aggregation

Extract from `main.py:5095-5261` (`get_topology_summary`):

| Function | Source lines | Purpose |
|----------|-------------|---------|
| `build_topology_summary()` | 5095-5261 | Plane aggregation, SOR categorization, graph construction |
| `categorize_candidate_to_plane(candidate) -> str` | 5115-5135 | Extract plane from candidate fields |
| `detect_sor_systems(candidates) -> list` | 5137-5173 | SOR detection and categorization |

**1d. Create `app/services/collector_service.py`** — Collector orchestration

Extract from `main.py:4102-4183` (`run_collector`):

| Function | Source lines | Purpose |
|----------|-------------|---------|
| `run_collector_pipeline(collector, adapters, policy, preset)` | 4102-4183 | Adapter discovery + governance + PII redaction + observation storage |

**1e. Create `app/services/tee_service.py`** — TEE workflow

Extract from `main.py:4528-4595` (`update_tee_status`):

| Function | Source lines | Purpose |
|----------|-------------|---------|
| `validate_tee_transition(current_status, new_status) -> tuple[bool, str]` | 4549-4563 | Status state-machine enforcement |
| `validate_tee_verification(tee_request, verification) -> tuple[bool, str]` | 4565-4578 | Verification checks |

**1f. Create `app/services/export_service.py`** — Reconciliation CSV

Extract from `main.py:3062-3232` (`download_reconciliation_summary`):

| Function | Source lines | Purpose |
|----------|-------------|---------|
| `generate_reconciliation_csv(aod_run_id) -> str` | 3062-3232 | CSV generation + RCA analysis |

**Tests for Phase 1:**
- `tests/test_handoff_service.py` — Unit tests for `process_handoff()` with mocked db calls. Specifically test:
  - `infer_plane_type_from_category()` returns correct plane for each SOR category
  - `link_candidate_to_plane()` tries vendor match before category fallback
  - Rejected candidates are tracked with reasons
  - Handoff log is created with correct counts
- `tests/test_matching_service.py` — Unit tests for governance validation and matching strategies.
- `tests/test_topology_service.py` — Unit tests for SOR detection and graph construction.

**Deliverables:** `app/services/` package with 6 modules. Route handlers in `main.py` become thin wrappers that call service functions. ~800 lines move out of `main.py`.

---

### Phase 2 — Split main.py into routers + UI module

**Goal:** Break the 5,444-line monolith into focused FastAPI router modules and a separate UI package.

**2a. Create `app/routers/` package with domain-specific routers:**

| Router file | Routes | Source lines |
|-------------|--------|-------------|
| `candidates.py` | `POST/GET /api/aam/candidates`, `PATCH .../status`, `POST .../match`, `POST .../defer` | 2612-2661, 4206-4425 |
| `pipes.py` | `GET /api/pipes`, `GET .../versions`, `GET .../drift` | 4017-4056 |
| `handoff.py` | `POST /api/handoff/aod/receive`, `POST .../reset`, `POST .../fetch`, `POST .../policy`, `GET .../logs`, `GET .../reconciliation` | 2663-3060 |
| `collectors.py` | `GET/POST /api/aam/collectors`, `POST /api/collect/*/run`, `GET /api/collect/runs` | 3944-4202 |
| `drift.py` | `GET/POST /api/drift/*`, `GET/POST /api/fabric-drift/*` | 4089-4094, 4429-4460, 4738-4790 |
| `topology.py` | `GET /api/topology/*` | 4998-5337 |
| `adapters.py` | `GET/POST /api/adapters/*` | 4601-4732 |
| `presets.py` | `GET/POST /api/preset-config/*`, `GET/POST /api/presets/*` | 4796-4979 |
| `export.py` | `GET /api/export/*`, `GET /api/dcl/*` | 4058-4087 |
| `tee.py` | `POST/GET /api/tee/*` | 4464-4595 |
| `admin.py` | `DELETE /api/data`, `GET /api/debug/*`, `GET /api/stats`, `GET /health` | 2601-2610, 4981-4992, 5340-5444 |

Each router uses `APIRouter(prefix=..., tags=[...])` and imports its service module.

**2b. Create `app/ui/` package:**

| File | Routes | Source lines |
|------|--------|-------------|
| `styles.py` | `NAV_STYLE`, `NAV_HTML` constants, `ui_nav()` helper | 100-169, 365-381 |
| `pages.py` | All `@app.get("/ui/...")` routes: pipes, candidates, drift, topology, guide, reconcile | 384-2600, 3235-3941 |

**2c. Slim down `main.py`:**

After extraction, `main.py` becomes ~50 lines:
```python
from fastapi import FastAPI
from contextlib import asynccontextmanager
from .config import settings
from .logging import get_logger
from .db import init_db
from .routers import candidates, pipes, handoff, collectors, drift, topology, adapters, presets, export, tee, admin
from .ui import pages

@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

app = FastAPI(title="AAM - Adaptive API Mesh", version="0.1.0", lifespan=lifespan)
app.include_router(candidates.router)
app.include_router(pipes.router)
# ... etc for all routers
app.include_router(pages.router)
```

**Deliverables:** `app/routers/` (11 files), `app/ui/` (2 files), `main.py` shrunk to ~50 lines. All existing endpoints respond identically. Integration harness passes.

---

### Phase 3 — Refactor db.py

**Goal:** Split the 2,831-line data access monolith into domain-specific repository modules, add connection management, and fix the migration strategy.

**3a. Create `app/db/` package (replace `app/db.py`):**

| File | Functions | Current lines |
|------|-----------|---------------|
| `connection.py` | `get_connection()`, connection context manager | 19-23 |
| `schema.py` | `init_db()`, `_column_exists()`, `_add_column_if_not_exists()` | 26-293 |
| `candidates.py` | `create_candidate()`, `get_candidate()`, `list_candidates()`, `update_candidate_status()`, `update_candidate_match()`, `update_candidate_deferred()`, `get_candidates_by_aod_run()`, `_row_to_candidate()` | 300-464, 1111-1163, 2054-2065 |
| `pipes.py` | `create_pipe()`, `get_pipe()`, `list_pipes()`, `get_pipe_versions()`, `update_pipe_with_version()`, `_candidate_to_pipe()`, `_row_to_pipe()`, `get_pipe_stats()` | 471-764, 1359-1388 |
| `drift.py` | `create_drift_event()`, `get_drift_event()`, `get_drift_events()`, `list_all_drift_events()`, `update_drift_status()`, `_row_to_drift_event()` | 771-844, 1067-1104, 1199-1209 |
| `observations.py` | `create_observation()`, `get_observations_for_candidate()`, `get_unprocessed_observations()`, `mark_observation_processed()`, `_row_to_observation()` | 851-929 |
| `collectors.py` | `list_collectors()`, `update_collector_last_run()`, `create_collector_run()`, `complete_collector_run()`, `get_collector_run()`, `list_collector_runs()` | 936-1060 |
| `tee.py` | `list_tee_requests()`, `get_tee_request()`, `create_tee_request()`, `update_tee_request_status()` | 1170-1315 |
| `handoff.py` | `create_handoff_log()`, `get_handoff_log()`, `list_handoff_logs()`, `get_latest_aod_run()` | 1868-1962, 2708-2730 |
| `policy.py` | `save_policy_manifest()`, `get_active_policy_manifest()`, `list_policy_manifests()` | 1969-2051 |
| `fabric_planes.py` | `store_fabric_plane()`, `get_fabric_planes()`, `find_fabric_plane_by_vendor()` | 2072-2167 |
| `topology.py` | `get_topology_data()`, `get_topology_for_pipe()`, `get_topology_for_fabric_plane()` | 1395-1861 |
| `reconciliation.py` | `get_aod_reconciliation()`, `get_canonical_stats()` | 2174-2831 |
| `admin.py` | `reset_aod_state()`, `clear_all_data()` | 1322-1356 |

The `app/db/__init__.py` re-exports all public functions so existing imports (`from .db import create_candidate`) continue to work unchanged. No call-site changes needed.

**3b. Add connection context manager in `app/db/connection.py`:**
```python
@contextmanager
def get_db():
    conn = sqlite3.connect(settings.DATABASE_URL)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```
Migrate functions to use `with get_db() as conn:` instead of manual `get_connection()` + `conn.close()`.

**3c. Fix candidate dedup in `app/db/candidates.py`:**
- Replace DELETE + INSERT (`db.py:315`) with SQLite `INSERT OR REPLACE` (UPSERT) using `ON CONFLICT(asset_key) DO UPDATE`.

**3d. Fix f-string SQL interpolation:**
- `_column_exists()` and `_add_column_if_not_exists()` — validate `table_name` and `column_name` against a whitelist of known tables/columns.
- `reset_aod_state()` — table names already come from a hardcoded list; add an assertion.

**Tests for Phase 3:**
- `tests/test_db_candidates.py` — CRUD cycle: create → get → list → update → dedup behavior.
- `tests/test_db_pipes.py` — Pipe creation, versioning, stats.
- `tests/test_db_handoff.py` — Handoff log creation and retrieval.

**Deliverables:** `app/db/` package (14 files + `__init__.py`). Old `app/db.py` deleted. Connection context manager. UPSERT for candidates. All tests pass.

---

### Phase 4 — Harden the AOD → AAM handoff

**Goal:** Make the most critical integration boundary robust and observable.

**4a. Typed error classification in `app/services/handoff_service.py`:**
- Define `HandoffError` enum: `INVALID_CANDIDATE`, `PLANE_CREATION_FAILED`, `DB_WRITE_FAILED`, `GOVERNANCE_REJECTED`.
- Replace bare `except Exception as e` with specific catches:
  - `ValidationError` → `INVALID_CANDIDATE`
  - `sqlite3.Error` → `DB_WRITE_FAILED`
  - Log full traceback at `ERROR` level; include `aod_asset_id` in structured log fields.

**4b. Add handoff metrics to the response:**
- Extend `AODHandoffResponse` with:
  - `planes_stored: int`
  - `planes_inferred: int`
  - `processing_time_ms: float`
- Emit timing via `logger.info("Handoff complete", extra={"run_id": ..., "duration_ms": ..., "accepted": ..., "rejected": ...})`.

**4c. Add idempotency:**
- Before processing, check if `aod_handoff_log` already has an entry for this `run_id`. If so, return the cached response with a `208 Already Reported` status. This prevents accidental replay.

**4d. Transactional candidate batch:**
- Wrap the entire candidate loop in a single database transaction (using the Phase 3 connection context manager). Currently each candidate opens/closes its own connection; if the process crashes mid-loop, the database has a partial batch with no way to detect it.

**Tests for Phase 4:**
- `tests/test_handoff_idempotency.py` — Same `run_id` submitted twice; second call returns 208.
- `tests/test_handoff_errors.py` — Malformed candidate produces `INVALID_CANDIDATE` rejection, not a 500.
- `tests/test_handoff_transaction.py` — Simulate a DB error mid-batch; verify zero candidates persisted (rollback).

**Deliverables:** Idempotent handoff endpoint. Typed error classification. Batch transactions. Structured logging with timing.

---

### Phase 5 — Improve UI layer

**Goal:** Replace inline HTML string concatenation with Jinja2 templates.

**5a. Add `jinja2` dependency to `pyproject.toml`.**

**5b. Create `app/templates/` directory:**
- `base.html` — shared layout with nav, CSS.
- `pipes.html`, `candidates.html`, `drift.html`, `topology.html`, `guide.html`, `reconcile.html` — one template per UI page.
- Move `NAV_STYLE`, `NAV_HTML` CSS/HTML into `base.html`.

**5c. Update `app/ui/pages.py`:**
- Replace string concatenation with `Jinja2Templates.TemplateResponse(...)`.
- Each route handler now calls service functions for data, then passes results to the template.

**Deliverables:** `app/templates/` (7 HTML files). UI routes use `TemplateResponse`. No more inline HTML in Python source.

---

### Phase 6 — Cleanup and hardening

**6a. Clean up JSON imports in main.py:**
- Remove `import json as _json` and `import json as json_module` aliases; use standard `import json` everywhere.

**6b. Narrow exception handlers in adapters:**
- Replace `except Exception` in `ipaas.py:59`, `gateway.py:66`, `eventbus.py:60`, `warehouse.py:65` with specific exceptions (`ConnectionError`, `TimeoutError`, `httpx.HTTPError`).
- Log the original exception at `WARNING` level.

**6c. Add shared constants in `app/constants.py`:**
- `SOR_CATEGORIES` set (`{'crm', 'erp', 'hcm', 'idp', 'itsm', 'saas', 'hr', 'finance', 'cmdb', 'identity'}`).
- `CATEGORY_TO_PLANE_TYPE` dict — single source of truth for the mapping used in handoff and topology.
- Update `handoff_service.py` and `topology_service.py` to import from here.

**6d. Move business logic out of db converters:**
- `_candidate_to_pipe()` in `db.py:686-731` contains modality inference and trust label logic. Move this to `services/matching_service.py` and have the db function be a pure data mapper.

---

### Target Architecture (after all phases)

```
app/
├── main.py               # ~50 lines: FastAPI app + router includes
├── config.py              # Pydantic BaseSettings
├── logging.py             # Structured logging factory
├── constants.py           # SOR_CATEGORIES, CATEGORY_TO_PLANE_TYPE
├── models.py              # Pydantic models (unchanged)
├── inference.py           # Observation→Pipe heuristics (unchanged)
├── fabric_drift.py        # Drift detection (reads thresholds from config)
├── preset_config.py       # Enterprise maturity presets (unchanged)
├── pii_redaction.py       # PII masking (unchanged)
├── dcl_export.py          # DCL export (unchanged)
├── services/
│   ├── handoff_service.py # AOD handoff orchestration
│   ├── matching_service.py# Candidate matching + governance
│   ├── topology_service.py# Topology aggregation
│   ├── collector_service.py# Collector pipeline
│   ├── tee_service.py     # TEE workflow validation
│   └── export_service.py  # Reconciliation CSV
├── routers/
│   ├── candidates.py
│   ├── pipes.py
│   ├── handoff.py
│   ├── collectors.py
│   ├── drift.py
│   ├── topology.py
│   ├── adapters.py
│   ├── presets.py
│   ├── export.py
│   ├── tee.py
│   └── admin.py
├── ui/
│   ├── styles.py
│   └── pages.py
├── templates/
│   ├── base.html
│   ├── pipes.html
│   ├── candidates.html
│   ├── drift.html
│   ├── topology.html
│   ├── guide.html
│   └── reconcile.html
├── db/
│   ├── __init__.py        # Re-exports for backward compat
│   ├── connection.py      # Context manager + settings
│   ├── schema.py          # init_db() + migrations
│   ├── candidates.py
│   ├── pipes.py
│   ├── drift.py
│   ├── observations.py
│   ├── collectors.py
│   ├── tee.py
│   ├── handoff.py
│   ├── policy.py
│   ├── fabric_planes.py
│   ├── topology.py
│   ├── reconciliation.py
│   └── admin.py
├── adapters/
│   ├── base.py
│   ├── factory.py
│   ├── ipaas.py
│   ├── gateway.py
│   ├── eventbus.py
│   └── warehouse.py
└── collectors/
    └── mock.py
tests/
├── conftest.py            # In-memory DB fixture
├── test_smoke.py
├── test_handoff_service.py
├── test_matching_service.py
├── test_topology_service.py
├── test_db_candidates.py
├── test_db_pipes.py
├── test_db_handoff.py
├── test_handoff_idempotency.py
├── test_handoff_errors.py
├── test_handoff_transaction.py
└── test_harness.py        # Existing integration harness (unchanged)
```

### Phase execution order and estimated scope

| Phase | Depends on | Files changed | Files created | Risk |
|-------|-----------|---------------|---------------|------|
| **0 — Foundation** | None | ~15 (print→logger) | 4 | Low |
| **1 — Service layer** | Phase 0 | `main.py` | 6 + 3 test files | Medium |
| **2 — Router split** | Phase 1 | `main.py` | 13 | Medium |
| **3 — DB split** | Phase 0 | `db.py` (delete) | 15 + 3 test files | Medium |
| **4 — Handoff hardening** | Phases 1, 3 | `handoff_service.py`, `models.py` | 3 test files | Low |
| **5 — UI templates** | Phase 2 | `ui/pages.py` | 7 templates | Low |
| **6 — Cleanup** | Phases 1, 3 | ~8 | 1 (`constants.py`) | Low |

Phases 0→1→2 and 0→3 can proceed in parallel after Phase 0 is complete. Phase 4 requires both Phase 1 and Phase 3.

---

## Development Notes

- **Run dev server:** `uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload`
- **Database:** Auto-created as `aam.db` in working directory on first startup
- **AOD replay:** Last payload persisted to `aod_last_payload.json` for reset recovery
- **Presets:** Enterprise maturity patterns in `samples/presets/` (early_scrappy, ipaas_centric, platform_oriented, warehouse_centric)
- **API docs:** Swagger/ReDoc intentionally disabled (`docs_url=None, redoc_url=None`)
