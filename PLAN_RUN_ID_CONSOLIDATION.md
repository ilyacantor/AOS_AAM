# Plan: Consolidate Run ID Usage (Per-Run, Not Per-Pipe)

**Goal**: Use existing per-run unique ID from AOD handoff when dispatching to Farm, eliminating AAM-generated run_ids

**Current Run Example**:
- **run_id**: `run_b83b051922fa` (already exists, from AOD)
- **snapshot_name**: `CoreWorks-JEZ0` (tenant identifier, separate from run_id)
- **Aliases**: May appear as `aod_run_id` or `aam_run_id` (same value)

**Principle**: DO NOT CREATE NEW IDs - reuse existing per-run identifier across the entire dispatch cycle

---

## Current State Analysis

### Where run_id Currently Exists

| Location | Current Behavior | Example Value |
|----------|------------------|---------------|
| **AOD Handoff** | `AODHandoffRequest.run_id` sent by AOD | `run_b83b051922fa` |
| **Database** | Stored as `aod_run_id` in multiple tables | `run_b83b051922fa` |
| **Manifest Building** | **GENERATES NEW** via `_next_run_id()` | `run_20260223_salesforce_001` ❌ |
| **Job Tracking** | Uses generated run_id as `job_id` | `run_20260223_salesforce_001` ❌ |

### Current Run ID Generation (TO BE REMOVED)

**File**: `app/services/runner_dispatch.py:171-179`

```python
def _next_run_id(source_system: str) -> str:
    """Generate a unique run_id: run_{YYYYMMDD}_{system}_{seq:03d}"""
    global _seq_counter
    if _seq_counter is None:
        _seq_counter = _init_seq_counter()
    _seq_counter += 1
    date_str = datetime.utcnow().strftime("%Y%m%d")
    safe_system = source_system.lower().replace(" ", "_")[:20]
    return f"run_{date_str}_{safe_system}_{_seq_counter:03d}"  # ❌ Creates new IDs
```

**Problem**: This generates per-pipe run_ids, not per-batch. Farm receives multiple manifests with different run_ids and can't group them.

---

## Target State

### Run ID Flow (After Implementation)

```
AOD Handoff                    AAM Database                Farm Manifest
─────────────                  ────────────                ─────────────
run_id: run_b83b051922fa  →   aod_run_id: run_b83b051922fa  →  run_id: run_b83b051922fa
                          ↓                                  ↓
                     (stored once)                    (reused for all pipes)
```

### Key Principle: One Run ID Per Dispatch Cycle

**Single dispatch cycle** (triggered by "Run" button):
- ✅ **Same run_id** for ALL manifests: `run_b83b051922fa`
- ✅ **Different job_ids** per pipe: Use `pipe_id` as unique key in AAM database
- ✅ **Same snapshot_name** for all manifests: `CoreWorks-JEZ0`

**Result**: Farm receives multiple manifests with the same `run_id` and can group them into a single batch execution.

---

## Implementation Plan

### Phase 1: Stop Generating New Run IDs ✅

**What**: Remove ID generation, always use existing `aod_run_id`

**Files to Change**:

#### 1.1 `app/services/runner_dispatch.py` - Remove ID Generation

**Lines 149-179**: Delete `_seq_counter`, `_init_seq_counter()`, `_next_run_id()`

**Line 220-221**: Change from:
```python
if run_id is None:
    run_id = _next_run_id(source_system)
```

To:
```python
if run_id is None:
    raise ValueError(
        f"run_id is required for manifest building (pipe={pipe_id}). "
        "Pass aod_run_id from AOD handoff or use a stable per-dispatch identifier."
    )
```

**Rationale**: Force callers to explicitly provide run_id, preventing accidental ID generation.

---

#### 1.2 `app/services/runner_dispatch.py:dispatch_pipe()` - Pass aod_run_id

**Lines 271-318**: Update to always fetch and pass `aod_run_id`

