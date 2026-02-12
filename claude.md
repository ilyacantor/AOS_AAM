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
├── main.py            # 5,444 lines — FastAPI app, all routes, embedded UI
├── db.py              # 2,831 lines — SQLite schema + 60+ CRUD functions
├── models.py          #   459 lines — Pydantic models & enums
├── inference.py        #   577 lines — Observation → DeclaredPipe heuristics
├── fabric_drift.py     #   306 lines — Connectivity drift detection
├── preset_config.py    #   229 lines — Enterprise maturity presets (6/8/9/11)
├── pii_redaction.py    #   229 lines — Regex-based PII masking
├── dcl_export.py       #   194 lines — DeclaredPipe export for DCL
├── dcl_export_old.py   #   171 lines — Dead code (legacy export)
├── adapters/
│   ├── base.py         # Abstract FabricAdapter interface
│   ├── factory.py      # get_adapter_for_plane() factory
│   ├── ipaas.py        # Workato, MuleSoft, Boomi, Tray, Zapier
│   ├── gateway.py      # Kong, Apigee, AWS APIGW, Azure APIM
│   ├── eventbus.py     # Kafka, EventBridge, Pulsar
│   └── warehouse.py    # Snowflake, BigQuery, Redshift
└── collectors/
    └── mock.py         # Mock collector for testing
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

## Development Notes

- **Run dev server:** `uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload`
- **Database:** Auto-created as `aam.db` in working directory on first startup
- **AOD replay:** Last payload persisted to `aod_last_payload.json` for reset recovery
- **Presets:** Enterprise maturity patterns in `samples/presets/` (early_scrappy, ipaas_centric, platform_oriented, warehouse_centric)
- **API docs:** Swagger/ReDoc intentionally disabled (`docs_url=None, redoc_url=None`)
