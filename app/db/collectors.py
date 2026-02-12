"""
Collector operations
"""
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional

from .connection import get_connection

# ============================================================================
# COLLECTOR OPERATIONS
# ============================================================================

def list_collectors() -> list[dict]:
    """List all collectors"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collectors ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "collector_id": row["collector_id"],
        "name": row["name"],
        "collector_type": row["collector_type"],
        "description": row["description"],
        "enabled": bool(row["enabled"]),
        "last_run": row["last_run"],
        "created_at": row["created_at"]
    } for row in rows]


def update_collector_last_run(collector_id: str):
    """Update collector's last run timestamp"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE collectors SET last_run = ? WHERE collector_id = ?",
        (datetime.utcnow().isoformat(), collector_id)
    )
    conn.commit()
    conn.close()


# ============================================================================
# COLLECTOR RUN OPERATIONS (v1 Practical Interface)
# ============================================================================

def create_collector_run(collector_id: str) -> str:
    """Create a new collector run and return the run_id"""
    conn = get_connection()
    cursor = conn.cursor()
    
    run_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO collector_runs (run_id, collector_id, status, started_at)
        VALUES (?, ?, ?, ?)
    """, (run_id, collector_id, "running", now))
    
    conn.commit()
    conn.close()
    
    return run_id


def complete_collector_run(run_id: str, status: str, observations_count: int, error_message: Optional[str] = None) -> bool:
    """Complete a collector run with final status"""
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        UPDATE collector_runs 
        SET status = ?, completed_at = ?, observations_count = ?, error_message = ?
        WHERE run_id = ?
    """, (status, now, observations_count, error_message, run_id))
    
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    return affected > 0


def get_collector_run(run_id: str) -> Optional[dict]:
    """Get a collector run by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collector_runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "run_id": row["run_id"],
            "collector_id": row["collector_id"],
            "status": row["status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "observations_count": row["observations_count"],
            "error_message": row["error_message"]
        }
    return None


def list_collector_runs(collector_id: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """List collector runs with optional collector filter"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if collector_id:
        query = "SELECT * FROM collector_runs WHERE collector_id = ? ORDER BY started_at DESC"
        params = [collector_id]
    else:
        query = "SELECT * FROM collector_runs ORDER BY started_at DESC"
        params = []
    
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    
    cursor.execute(query, params)
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        "run_id": row["run_id"],
        "collector_id": row["collector_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "observations_count": row["observations_count"],
        "error_message": row["error_message"]
    } for row in rows]