**Current** (lines 288-307):
```python
if not snapshot_name:
    try:
        from ..db.handoff import list_handoff_logs
        handoffs = list_handoff_logs(limit=1)
        if handoffs:
            snapshot_name = snapshot_name or handoffs[0].get("snapshot_name")
            aod_run_id = handoffs[0].get("aod_run_id")
    except Exception as exc:
        _log.error(...)
else:
    aod_run_id = None

manifest = build_manifest(
    pipe,
    trigger,
    snapshot_name=snapshot_name,
    aod_run_id=aod_run_id,
    farm_verification=farm_verification,
)
```

**Change to**:
```python
# Always fetch latest aod_run_id from handoff log
try:
    from ..db.handoff import list_handoff_logs
    handoffs = list_handoff_logs(limit=1)
    if not handoffs:
        raise ValueError("No AOD handoff found. Run AOD handoff first before dispatching pipes.")

    aod_run_id = handoffs[0].get("aod_run_id")
    snapshot_name = snapshot_name or handoffs[0].get("snapshot_name")

    if not aod_run_id:
        raise ValueError("Latest handoff has no aod_run_id. Cannot dispatch without a run identifier.")

except Exception as exc:
    _log.error("Failed to fetch aod_run_id for dispatch: %s", exc)
    raise

manifest = build_manifest(
    pipe,
    trigger,
    snapshot_name=snapshot_name,
    aod_run_id=aod_run_id,
    farm_verification=farm_verification,
    run_id=aod_run_id,  # ✅ Use aod_run_id as manifest run_id
)
```

**Rationale**: Ensures every manifest uses the same `aod_run_id` from the current handoff.

---

#### 1.3 `app/services/runner_dispatch.py:dispatch_batch()` - Already Correct!

**Line 369**: Already passes `run_id=current_aod_run_id` (from failed cff244d commit)

```python
manifest = build_manifest(pipe, trigger, snapshot_name=current_snapshot, aod_run_id=current_aod_run_id, run_id=current_aod_run_id)
```

**No changes needed** - this is already correct! ✅

---

### Phase 2: Fix Job ID vs Run ID Mismatch ⚠️

**Problem from cff244d**: Database uses `pipe_id` as `job_id`, but status updates use `run_id` for lookups.

**Decision Point**: Two options:

#### Option A: Use pipe_id as job_id (Database PRIMARY KEY) ✅ **RECOMMENDED**

**Database Schema**:
- `job_id` = `pipe_id` (e.g., `pipe_salesforce_001`) - unique per pipe
- `run_id` = `aod_run_id` (e.g., `run_b83b051922fa`) - shared across batch

**Changes Required**:

**2.1 `app/db/runner_jobs.py:create_runner_job()`** - Use pipe_id as job_id

**Line 15-27**: Change from:
```python
def create_runner_job(manifest_dict: dict) -> str:
    """Create a new runner job from a manifest dict. Returns job_id (= run_id)."""
    job_id = manifest_dict["run_id"]  # ❌ Uses run_id
```

To:
```python
def create_runner_job(manifest_dict: dict) -> str:
    """Create a new runner job from a manifest dict. Returns job_id (= pipe_id)."""
    job_id = manifest_dict["source"]["pipe_id"]  # ✅ Use pipe_id
    run_id = manifest_dict["run_id"]  # Extract for storage
```

**Add run_id field to insert**:
```python
sb.insert("runner_jobs", {
    "job_id": job_id,
    "pipe_id": manifest_dict["source"]["pipe_id"],
    "run_id": run_id,  # ✅ NEW: Store run_id separately
    "status": "queued",
    "manifest": json.dumps(manifest_dict, default=str),
    "dispatched_at": now,
    "rows_transferred": 0,
})
```

**Schema Migration Required**:
```sql
ALTER TABLE runner_jobs ADD COLUMN run_id VARCHAR;
CREATE INDEX idx_runner_jobs_run_id ON runner_jobs(run_id);
```

---

**2.2 `app/db/runner_jobs.py:create_runner_jobs_batch()`** - Already correct!

