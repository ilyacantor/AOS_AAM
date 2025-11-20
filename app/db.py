"""
SQLite Database Module
Handles credentials storage and retrieval
"""
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any
import os

DB_PATH = "salesforce.db"


def get_db_connection():
    """Get SQLite database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Initialize SQLite database with salesforce_credentials table
    
    For this POC, we use a single-row table (always id=1)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS salesforce_credentials (
            id INTEGER PRIMARY KEY,
            environment TEXT,
            base_url TEXT,
            instance_url TEXT,
            client_id TEXT,
            client_secret TEXT,
            access_token TEXT,
            refresh_token TEXT,
            token_type TEXT,
            expires_at TEXT,
            status TEXT DEFAULT 'disconnected',
            error_message TEXT,
            state TEXT,
            callback_url TEXT,
            updated_at TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    
    print("✓ Database initialized")


def get_credentials() -> Optional[Dict[str, Any]]:
    """
    Get the single credentials record (id=1)
    
    Returns None if no record exists
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM salesforce_credentials WHERE id = 1")
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return dict(row)
    return None


def save_credentials(
    environment: str,
    base_url: str,
    client_id: str,
    client_secret: str,
    state: str,
    callback_url: str
):
    """
    Save or update initial credentials when starting OAuth flow
    
    This clears any old tokens and sets status to 'disconnected'
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    # Use INSERT OR REPLACE to handle both insert and update
    cursor.execute("""
        INSERT OR REPLACE INTO salesforce_credentials (
            id, environment, base_url, client_id, client_secret,
            state, callback_url, status, updated_at,
            access_token, refresh_token, instance_url, token_type, expires_at, error_message
        ) VALUES (1, ?, ?, ?, ?, ?, ?, 'disconnected', ?, NULL, NULL, NULL, NULL, NULL, NULL)
    """, (environment, base_url, client_id, client_secret, state, callback_url, now))
    
    conn.commit()
    conn.close()


def update_credentials(
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    instance_url: Optional[str] = None,
    token_type: Optional[str] = None,
    expires_at: Optional[str] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None
):
    """
    Update credentials after token exchange or refresh
    
    Only updates fields that are provided (not None)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    # Build dynamic UPDATE query based on provided fields
    updates = []
    values = []
    
    if access_token is not None:
        updates.append("access_token = ?")
        values.append(access_token)
    
    if refresh_token is not None:
        updates.append("refresh_token = ?")
        values.append(refresh_token)
    
    if instance_url is not None:
        updates.append("instance_url = ?")
        values.append(instance_url)
    
    if token_type is not None:
        updates.append("token_type = ?")
        values.append(token_type)
    
    if expires_at is not None:
        updates.append("expires_at = ?")
        values.append(expires_at)
    
    if status is not None:
        updates.append("status = ?")
        values.append(status)
    
    if error_message is not None:
        updates.append("error_message = ?")
        values.append(error_message)
    
    # Always update timestamp
    updates.append("updated_at = ?")
    values.append(now)
    
    if updates:
        query = f"UPDATE salesforce_credentials SET {', '.join(updates)} WHERE id = 1"
        cursor.execute(query, values)
        conn.commit()
    
    conn.close()
