# AAM Code Review — February 22, 2026

Full codebase audit across all layers: config, DB client, services, routers, adapters, parsers, and inference engine.

---

## RACI VIOLATIONS — Stop and Flag

These require an architectural decision before any code is written.

**1. AAM directly stores data when DCL is unreachable**
`app/services/runner_execute.py` — `_fallback_direct_store()` function
When DCL HTTP is unreachable, AAM calls `store_ingest()` directly to write data to the database. The function comment says "dev/test only" but there is no production guard. RACI is unambiguous: AAM owns pipe blueprint dispatch; it does NOT touch data movement. This function must be removed — if DCL is down, the job must fail and surface that failure.

**2. AAM performing category-based system classification**
`app/inference.py:220-228` and `app/services/matching_service.py:110-123`
AAM is classifying candidates by category (CRM, ERP, iPaaS) to infer fabric planes. The RACI table assigns classification to AOD, not AAM. AAM should receive the fabric plane assignment from AOD as a fact; it should not derive it from application category. This also conflicts with the CLAUDE.md note: "A CRM could route through any of the four planes depending on how the enterprise wired its integrations." AAM's fallback logic is both a RACI violation and semantically wrong.

---

## Critical — Silent Fallbacks & Error Swallowing

**3. DCL URL silently becomes a localhost path**
`app/config.py:27-32`
When `DCL_URL` is not set, `DCL_INGEST_URL` falls back to the local path `/api/dcl/ingest` and `DCL_EXPORT_PIPES_URL` becomes an empty string. The system will appear to function while routing everything to a dead endpoint. This is exactly the "demo works, production breaks" pattern forbidden by the constitution.

**4. Idempotency check returns stale data without payload comparison**
`app/services/handoff_service.py:277-295`
If AOD resubmits the same `run_id` with a different payload (updated candidates, corrected planes), AAM ignores the new data and returns the cached result. A re-submission with a different payload is either an AOD bug (should be rejected) or a correction (should replace). Currently it does neither — it silently returns stale data.

**5. Partial handoff silently reported as success**
`app/services/handoff_service.py:363-406`
When SOR declarations or fabric planes fail to store, the exception is caught, appended to an error list, and processing continues. The handoff response says candidates were accepted, but the planes and SOR context they depend on may not exist in the database. Candidates accepted against phantom planes cannot be dispatched correctly.

**6. DCL unreachable → silent data storage bypass**
`app/services/runner_execute.py:150-152`
Also a RACI violation per item 1. When DCL is unreachable, falls back to direct storage with no production guard.

**7. Farm dispatch — exception swallowed, `aod_run_id` lost**
`app/services/runner_dispatch.py:274-282`
When fetching the most recent handoff log fails (DB error, missing table), the exception is swallowed silently and `aod_run_id` is set to None. The manifest dispatched to Farm has no AOD lineage, breaking end-to-end reconciliation.

**8. Sequence counter defaults to 0 on DB failure**
`app/services/runner_dispatch.py:152-165`
If the DB query to find the max existing job number fails, the counter silently resets to 0. The next job gets `run_001` even if 500 jobs already exist, creating ID collisions.

**9. Request body parse failure — audit trail broken**
`app/routers/export.py:183-186` and `:253-257`
When the request body is invalid JSON, the exception is caught with no logging, body becomes `{}`, and all fields silently become None. The DCL push is then recorded with a null `aod_run_id`, permanently breaking the audit trail for that dispatch.

**10. In-memory dispatch state unreliable in multi-worker**
`app/routers/export.py:29/138/285`
`_last_dcl_dispatch` is a module-level variable updated per-request. In any multi-worker deployment (Uvicorn with `--workers > 1`), each worker has its own copy. The `/api/export/dcl/dispatch-status` endpoint returns different answers depending on which worker handles the request.

**11. Connection pool errors swallowed silently**
`app/db/supabase_client.py:93-94` and `:110-111`
Two bare `except Exception: pass` blocks in the connection pool path. Pool errors are infrastructure signals — swallowing them makes production DB issues invisible.

