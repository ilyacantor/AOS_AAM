-- Migration: Add run_id column to runner_jobs table
-- Purpose: Store both job_id (pipe_id) and run_id (aod_run_id) for proper tracking
-- Date: 2026-02-23

-- Add run_id column (nullable initially for existing rows)
ALTER TABLE runner_jobs ADD COLUMN IF NOT EXISTS run_id VARCHAR;

-- Create index for efficient lookups by run_id
CREATE INDEX IF NOT EXISTS idx_runner_jobs_run_id ON runner_jobs(run_id);

-- Comment for documentation
COMMENT ON COLUMN runner_jobs.run_id IS 'AOD run identifier (shared across all pipes in a batch dispatch). Used by Farm for batch grouping.';
COMMENT ON COLUMN runner_jobs.job_id IS 'Unique job identifier (uses pipe_id as PRIMARY KEY). Used by AAM for job tracking and status updates.';
