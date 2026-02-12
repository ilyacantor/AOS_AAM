"""
Database connection and helper utilities.
"""
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Optional
import uuid

from ..config import settings
from ..logger import get_logger

_log = get_logger("db")

DATABASE = settings.DATABASE_URL


@contextmanager
def get_db():
    """Context manager for database connections with auto-commit/rollback."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_connection():
    """Get database connection with row factory (legacy — prefer get_db())."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def _add_column_if_not_exists(cursor, table_name: str, column_name: str, column_def: str):
    """Add a column to a table if it doesn't exist."""
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