**12. Reconciliation JSON failures produce empty results**
`app/db/reconciliation.py:135-136` and `:300`
When the stored AOD fabric plane JSON is malformed, the parse exception is swallowed, and the comparison proceeds with an empty list. The reconciliation report concludes "all planes only in AAM" when the real answer is "the stored data was corrupt." Data quality errors must appear in the output.

**13. All four adapters are stubs returning False silently**
`app/adapters/gateway.py`, `ipaas.py`, `eventbus.py`, `warehouse.py`
Every `connect()`, `check_health()`, `apply_governance_policy()`, and `self_heal()` method logs a warning and returns False or a DISCONNECTED status. No `NotImplementedError` is raised. Code that calls these adapters and checks the boolean result cannot distinguish "not implemented" from "genuinely failed." The warehouse adapter's `_wake_warehouse()` sets a local flag to False — it doesn't call any warehouse API. It simulates healing without doing it.

---

## High Severity — Hardcoded Values & Logic Errors

**14. Unreachable else clause in config.py**
`app/config.py:53-56`
The FARM_INTAKE_URL construction has an else branch that can never execute — the condition is written inverted. Dead code in config is a maintenance hazard.

**15. Unknown transport + plane silently defaults to "rest_api"**
`app/services/runner_dispatch.py:200-203`
If neither `transport_kind` nor `fabric_plane` maps to a known adapter, the manifest is built with `adapter="rest_api"` and no warning is logged. Farm receives an adapter type that may be entirely wrong for the source system.

**16. HTTP timeouts hardcoded at 30s, ignoring config**
`app/services/runner_execute.py:112` and `runner_dispatch.py:428`
Both Farm dispatch and DCL calls use hardcoded `timeout=30.0`. The config has `RUNNER_JOB_TIMEOUT_S=300`. If a job legitimately needs 5 minutes, it will fail at the 30-second HTTP timeout.

**17. Substring matching for fabric plane coverage check**
`app/services/handoff_service.py:458-475`
The check for whether a vendor's fabric plane is already covered uses `vendor_lower in v or v in vendor_lower` — substring matching. "api" would be detected as covered by "api_gateway", and "kong" matches "kong_gateway". Real vendor names will produce false positives, causing valid planes to be silently skipped.

**18. Enum objects stored instead of string values**
`app/services/handoff_service.py:298-311` and `:496`
`_serialize_candidate()` only converts enums when they are truthy, skipping None values. The infrastructure candidate at line 496 sets `"status": CandidateStatus.NEW` (the enum object, not `"new"`). The DB receives enum objects in some paths, strings in others.

**19. 0.0 confidence dispatch not blocked**
`app/services/matching_service.py:120-123`
The fallback plane assignment returns confidence 0.0 with the reason `"needs_operator_review"`, but nothing in the dispatch path checks for this. A pipe can be auto-dispatched with zero confidence and no operator review ever happening.

**20. Inference fills in invented fields from hardcoded lists**
`app/inference.py:87-108`
When an observation has no schema sample, inference silently substitutes the hardcoded `CATEGORY_STANDARD_FIELDS` list as if those were real discovered fields. DCL receives invented fields presented as observed facts. Trust labels on the resulting pipe say "inferred:schema_from_sample" but there was no sample.

**21. Identity key fallback defaults to `["id"]` silently**
`app/inference.py:296-367`
When no identity key can be inferred, returns `["id"]`. Real identity could be a composite key (`account_id + customer_id`). DCL will use wrong join keys for entity resolution and no one will know why records don't match.

---

## Medium Severity — Permissive Schemas, Dead Code, Config Issues

**22. Pooler host hardcoded to us-west-2**
`app/db/supabase_client.py:37`
Default pooler host is `aws-0-us-west-2.pooler.supabase.com`. Missing env var should fail, not silently assume a region. The log message also hardcodes "us-west-2" regardless of actual host.

