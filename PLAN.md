# AAM Pipe Inference Validation Plan

## Part A: Tech Debt & Code Quality Review

### Critical Issues (High Severity)

**1. `db/reconciliation.py` — 651-line God Function**
- `get_aod_reconciliation()` is a single 607-line function doing 7 unrelated jobs:
  handoff log lookup, candidate counting, vendor case-duplicate detection,
  fabric plane comparison, SOR line-item ingestion, schema completeness,
  and duplicate detection.
- Should be decomposed into 5-7 focused functions.

**2. `db/pipes.py` — Dual Source of Truth**
- `get_pipe()` and `list_pipes()` have comments saying "CANONICAL: Pipes = Candidates"
  but query `connection_candidates` first, then fall back to `declared_pipes`.
- `_candidate_to_pipe()` (line 231) contains **business logic in the DB layer**: maps
  category strings to modality with hardcoded if/elif chains. This duplicates
  `inference.py:infer_modality()`.
- The `_candidate_to_pipe` modality inference is also **always wrong**: every non-iPaaS
  category returns `DECLARED_INTERFACE`, making the branches dead code
  (lines 245-250 all return the same value).

**3. `inference.py` — Dead Update Path**
- `infer_pipes_from_observations()` (line 42) sets `_action = "update"` on existing pipes.
- `process_pending_observations()` (line 563-567) catches the "update" action but
  always calls `create_pipe()` anyway. The `updated` counter is never incremented.
  The inference engine literally cannot update a pipe.
- `routers/collectors.py:infer_pipes()` (line 55) also only handles `action == "create"`,
  silently dropping updates.

**4. `services/handoff_service.py` — `reset_aod_state()` on Every Handoff**
- Line 260: `reset_aod_state()` is called on every new handoff, which DELETEs from
  13 tables. This means a second AOD run wipes the first run's data entirely.
  Combined with the idempotency check (line 247), a re-run of the *same* run_id
  returns cached results, but a *new* run_id nukes everything.
- No multi-run history is preserved despite the `aod_handoff_log` table existing
  for exactly that purpose.

**5. Missing DB Transactions**
- `db/pipes.py:create_pipe()` inserts into `declared_pipes` then `pipe_versions`
  with no transaction wrapper — if the second INSERT fails, an orphaned pipe exists.
- `db/candidates.py:create_candidate()` does DELETE-then-INSERT (dedup) without
  a transaction — concurrent access could lose data.
- `db/admin.py:reset_aod_state()` deletes from 13 tables with no transaction.

**6. `db/schema.py` — Status Default Contradiction**
- `connection_candidates.status` defaults to `'connected'` (line 32), but
  `db/candidates.py:create_candidate()` defaults to `'new'` (line 56 of candidates.py).
- The schema default is unreachable (create_candidate always passes a status),
  but it's misleading and will bite if any other code path inserts directly.

### Medium Issues

**7. `routers/handoff.py` — Business Logic in Router**
- `_normalize_fabric_planes()` (35 lines of normalization logic, line 57-91)
  and `_normalize_sors()` (28 lines, line 94-121) belong in the service layer.
- `PLANE_TYPE_ALIASES` dict (line 66) duplicates knowledge from `constants.py`.

**8. `inference.py` — Type Inconsistency Throughout**
- Functions return string literals ("CONTROL_PLANE", "DECLARED_INTERFACE") instead
  of Modality/TransportKind enum values defined in `models.py`.
- `infer_fabric_plane()` returns "UNKNOWN" but the FabricPlane enum has no UNKNOWN member.

**9. `services/topology_service.py` — String-Parsing IDs**
- Line 46-47: `fabric_plane_id.split(":")[0]` to extract plane type from composite
  ID like "IPAAS:workato". Fragile if ID format changes.

**10. Hardcoded Magic Numbers**
- `matching_service.py:89` — `list_pipes(limit=200)` caps pipe search at 200.
- `topology_service.py:142` — Top 20 systems arbitrary cutoff.
- `export_service.py:122` — Sample of 25 incomplete candidates.
- `inference.py:475` — 10,000 requests/day = "high traffic" threshold.

**11. `dcl_export.py` — Vendor/Category Confusion**
- `_infer_fields_from_category()` (line 52) checks `"salesforce" in category_lower`,
  mixing vendor name checks into a function that claims to work on categories.

---

## Part B: AAM Pipe Inference Validation Checklist

### Execution Strategy

Use the real 654-candidate payload from AOD run `run_68d878107640` (snapshot
`InfoLogic-B3QJ`). Re-ingest from `aod_last_payload.json`, then walk every
phase below as a live DB query + API call sequence.

No code changes — read-only verification against the running server.

### Phase 1: Pre-Inference Ground Truth