**Lines 30-62**: Already uses `pipe_id` as `job_id` (from cff244d)

```python
job_ids = [m["source"]["pipe_id"] for m in manifests]  # ✅ Correct
```

**Add run_id to batch insert**:
```python
rows.append({
    "job_id": m["source"]["pipe_id"],
    "pipe_id": m["source"]["pipe_id"],
    "run_id": m["run_id"],  # ✅ NEW: Add run_id field
    "status": "queued",
    "manifest": json.dumps(m, default=str),
    "dispatched_at": now,
    "rows_transferred": 0,
})
```

---

**2.3 `app/services/runner_dispatch.py:dispatch_to_farm()` - Fix Status Updates**

**Lines 456, 471**: Change from:
```python
update_runner_status(manifest.run_id, "dispatched")  # ❌ Looks up by run_id
update_runner_status(manifest.run_id, "failed", error_message=error_msg)
```

To:
```python
update_runner_status(manifest.source.pipe_id, "dispatched")  # ✅ Look up by pipe_id (job_id)
update_runner_status(manifest.source.pipe_id, "failed", error_message=error_msg)
```

**Rationale**: `job_id` in database is `pipe_id`, so status updates must use `pipe_id` as lookup key.

---

**2.4 `app/routers/dcl_ingest.py` - Use pipe_id for Status Updates**

**Lines 92, 103**: Change from:
```python
update_runner_status(x_run_id, "pushing")
update_runner_status(x_run_id, "completed", rows_transferred=...)
```

To:
```python
pipe_id = request.headers.get("x-pipe-id")
if pipe_id:
    update_runner_status(pipe_id, "pushing")
    update_runner_status(pipe_id, "completed", rows_transferred=...)
```

**Rationale**: DCL already receives `x-pipe-id` header from Farm, use it for job lookups.

---

**2.5 Add Validation to `update_runner_status()`**

**File**: `app/db/runner_jobs.py:65-91`

**Add logging for failed updates**:
```python
def update_runner_status(
    job_id: str,
    status: str,
    *,
    rows_transferred: Optional[int] = None,
    error_message: Optional[str] = None,
    dcl_response: Optional[dict] = None,
) -> bool:
    """Update runner job status and optional fields."""
    data: dict = {"status": status}
    # ... (existing field updates)

    result = sb.update("runner_jobs", data, filters={"job_id": job_id})

    # ✅ NEW: Log failures for debugging
    if not result:
        _log.warning(
            "No runner job found for job_id=%s when updating to status=%s. "
            "This may indicate a job_id mismatch between create and update calls.",
            job_id, status
        )

    return len(result) > 0
```

**Rationale**: Surface silent failures so mismatches are visible in logs.

---

#### Option B: Use run_id as job_id (Revert cff244d Changes) ❌ **NOT RECOMMENDED**

**Why not recommended**: Farm needs to group pipes by `run_id`. If each manifest has a unique run_id as job_id, Farm can't group the batch.

---

### Phase 3: Integration Testing

**Test Scenarios**:

1. **Single Pipe Dispatch**
   ```python
   # Trigger: Click "Run" on a single pipe
   result = dispatch_pipe("pipe_salesforce_001")

   # Verify:
   assert result["job_id"] == "pipe_salesforce_001"  # job_id is pipe_id
   assert result["run_id"] == "run_b83b051922fa"     # run_id is aod_run_id

   job = get_runner_job(result["job_id"])
   assert job["status"] == "queued"  # Initial state
   ```

2. **Batch Dispatch**
   ```python
   # Trigger: Click "Run" on all pipes
   results = dispatch_batch(["pipe_salesforce_001", "pipe_netsuite_001"])

   # Verify: All manifests have same run_id
   run_ids = {r["run_id"] for r in results}
   assert len(run_ids) == 1  # Only one unique run_id
   assert list(run_ids)[0] == "run_b83b051922fa"

   # Verify: Each has unique job_id
   job_ids = {r["job_id"] for r in results}
   assert len(job_ids) == 2  # Two unique job_ids (pipe_ids)
   ```

