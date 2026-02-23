# Bug Analysis: Commit cff244d Instability

**Commit**: `cff244d` - "fix(dispatch): use aod_run_id for Farm batch grouping, pipe_id for AAM tracking"
**Status**: ❌ UNSTABLE - Rolled back
**Root Cause**: Job ID mismatch between database schema and status update calls

---

## The Change

### What cff244d Tried to Do

**Goal**: Enable Farm to group all pipes in a dispatch batch using a shared `run_id`

**Implementation**:
1. **Database**: Store `job_id = pipe_id` (unique per pipe)
2. **Manifest**: Set `run_id = aod_run_id` (shared across batch)
3. **Rationale**: Farm receives manifests with same `run_id` → groups into single batch

### Files Modified

| File | Lines Changed | What Changed |
|------|---------------|--------------|
| `app/db/runner_jobs.py` | 38, 54 | Use `pipe_id` as `job_id` (PRIMARY KEY) |
| `app/services/runner_dispatch.py` | 369, 374 | Set `run_id = aod_run_id` for all manifests |

---

## The Bug

### Job ID Lookup Mismatch

**Database Schema** (`runner_jobs` table):
```sql
job_id VARCHAR PRIMARY KEY  -- Stores pipe_id (e.g., "pipe_salesforce_001")
pipe_id VARCHAR             -- Also stores pipe_id (redundant)
```

**Status Update Calls** (all use `run_id` as lookup key):
```python
# runner_dispatch.py:456
update_runner_status(manifest.run_id, "dispatched")
# manifest.run_id = aod_run_id (e.g., "aod_20260223_techwave")

# runner_dispatch.py:471
update_runner_status(manifest.run_id, "failed", error_message=error_msg)

# dcl_ingest.py:92
update_runner_status(x_run_id, "pushing")
# x_run_id from HTTP header = aod_run_id

# dcl_ingest.py:103
update_runner_status(x_run_id, "completed", rows_transferred=...)
```

**Actual Database Query** (`runner_jobs.py:90`):
```python
sb.update("runner_jobs", data, filters={"job_id": job_id})
# Tries to find row where job_id = aod_run_id
# But job_id column actually contains pipe_id
# Result: No matching rows, update fails silently
```

---

## Impact

### What Breaks

1. **Status Updates Fail Silently**
   - Farm dispatch succeeds but job stays "queued" (not "dispatched")
   - Farm failures not recorded (job stays "queued")
   - DCL ingestion progress not tracked (jobs never marked "pushing" or "completed")

2. **Dashboard Shows Incorrect State**
   - All jobs appear stuck in "queued" state
   - Progress monitor shows 0 completed even after successful runs
   - Operators can't tell if dispatch succeeded

3. **Re-Dispatch Attempts Fail**
   - If operator clicks "Run" again, get PRIMARY KEY violation
   - Error: "Runner jobs already exist for pipe_id(s): [...]"
   - Must manually clear jobs before re-dispatching

4. **Worker Retry Logic Broken**
   - Background worker can't retry jobs that appear "queued"
   - Jobs stuck forever with no path to recovery

### What Still Works

✅ **Job Creation**: Bulk insert succeeds (uses pipe_id correctly)
✅ **Worker Claims**: `_claim_queued_jobs()` returns correct job_ids (pipe_ids)
✅ **Worker Dispatch**: Worker uses `job_id` variable (pipe_id) for status updates, so worker flow is OK
✅ **Database Queries**: Lookups by pipe_id work fine

---

## Why It Wasn't Caught

### Missing Validation

1. **No return value check**: `update_runner_status()` returns bool (True if row updated, False if no match), but callers don't check it
   ```python
   # Should be:
   updated = update_runner_status(manifest.run_id, "dispatched")
   if not updated:
       _log.error("Failed to update status for run_id=%s", manifest.run_id)
   ```

2. **Silent failure**: Database UPDATE with no matching rows returns 0 rows affected but doesn't raise an exception

3. **No integration test**: Tests don't verify status transitions after dispatch

---

## The Correct Fix

### Option A: Use pipe_id Consistently (Recommended)

**What to change**: Update all `update_runner_status()` calls to use `pipe_id` instead of `run_id`

```python
# runner_dispatch.py:456
update_runner_status(manifest.source.pipe_id, "dispatched")

# runner_dispatch.py:471
update_runner_status(manifest.source.pipe_id, "failed", error_message=error_msg)

# dcl_ingest.py:92,103
# Need to get pipe_id from manifest or pass it via header
update_runner_status(pipe_id, "pushing")
```

**Pros**: Simple, consistent with database schema
**Cons**: Requires passing `pipe_id` to DCL ingest (currently only gets `x_run_id`)

---

### Option B: Revert to run_id as job_id (Original Design)

**What to change**: Revert cff244d changes, use `run_id` as `job_id` in database

```python
# runner_jobs.py:38
job_ids = [m["run_id"] for m in manifests]  # Back to original

# runner_jobs.py:54
"job_id": m["run_id"]  # Back to original
```

**Pros**: No changes to status update calls, everything works
**Cons**: Farm can't group by run_id if each manifest has unique run_id

---

### Option C: Dual-Key Lookup (Complex)

**What to change**: Make `update_runner_status()` smart enough to look up by either `job_id` OR `run_id`

```python
def update_runner_status(job_or_run_id: str, status: str, **kwargs):
    # Try job_id first
    result = sb.update("runner_jobs", data, filters={"job_id": job_or_run_id})
    if not result:
        # Try run_id as fallback
        result = sb.update("runner_jobs", data, filters={"run_id": job_or_run_id})
    return len(result) > 0
```

**Pros**: Backward compatible, works with either identifier
**Cons**: Complex, hides the mismatch, may update wrong row if run_id collides

---

## Recommendation

### Go with **Option A** (Use pipe_id consistently)

**Why**:
1. Database schema using `pipe_id` as PRIMARY KEY is correct (unique, immutable)
2. Fixes the root cause instead of working around it
3. Makes code explicit about what identifier is used where

**Implementation**:
1. Update `runner_dispatch.py:456, 471` to use `manifest.source.pipe_id`
2. Update `dcl_ingest.py` to accept `x-pipe-id` header (already exists!) and use it for status updates
3. Add validation: Check return value of `update_runner_status()` and log errors
4. Add integration test: Verify status transitions through full dispatch cycle

---

## Prevention

### Add These Safeguards

1. **Validation in update_runner_status**:
   ```python
   result = sb.update("runner_jobs", data, filters={"job_id": job_id})
   if not result:
       _log.warning("No job found for job_id=%s, status update skipped", job_id)
   return len(result) > 0
   ```

2. **Check return values**:
   ```python
   updated = update_runner_status(pipe_id, "dispatched")
   if not updated:
       raise RuntimeError(f"Failed to update job {pipe_id} to dispatched")
   ```

3. **Integration test**:
   ```python
   def test_dispatch_status_updates():
       # Dispatch a job
       result = dispatch_pipe(pipe_id)
       # Verify status changed to "dispatched"
       job = get_runner_job(result["job_id"])
       assert job["status"] == "dispatched"
   ```

---

## Conclusion

The commit was **architecturally sound** (using pipe_id as PRIMARY KEY is correct) but **incompletely implemented** (didn't update all lookup call sites).

**Root cause**: Job ID used for database storage (pipe_id) didn't match job ID used for status lookups (run_id).

**Fix**: Update all status update calls to consistently use `pipe_id` as the lookup key.

---

**Analysis Date**: 2026-02-23
**Analyst**: Claude Sonnet 4.5
