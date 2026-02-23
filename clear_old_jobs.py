#!/usr/bin/env python
"""
Clear old runner jobs from the database.

This removes all jobs from runner_jobs table so fresh dispatches can proceed
without "already exist" conflicts.
"""
import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app.db import supabase_client as sb
from psycopg2 import sql as psql
from app.logger import get_logger

_log = get_logger("clear_jobs")


def clear_all_jobs():
    """Delete all rows from runner_jobs table."""
    try:
        query = psql.SQL("DELETE FROM {} RETURNING job_id").format(
            sb._ident("runner_jobs")
        )
        rows = sb._execute_composed(query)
        count = len(rows)
        _log.info("Deleted %d jobs from runner_jobs table", count)
        print(f"✓ Cleared {count} jobs from runner_jobs table")
        return count
    except Exception as exc:
        _log.error("Failed to clear jobs: %s", exc)
        print(f"✗ Error: {exc}")
        return 0


def show_job_status():
    """Show current job counts by status before clearing."""
    try:
        query = psql.SQL(
            "SELECT status, COUNT(*) as cnt FROM {} GROUP BY status ORDER BY status"
        ).format(sb._ident("runner_jobs"))
        rows = sb._execute_composed(query)

        if not rows:
            print("No jobs in database")
            return

        print("\nCurrent job status:")
        total = 0
        for r in rows:
            count = int(r["cnt"])
            total += count
            print(f"  {r['status']:15} {count:4} jobs")
        print(f"  {'TOTAL':15} {total:4} jobs")
        print()
    except Exception as exc:
        _log.error("Failed to query job status: %s", exc)
        print(f"✗ Error querying status: {exc}")


if __name__ == "__main__":
    print("Runner Jobs Cleanup\n" + "=" * 50)

    # Show current state
    show_job_status()

    # Clear all jobs
    count = clear_all_jobs()

    if count > 0:
        print("\n✓ Ready for fresh dispatch")
    else:
        print("\n⚠ No jobs were cleared (table may already be empty)")
