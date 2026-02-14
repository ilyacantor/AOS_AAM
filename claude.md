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
- **Database:** SQLite (file: `aam.db`, configurable via `AAM_DATABASE_URL` env var)
- **HTTP Client:** httpx
- **Package Manager:** uv
- **Testing:** pytest + pytest-asyncio
- **Logging:** stdlib `logging` via `app/logger.py` (`aam.*` namespace)

## Architecture & Key Modules

```
app/
├── main.py              # ~253 lines — App factory, lifespan, router registration
├── config.py            # Settings from environment variables (AAM_DATABASE_URL, AAM_LOG_LEVEL, drift thresholds)
├── constants.py         # SOR_CATEGORIES, PLANE_TYPE_ALIASES, INFRA_VENDOR_PLANE, display constants
├── logger.py            # Structured logging factory (aam.* namespace)
├── models.py            # Pydantic models & enums (FabricPlane, Modality, AODHandoffRequest, etc.)
├── inference.py         # Observation → DeclaredPipe heuristics
├── fabric_drift.py      # Connectivity drift detection
├── plane_resolution.py  # Fabric plane resolution helpers
├── pii_redaction.py     # Regex-based PII masking
├── dcl_export.py        # DeclaredPipe export for DCL
├── services/            # Business logic layer
│   ├── handoff_service.py    # AOD→AAM handoff orchestration (normalization, idempotency, payload caching)
│   ├── matching_service.py   # 4-strategy candidate auto-matching
│   ├── topology_service.py   # Topology summary builder
│   ├── collector_service.py  # Collector run orchestration
│   ├── tee_service.py        # TEE workflow enforcement
│   └── export_service.py     # CSV reconciliation export
├── routers/             # FastAPI route handlers
│   ├── handoff.py       # AOD handoff: /receive, /fetch, /policy, /logs, /reconciliation
│   ├── candidates.py    # Candidate match/defer
│   ├── pipes.py         # Pipe CRUD
│   ├── collectors.py    # Collector execution
│   ├── drift.py         # Schema + fabric drift
│   ├── tee.py           # TEE request management
│   ├── adapters.py      # Fabric plane adapters
│   ├── topology.py      # Topology graph endpoints
│   ├── export.py        # DCL export + stats
│   ├── admin.py         # Admin/debug endpoints
│   └── ui_pages.py      # Operator UI HTML pages (~2,728 lines)
├── ui/
│   └── styles.py        # NAV_STYLE, UI_STYLE, ui_nav(), aod_run_banner()
├── db/                  # Database package (21 modules)
│   ├── __init__.py      # Re-exports all public functions for backward compat
│   ├── connection.py    # get_db() context manager, get_connection(), DATABASE
│   ├── schema.py        # init_db() + CREATE TABLE DDL + migrations
│   ├── candidates.py    # Candidate CRUD
│   ├── candidate_match.py # Match/defer updates
│   ├── pipes.py         # Pipe CRUD + versioning
│   ├── drift.py         # Drift event operations
│   ├── drift_status.py  # Drift status updates
│   ├── observations.py  # Observation storage
│   ├── collectors.py    # Collector operations
│   ├── tee.py           # TEE request operations
│   ├── handoff.py       # Handoff log operations
│   ├── policy.py        # Policy manifest operations
│   ├── fabric_planes.py # Fabric plane storage
│   ├── sor_declarations.py  # SOR declaration storage
│   ├── sor_dispositions.py  # SOR disposition storage
│   ├── topology.py      # Topology graph queries
│   ├── reconciliation.py # AOD reconciliation deep checks (~635 lines)
│   ├── stats.py         # Canonical KPI stats
│   ├── dcl_pushes.py    # DCL push tracking
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

1. **AOD Handoff** — `POST /api/handoff/aod/receive` accepts `AODHandoffRequest` with batch candidates + fabric planes + SOR declarations + governance policy version.
2. **Normalization** — `normalize_candidates()`, `normalize_fabric_planes()`, `normalize_sors()` handle case mismatches, unknown enum values, and alternate key names before Pydantic validation.
3. **Candidate Storage** — Each candidate is deduplicated by `asset_key` (delete + insert) into `connection_candidates`.
4. **Fabric Plane Resolution** — Planes come explicitly from AOD. AAM does not infer planes from candidate categories — AOD owns plane detection.
5. **SOR Declarations** — Farm-declared Systems of Record are stored for topology and governance display.
6. **Payload Caching** — The parsed payload is saved to `aod_payload_cache` (DB table, not file) so `/fetch` can replay after resets.
7. **Collector Runs** — Collectors produce `Observation` rows from candidates.
8. **Inference** — `infer_pipes_from_observations()` converts observations into `DeclaredPipe` objects via pattern-matching heuristics.
9. **DCL Export** — `export_pipes_to_dcl()` serializes pipes for downstream consumption.

### Key Enums

| Enum | Values |
|------|--------|
| `FabricPlane` | IPAAS, API_GATEWAY, EVENT_BUS, DATA_WAREHOUSE |
| `Modality` | CONTROL_PLANE, DECLARED_INTERFACE, PASSIVE_SUBSCRIPTION, MINIMAL_TEE |
| `TransportKind` | API, EVENT_STREAM, TABLE, FILE, WEBHOOK |
| `ChangeSemantics` | SNAPSHOT, APPEND_ONLY, CDC_UPSERT, UNKNOWN |
| `CandidateStatus` | NEW, TRIAGED, CONNECTED, DEFERRED |
| `AODActionType` | PROVISION, INVENTORY_ONLY |

### Database Tables (SQLite)

15 tables: `connection_candidates`, `declared_pipes`, `pipe_versions`, `drift_events`, `observations`, `collectors`, `collector_runs`, `aod_policy_manifest`, `fabric_planes`, `aod_handoff_log`, `tee_requests`, `sor_declarations`, `sor_dispositions`, `aod_payload_cache`, `dcl_pushes`

---

## AOD → AAM Handoff: Detailed Contract

The primary ingestion endpoint is `POST /api/handoff/aod/receive` (`app/routers/handoff.py`).

**Input model** (`AODHandoffRequest` in `app/models.py`):
- `run_id` — AOD discovery run identifier
- `snapshot_name` — human-readable label (e.g. "TechWave-0XPX")
- `candidates[]` — list of `AODHandoffCandidate` (extends `ConnectionCandidate` with required `aod_run_id`, `aod_asset_id`)
- `fabric_planes[]` — detected integration fabric control planes
- `sors[]` — authoritative SOR declarations from Farm
- `policy_version` — governance policy version applied
- `handoff_timestamp` — auto-populated if omitted

Each candidate carries governance fields from AOD:
- `execution_allowed` (bool), `action_type` ("inventory_only" | "provision"), `blocking_findings[]`, `connected_via_plane`

**Processing pipeline** (`app/services/handoff_service.py` → `process_handoff()`):
1. Idempotency check — if `aod_handoff_log` already has this `run_id`, return cached response
2. Cache raw payload to `aod_payload_cache` DB table for `/fetch` replay
3. Clear stale state via `reset_aod_state()` (preserves collectors and payload cache)
4. Store SOR declarations
5. Store explicit fabric planes from AOD (AAM does NOT infer planes from categories)
6. Loop candidates: normalize enums → dedup by `asset_key` → vendor-match to fabric plane → insert into `connection_candidates`
7. Create infrastructure candidates for fabric plane vendors
8. Create audit entry in `aod_handoff_log`
9. Return `AODHandoffResponse` with accepted/rejected counts

**Normalization layer** (`app/services/handoff_service.py`):
- `normalize_fabric_planes()` — handles alternate key names (`type`/`planeType`/`plane_type`, `vendor`/`name`), uppercases plane types, resolves aliases
- `normalize_candidates()` — uppercases `connected_via_plane` and `preferred_modality`, validates against enum values (unknown values stripped to `null` with warning), normalizes `action_type` case
- `normalize_sors()` — handles alternate key names (`business_domain`/`type`, `app_name`/`application`), standardizes case

**Fetch/replay** — `POST /api/handoff/aod/fetch` loads cached payload, re-normalizes, resets state, and re-runs `process_handoff()`.

---

## Remaining Tech Debt

### High: `ui_pages.py` is 2,728 lines of inline HTML

`app/routers/ui_pages.py` generates all UI pages via Python string concatenation. No template engine, no static asset pipeline. This is the largest single file in the codebase.

**Mitigation path:** Extract to Jinja2 templates in `app/templates/`.

### Medium: Embedded UI in API server

HTML/CSS/JS is generated inside Python route handlers and returned as `HTMLResponse`. UI changes require modifying Python source.

### Medium: Adapter implementations are mock/simulated

All four adapter files (ipaas, gateway, eventbus, warehouse) return simulated data. No real integration test coverage against live fabric planes.

### Low: `package.json` exists

`package.json` names the project `"aam"` — it exists as a Replit artifact but AAM is a pure Python project.

---

## Development Notes

- **Run dev server:** `uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload`
- **Run tests:** `python -m pytest tests/ -v`
- **Database:** Auto-created as `aam.db` in working directory on first startup (override with `AAM_DATABASE_URL` env var)
- **AOD replay:** Last payload cached in `aod_payload_cache` DB table (survives `reset_aod_state()`)
- **Logging:** Structured via `app/logger.py`, level controlled by `AAM_LOG_LEVEL` env var (default `INFO`)
- **API docs:** Swagger/ReDoc intentionally disabled (`docs_url=None, redoc_url=None`)
- **Tests:** 33 passing (pytest), 3 skipped (integration harness requiring live server)