**23. PII redaction policy hardcoded to "optional"**
`app/services/collector_service.py:81`
Redaction policy is not read from config or the policy manifest — it is hardcoded. In optional mode, redaction only runs if the observation itself claims to contain PII, which is metadata from an untrusted source.

**24. Status fields accept arbitrary strings**
`app/db/drift_status.py`, `app/db/tee.py`, `app/db/sor_dispositions.py`
All three update functions accept any string as `status`. A typo like `"aproved"` stores silently. These should validate against the allowed enum values.

**25. Dead code exports**
`app/db/dcl_pushes.py:13-15` — `init_dcl_pushes_table()` is a no-op still exported from `__init__.py`.
`app/db/candidates.py:20-24` — `if isinstance(execution_allowed, bool): pass` does nothing; the condition with no body also appears twice.

**26. `cancel_queued_jobs()` returns 0 on failure**
`app/db/runner_jobs.py:156-162`
Returns `0` on exception. Callers cannot distinguish "nothing to cancel" from "cancellation failed." Also uses an inline `import logging` instead of the codebase's `get_logger()` pattern — one module with two loggers.

**27. JSON loads without try/except in reads**
`app/db/tee.py:30,57,113`
Reads `row["configuration"]` through `json.loads()` with no error handling. A corrupt row crashes the function rather than returning a recoverable error state.

**28. topology.py silent "UNMAPPED" fallback**
`app/services/topology_service.py:84-89`
Candidates without a resolvable fabric plane are silently labeled "UNMAPPED" with no log. They disappear from the visible topology without any operator signal.

**29. export.py response shape has three incompatible structures**
`app/routers/export.py`
The `export_pipes` field in the response can be `{status, ok, body}`, `{error}`, or `{skipped, reason}` depending on the code path. No consistent schema — clients must handle all three.

**30. DBT parser drops missing sources silently**
`app/parsers/dbt_manifest.py:80-89`
If a dbt model depends on a source that isn't in the manifest, it is silently skipped. DCL receives partial lineage with no indication that edges are missing.

---

## Addendum 1 — Additional Items

**31. `ui_pages.py` silently shows empty state on DB failures**
Multiple exception handlers in the UI page router catch any DB exception and substitute empty lists/zeros (`all_jobs = []`, `dcl_exported = 0`). Operators will see a blank dashboard and assume nothing is running, when the actual cause is a data access failure. Silent UI degradation.

**32. `models.py` — Several core fields are completely unvalidated dicts**
`endpoint_ref`, `metadata`, `governance_rules`, `transform`, `schema_map`, and `configuration` are all typed as bare `dict` or `list[dict]` with no inner schema. Any caller can pass arbitrary keys. DCL and downstream consumers receive structurally unconstrained data from what should be a well-defined contract layer.

**33. `constants.py` — Categories defined as sets/dicts, not Enums**
`SOR_CATEGORIES`, `PLANE_STANDARD_FIELDS`, etc. are Python sets and dicts. Any string passes silently as a valid category. Should be Enums or at minimum validated against these sets at the function boundary where category first enters the system.

---

## Addendum 2 — DB/Services Layer

**34. `tee_service.py` — state updated before pipe validation**
The TEE status is written to the database *before* the associated pipe's existence is verified. If the pipe was deleted between the initial validation and the update, the exception fires after the state change has already committed, leaving an approved TEE pointing at a non-existent pipe.

**35. `sor_declarations.py` — `clear_sor_declarations(None)` deletes everything**
When called with no `aod_run_id`, runs `DELETE ... WHERE sor_id IS NOT NULL` — effectively the entire table. No guard, no confirmation, no audit log.

**36. `stats.py` — three fields returning the same value under different names**
`total_candidates`, `total_pipes`, and `pipes` all carry the same count. If they ever diverge due to a future change, there is no canonical source.

**37. `runner_jobs.py` — batch insert has no idempotency check**
`create_runner_jobs_batch()` inserts all manifests unconditionally. A retry on a failed dispatch creates duplicate job records for the same `run_id`.