3. **Status Updates**
   ```python
   # Dispatch and update status
   result = dispatch_pipe("pipe_salesforce_001")

   # Simulate Farm dispatch success
   updated = update_runner_status(result["job_id"], "dispatched")
   assert updated == True  # Update succeeded

   # Verify status changed
   job = get_runner_job(result["job_id"])
   assert job["status"] == "dispatched"
   ```

4. **Farm Grouping** (Manual verification via Farm logs)
   ```
   Farm receives:
   - Manifest 1: run_id=run_b83b051922fa, pipe_id=pipe_salesforce_001
   - Manifest 2: run_id=run_b83b051922fa, pipe_id=pipe_netsuite_001

   Farm groups by run_id → Single batch execution
   ```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Schema migration failure** | Low | High | Test migration on dev database first, add rollback script |
| **Status update failures** | Medium | High | Add validation logging, check return values |
| **Farm compatibility** | Low | Medium | Verify Farm can handle shared run_id (confirm with Farm team) |
| **Re-dispatch conflicts** | Medium | Medium | Primary key on pipe_id prevents duplicate jobs for same pipe |
| **Missing aod_run_id** | Low | High | Fail-fast with clear error if no handoff found |

---

## Rollback Plan

If implementation fails:

1. **Revert Code Changes**
   ```bash
   git revert <commit-sha>
   ```

2. **Revert Schema Migration**
   ```sql
   ALTER TABLE runner_jobs DROP COLUMN run_id;
   DROP INDEX idx_runner_jobs_run_id;
   ```

3. **Clear Failed Jobs**
   ```sql
   DELETE FROM runner_jobs WHERE status = 'queued' AND created_at > <cutoff_timestamp>;
   ```

---

## Success Criteria

✅ **Phase 1 Complete**:
- No new run_ids generated by `_next_run_id()`
- All manifests use `aod_run_id` from handoff
- Error raised if `aod_run_id` is missing

✅ **Phase 2 Complete**:
- Database stores both `job_id` (pipe_id) and `run_id` (aod_run_id)
- All status updates use `pipe_id` for lookups
- No silent update failures (logged if no matching row)

✅ **Phase 3 Complete**:
- Integration tests pass
- Farm successfully groups pipes by `run_id`
- Dashboard shows correct status for all jobs
- Re-dispatch works without PRIMARY KEY violations

---

## Open Questions for Team

1. **Farm Team**: Can Farm handle multiple manifests with the same `run_id`? (Assumption: Yes, this is the goal)

2. **DCL Team**: Does DCL's `/ingest` endpoint include `x-pipe-id` in the request headers? (Assumption: Yes, already implemented)

3. **AOD Team**: Is `aod_run_id` always present in handoff payloads? (Assumption: Yes, required field)

4. **Ops Team**: Are there existing jobs in `runner_jobs` table that need migration? (Check before schema change)

---

## Timeline Estimate

| Phase | Tasks | Effort | Dependencies |
|-------|-------|--------|--------------|
| **Phase 1** | Remove ID generation, update callers | 2 hours | None |
| **Phase 2** | Fix job_id/run_id mismatch, schema migration | 4 hours | Phase 1 |
| **Phase 3** | Integration tests, manual verification | 3 hours | Phase 2 |
| **Total** | | **9 hours** (1-2 days) | |

---

## Implementation Order

1. ✅ Create this plan document (DONE)
2. Review plan with team (get approval)
3. Create schema migration script
4. Implement Phase 1 changes (stop generating IDs)
5. Implement Phase 2 changes (fix mismatch)
6. Run integration tests (Phase 3)
7. Deploy to dev environment
8. Manual verification with Farm team
9. Deploy to production

---

**Plan Version**: 1.0
**Author**: Claude Opus 4.6
**Date**: 2026-02-23
**Status**: DRAFT - Awaiting Review
