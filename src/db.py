"""Centralized database connection module for PostgreSQL (Supabase).

All database access should go through this module. Replaces direct
sqlite3.connect() calls throughout the codebase.
"""

import os
import psycopg2
import psycopg2.pool
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

_DATABASE_URL = os.getenv("DATABASE_URL", "")

# Module-level connection pool (lazy-initialized)
_pool = None


def get_connection():
    """Get a PostgreSQL connection. Caller is responsible for closing it."""
    if not _DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment / .env file")
    conn = psycopg2.connect(_DATABASE_URL)
    conn.autocommit = False
    # Ensure read-write mode (Supabase session pooler may default to read-only)
    cur = conn.cursor()
    cur.execute("SET default_transaction_read_only = off")
    conn.commit()
    cur.close()
    return conn


def get_pool(minconn=2, maxconn=10):
    """Get or create a thread-safe connection pool (for pipeline workers)."""
    global _pool
    if _pool is None or _pool.closed:
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in environment / .env file")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn, maxconn, _DATABASE_URL
        )
    return _pool


def get_dict_cursor(conn):
    """Get a cursor that returns rows as dicts (replaces sqlite3.Row)."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def execute_schema(conn):
    """Execute schema.sql on the given connection.

    psycopg2 doesn't have executescript(), so we read the file,
    split on statement boundaries, and execute each one.
    """
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    cur = conn.cursor()
    # Execute the entire schema as one block — PostgreSQL handles multiple statements
    cur.execute(schema_sql)
    conn.commit()
    cur.close()


def upsert_sql(table, columns, pk_columns):
    """Generate an INSERT ... ON CONFLICT DO UPDATE statement.

    Returns a SQL string with %s placeholders for psycopg2.

    Example:
        upsert_sql("enterprise", ["enterprise_number", "status", "start_date"],
                    ["enterprise_number"])
        → INSERT INTO enterprise (enterprise_number, status, start_date)
          VALUES (%s, %s, %s)
          ON CONFLICT (enterprise_number) DO UPDATE SET
            status = EXCLUDED.status, start_date = EXCLUDED.start_date
    """
    cols_str = ", ".join(columns)
    vals_str = ", ".join(["%s"] * len(columns))
    update_cols = [c for c in columns if c not in pk_columns]

    if update_cols:
        set_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        return (
            f"INSERT INTO {table} ({cols_str}) VALUES ({vals_str}) "
            f"ON CONFLICT ({', '.join(pk_columns)}) DO UPDATE SET {set_str}"
        )
    else:
        # All columns are part of the PK — just ignore conflicts
        return (
            f"INSERT INTO {table} ({cols_str}) VALUES ({vals_str}) "
            f"ON CONFLICT DO NOTHING"
        )