| # | Check | Method | Pass Criteria |
|---|-------|--------|---------------|
| 1.1 | **Candidate Density** | `SELECT count(*) FROM connection_candidates` | = 654 (matches payload) |
| 1.2 | **Candidate Status Distribution** | `SELECT status, count(*) FROM connection_candidates GROUP BY status` | All should be `connected` (current default) — note: this is the schema default mismatch from tech debt #6 |
| 1.3 | **Vendor Metadata Richness** | `SELECT count(*) FROM connection_candidates WHERE known_endpoints IS NOT NULL AND known_endpoints != '[]'` | >0 means inference has URL data to work with |
| 1.4 | **SOR Alignment (Farm Ingestion)** | `SELECT count(*) FROM sor_declarations` | Should match the SOR count from AOD payload's `sors` array. If 0, Farm data was not sent. |
| 1.5 | **Fabric Planes Present** | `SELECT plane_type, vendor FROM fabric_planes ORDER BY plane_type` | Must show 4 planes: IPAAS/Workato, API_GATEWAY/AWS API Gateway, EVENT_BUS/Azure Event Hubs, DATA_WAREHOUSE/Snowflake |

### Phase 2: Inference Execution

| # | Check | Method | Pass Criteria |
|---|-------|--------|---------------|
| 2.1 | **Observation Availability** | `SELECT count(*) FROM observations WHERE processed = 0` | If 0, there are no observations to infer from (AOD handoff populates candidates, not observations — this is expected) |
| 2.2 | **POST /api/aam/infer** | `curl -X POST /api/aam/infer` | Returns 200 with `pipes_created` count. If observations=0, returns `"No pending observations"` — which means **inference is irrelevant for AOD-sourced data** |
| 2.3 | **Pipes via list_pipes()** | `GET /api/aam/pipes` | Since Pipes=Candidates, should return all 654 candidates as pipes. Verify `pipe_id` = `candidate_id`. |
| 2.4 | **Candidate→Pipe ID Mapping** | Compare `candidate_id` from candidates table to `pipe_id` from pipes endpoint | Must be 1:1 mapping (candidates ARE pipes per current architecture) |

### Phase 3: Classification Accuracy

| # | Check | Method | Pass Criteria |
|---|-------|--------|---------------|
| 3.1 | **Vendor Attribution (HubSpot)** | `SELECT * FROM connection_candidates WHERE LOWER(vendor_name) LIKE '%hubspot%'` then `GET /api/aam/pipes/{candidate_id}` | Pipe's `source_system` = "hubspot" (or "hubspot inc"), `fabric_plane` populated |
| 3.2 | **Fabric Plane Linkage** | `SELECT count(*) FROM connection_candidates WHERE fabric_plane_id IS NOT NULL` vs `WHERE fabric_plane_id IS NULL` | Linked count should include at least the 4 infra vendors + any SOR-category matches |
| 3.3 | **Directionality/Modality** | `GET /api/aam/pipes` → check modality field | Per current `_candidate_to_pipe()`, all non-iPaaS pipes get `DECLARED_INTERFACE`. This is a known limitation (tech debt #2). |
| 3.4 | **Deduplication** | `SELECT vendor_name, count(*) as cnt FROM connection_candidates GROUP BY LOWER(vendor_name) HAVING cnt > 1 ORDER BY cnt DESC LIMIT 10` | Verify that multi-candidate vendors (e.g., Salesforce with salesforce.com, slack.com, tableau.com) are separate candidates, not collapsed. Current design: NO dedup across asset_keys for same vendor. |

### Phase 4: Reconciliation Report

| # | Check | Method | Pass Criteria |
|---|-------|--------|---------------|
| 4.1 | **Reconciliation Endpoint** | `GET /api/handoff/aod/{run_id}/reconcile` | Returns full reconciliation report with fabric_planes, sor_line_items, schema_completeness sections |
| 4.2 | **SOR Match Verification (HubSpot)** | Check `sor_line_items` for hubspot | Status should be `ok` or have a candidate match — NOT "missing" |
| 4.3 | **Genuine Gap Test** | Check for a vendor in Farm that has no integration (e.g., if Xero/OneLogin were declared as SORs but not in candidates) | Should show `missing` verdict — proves report isn't painting everything green |
| 4.4 | **Fabric Plane Reconciliation** | Check `fabric_comparison.line_items` | All 4 planes should show `match` status |
| 4.5 | **Download Verification** | `GET /api/handoff/aod/{run_id}/reconcile/download` | Returns valid CSV with all sections populated |

### Troubleshooting Checks (if "No Pipes" persists)

| # | Check | Method |
|---|-------|--------|
| T.1 | **Normalization Fail** | Compare `vendor_name` in candidates vs `vendor` in `sor_declarations` — are they string-matching? |
| T.2 | **Confidence Threshold** | Check if any filtering by confidence score exists (current code: NO confidence threshold, all candidates accepted) |
| T.3 | **AOD Latency** | Check `aod_handoff_log.handoff_timestamp` vs `aod_handoff_log.processed_at` — is processing completing? |

---

## Execution Order

1. Kill existing server, reinit DB
2. Start server on port 8000
3. Replay the 654-candidate payload via `POST /api/handoff/aod/fetch`
4. Run Phase 1 checks (5 SQL queries)
5. Run Phase 2 checks (API calls)
6. Run Phase 3 checks (targeted queries + API)
7. Run Phase 4 checks (reconciliation endpoint + CSV download)
8. Run Troubleshooting checks if any failures
9. Produce a pass/fail summary table
