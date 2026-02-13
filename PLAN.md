# Root Cause Analysis & Fix Plan — COMPLETED

## Summary of Changes

### Phase 1: Bug Fixes (stop the bleeding)

| # | Fix | Files Changed |
|---|-----|---------------|
| 1a | **Missing imports** — `_row_to_drift_event` was undefined in `drift_status.py` and `tee.py` (runtime crash) | `db/drift_status.py`, `db/tee.py` |
| 1b | **`fabric_plane_id` propagation** — matching now resolves the composite fabric_plane_id (e.g. `"API_GATEWAY:aws api gateway"`) from the `fabric_planes` table and writes it to the candidate, so the topology resolves on step 1 without fallback | `db/candidate_match.py`, `services/matching_service.py` |
| 1c | **`create_candidate()` return value** — was hardcoded `"connected"`, now returns actual stored status (`"new"`) | `db/candidates.py` |
| 1d | **Sentinel unification** — eliminated `"UNKNOWN"`, `"UNMAPPED"`, and `"API_GATEWAY"` as DB-level sentinel strings. `None` in the DB, `"UNMAPPED"` only at the UI boundary. | `db/pipes.py`, `db/admin.py`, `inference.py` |
| 1e | **`is_healthy` None→False** — `bool(None)` was converting undeclared health to "unhealthy". Now preserves `None` through the stack, DCL export reports `"unknown"` | `db/fabric_planes.py`, `dcl_export.py` |
| 1.5 | **Fallback diagnostics** — `_resolve_plane_id()` now logs `WARNING` whenever it falls past step 1 (direct `fabric_plane_id`), making fallback frequency visible | `services/topology_service.py` |

### Phase 2: Structural Cleanup (prevent recurrence)

| # | Fix | Files Changed |
|---|-----|---------------|
| 2a | **Renamed `list_pipes()` → `list_candidates_as_pipes()`** — name now tells the truth about what it reads | `db/pipes.py`, `db/__init__.py`, `main.py`, `services/topology_service.py`, `routers/pipes.py`, `routers/ui_pages.py`, `routers/topology.py`, `tests/test_smoke.py` |
| 2b | **Split `get_pipe()` into two functions** — `get_pipe()` reads `declared_pipes` only; `get_pipe_or_candidate()` has the dual-lookup for UI compat | `db/pipes.py`, `db/__init__.py`, `routers/pipes.py`, `routers/tee.py`, `routers/ui_pages.py`, `services/tee_service.py`, `main.py` |
| 2c | **DCL export no longer drops unlinked candidates** — they go into a synthetic `"UNMAPPED"` group with a `WARNING` log instead of being silently skipped | `dcl_export.py` |
| 2d | **Removed `except Exception: pass`** in DCL push — malformed JSON now returns HTTP 400, empty body still works | `routers/export.py` |
| 2e | **Topology deduplication** — replaced `list_candidates_as_pipes()` call with `list_declared_pipes()` for the pipe_planes lookup. One fewer query against `connection_candidates`. | `services/topology_service.py` |

### Tests

- All 11 tests pass (3 integration tests skipped as expected)
- Fixed pre-existing `test_init_db_creates_all_tables` failure (missing `aod_payload_cache` table)
- Updated test assertions for Phase 1c (`status: "new"`) and Phase 1d (`fabric_plane: None`)