**38. `fabric_planes.py` — `is_healthy` stored as NULL when not provided**
When health status is not present in the incoming plane data, NULL is inserted. Queries filtering for `is_healthy = true` silently exclude planes with unknown health, making the topology view inconsistent.

**39. `handoff_service.py` — invalid plane hints silently stripped to None**
When a candidate arrives with an unrecognized `connected_via_plane` value, the code strips it to None and logs a warning. The candidate is accepted rather than rejected; downstream fabric plane assignment then has no hint.

**40. `collector_service.py` — disconnected adapters skipped with no audit entry**
When an adapter's health check returns anything other than CONNECTED, it is silently skipped. No log entry records which adapter was unreachable or for how long.

**41. `observations.py` — malformed schema_sample JSON silently dropped**
Rows with invalid JSON in `schema_sample` are skipped with no log output. The observation count looks normal but the schema data is missing without any signal that data was lost.

**42. `drift.py` — `json.loads` on `details` field has no error handling**
If a drift event has corrupt JSON in the `details` column, the exception propagates with no context about which `drift_id` or `pipe_id` caused it.

---

## Addendum 3 — DB Layer Specifics

**43. `supabase_client.py:table_exists()` returns False for query failures**
The function catches all exceptions and returns `False`. A missing table and a broken database connection both return `False`. Initialization code calling `table_exists()` before deciding to create a table will skip creation silently when the DB is unreachable — then crash later when it tries to write.

**44. `candidates.py:create_candidate()` always reports success**
Returns `{"status": "connected", ...}` unconditionally. If `sb.insert()` fails silently, the caller believes the candidate was stored. No verification step between the insert call and the success response.

**45. `create_candidate()` silently deletes the existing candidate on duplicate `asset_key`**
Line 26-27 runs `sb.delete(..., filters={"asset_key": asset_key})` before every insert. This upsert behavior is not documented in the function signature or docstring. The batch version skips this per-row delete and assumes prior cleanup — undocumented coupling.

**46. `create_candidates_batch()` returns pre-built results, not DB-confirmed rows**
After calling `sb.insert_many()`, returns the `results` list constructed from input data, ignoring `insert_many()`'s return value. If the insert fails partially, the caller receives a success report for every row regardless.

**47. `pipes.py:24` hardcodes `"API_GATEWAY"` as the default fabric plane**
When a pipe is created without an explicit `fabric_plane`, it silently defaults to `API_GATEWAY`. A data warehouse or event bus pipe submitted without this field will be miscategorized without any warning.

**48. JSON `"null"` string in DB columns defeats the empty-list fallback**
In `candidates.py:180-184`, the pattern `json.loads(row["findings"]) if row["findings"] else []` only catches falsy/empty values. If the column was stored as `json.dumps(None)`, the stored value is the string `"null"`, which is truthy. `json.loads("null")` returns `None`, not `[]`. The function then returns `"findings": None`, silently breaking type contracts for every downstream consumer.

---

## Issue Count Summary

| Category | Count |
|---|---|
| RACI violations (stop-and-flag) | 2 |
| Critical silent fallbacks / error swallowing | 11 |
| High severity hardcoded / logic errors | 8 |
| Medium severity permissive schemas / dead code | 9 |
| Addendum items (DB layer, services, models) | 18 |
| **Total** | **48** |

---

## Recommended Fix Sequence

1. **RACI decisions first (items 1 and 2)** — architectural call required before code is touched
2. **`config.py` DCL silent fallback (item 3)** — highest blast radius, affects every deployed pipe dispatch
3. **All four adapter stubs (item 13)** — `connect()`, `check_health()`, `self_heal()` all return False silently; should raise `NotImplementedError`
4. **`handoff_service.py` idempotency + partial handoff (items 4, 5)** — data integrity issues that compound over every AOD run
5. **Sweep exception handlers** — replace every `except Exception: pass` with at minimum a log line
6. **Hardcoded timeouts, enum serialization, status string validation** — mechanical cleanup, no decisions required
