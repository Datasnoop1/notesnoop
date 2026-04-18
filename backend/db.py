"""Database connection module for the FastAPI backend.

Uses a simple connection pool to avoid exhausting Supabase session pooler limits.
"""

import os
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DATABASE_URL = os.getenv("DATABASE_URL", "")

# Simple pool: min 1, max 3 connections (Supabase session pooler is limited)
_pool = None


def _get_pool():
    global _pool
    if _pool is None or _pool.closed:
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in environment / .env file")
        _pool = psycopg2.pool.SimpleConnectionPool(2, 10, _DATABASE_URL)
    return _pool


def get_connection():
    """Get a pooled PostgreSQL connection."""
    conn = _get_pool().getconn()
    conn.autocommit = False
    return conn


def put_connection(conn):
    """Return a connection to the pool."""
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


@contextmanager
def get_conn():
    """Context manager that yields a pooled connection."""
    conn = get_connection()
    try:
        yield conn
    finally:
        put_connection(conn)


def fetch_all(sql: str, params: tuple | list = None) -> list[dict]:
    """Execute a query and return all rows as a list of dicts."""
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.commit()
        return [dict(r) for r in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


def fetch_one(sql: str, params: tuple | list = None) -> dict | None:
    """Execute a query and return the first row as a dict, or None."""
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        conn.commit()
        return dict(row) if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


def execute(sql: str, params: tuple | list = None):
    """Execute a write query (INSERT/UPDATE/DELETE) and commit."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


@contextmanager
def transaction():
    """Context manager for multi-statement transactions.

    Yields (conn, cursor). Commits on clean exit, rolls back on exception.
    Use this for operations that need atomicity across multiple statements.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield conn, cur
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)


# ---------------------------------------------------------------------------
# pg_trgm fuzzy matching migration
# ---------------------------------------------------------------------------

# Belgian legal-form suffixes to strip during name normalization
_BELGIAN_SUFFIXES_RE = (
    r"\s*("
    r"NV|SA|BVBA|SRL|SPRL|BV|CVBA|SCRL|VOF|SNC|SE|"
    r"COMM\.?\s*V|SCS|GCV|ASBL|VZW|AISBL|IVZW"
    r")\s*$"
)

_trgm_migrated = False


def ensure_trgm_setup():
    """Enable pg_trgm, add name_normalized column, populate it, and create GIN index.

    Safe to call on every startup — all statements use IF NOT EXISTS / are idempotent.
    Runs once per process (guarded by _trgm_migrated flag).
    """
    global _trgm_migrated
    if _trgm_migrated:
        return

    conn = get_connection()
    try:
        cur = conn.cursor()

        # 1. Enable the pg_trgm extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

        # 2. Add name_normalized column if it doesn't exist
        cur.execute(
            "ALTER TABLE company_info ADD COLUMN IF NOT EXISTS name_normalized TEXT;"
        )

        # 3. Populate name_normalized for rows where it is NULL
        #    (strip Belgian legal suffixes, lowercase, collapse whitespace)
        cur.execute(f"""
            UPDATE company_info
            SET name_normalized = TRIM(REGEXP_REPLACE(
                LOWER(REGEXP_REPLACE(
                    name,
                    %s,
                    '', 'gi'
                )),
                '\\s+', ' ', 'g'
            ))
            WHERE name_normalized IS NULL AND name IS NOT NULL;
        """, (_BELGIAN_SUFFIXES_RE,))
        normalized_count = cur.rowcount

        # 4. Create GIN trigram indexes
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ci_name_trgm
            ON company_info USING GIN (name_normalized gin_trgm_ops);
        """)
        # 5. GIN trigram indexes on people tables for ILIKE searches
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_name_trgm
            ON administrator USING GIN (name gin_trgm_ops);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sh_name_trgm
            ON shareholder USING GIN (name gin_trgm_ops);
        """)

        # 6. activity_log indexes — the table has no indexes by default and
        #    EVERY /api/* call hits it (INSERT via ActivityLogMiddleware +
        #    COUNT via TierLimitMiddleware). Without these, seq-scans cost
        #    hundreds of ms per AI call once the table grows.
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_log_user_date
            ON activity_log(user_email, created_at DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_log_endpoint_date
            ON activity_log(endpoint, created_at DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_log_date
            ON activity_log(created_at DESC);
        """)

        # 7-OpenData. TED procurement + Regsol insolvency + Staatsblad events —
        # open-data enrichment tables, populated by scripts/open_data_*.py.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS procurement_award (
                id              SERIAL PRIMARY KEY,
                ted_notice_id   TEXT UNIQUE,
                enterprise_number TEXT,
                supplier_name   TEXT,
                supplier_vat    TEXT,
                buyer_name      TEXT,
                award_date      DATE,
                contract_value  NUMERIC(14,2),
                currency        VARCHAR(3) DEFAULT 'EUR',
                cpv_code        TEXT,
                title           TEXT,
                country         VARCHAR(2) DEFAULT 'BE'
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_procurement_award_ent ON procurement_award(enterprise_number);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_procurement_award_date ON procurement_award(award_date DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_procurement_award_vat ON procurement_award(supplier_vat);")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS insolvency_case (
                id                SERIAL PRIMARY KEY,
                enterprise_number TEXT NOT NULL,
                docket_number     TEXT UNIQUE,
                case_type         TEXT,
                court             TEXT,
                opened_at         DATE,
                closed_at         DATE,
                status            TEXT,
                curator_name      TEXT,
                last_scraped_at   TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_insolvency_case_ent ON insolvency_case(enterprise_number);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_insolvency_case_opened ON insolvency_case(opened_at DESC);")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS staatsblad_event (
                id                SERIAL PRIMARY KEY,
                enterprise_number TEXT NOT NULL,
                reference         TEXT,
                pub_date          DATE,
                event_type        TEXT,
                subject_name      TEXT,
                raw_title         TEXT,
                extracted_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_staatsblad_event_ent ON staatsblad_event(enterprise_number, pub_date DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_staatsblad_event_type ON staatsblad_event(event_type);")

        # 7a. platform_invoice — inbound invoice records from
        #     invoice@datasnoop.be (ingested by scripts/invoice_ingest.py).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS platform_invoice (
                id              SERIAL PRIMARY KEY,
                message_id      TEXT UNIQUE,
                sender          TEXT,
                subject         TEXT,
                received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                invoice_date    DATE,
                amount_cents    BIGINT,
                currency        VARCHAR(3) DEFAULT 'EUR',
                vendor          TEXT,
                category        TEXT,
                raw_body        TEXT,
                attachment_path TEXT,
                confirmed       BOOLEAN DEFAULT FALSE
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_platform_invoice_received
            ON platform_invoice(received_at DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_platform_invoice_date
            ON platform_invoice(invoice_date DESC);
        """)

        # 7. company_view_history — per-user "last visit" log, for the
        #    "what changed since last visit" banner on company profiles.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS company_view_history (
                user_email         TEXT NOT NULL,
                enterprise_number  VARCHAR(10) NOT NULL,
                last_viewed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                prev_viewed_at     TIMESTAMPTZ,
                PRIMARY KEY (user_email, enterprise_number)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_company_view_history_user
            ON company_view_history(user_email, last_viewed_at DESC);
        """)

        # 8. sector_percentiles — materialised view with percent_rank of
        #    every company on rev/ebitda/margin/fte/fixed_assets within its
        #    NACE-2 sector. Used by the screener rank pills and (future)
        #    radar chart. Refresh happens at the end of the daily NBB
        #    batch pipeline; initial build runs here on boot for a fresh
        #    environment.
        conn.commit()  # separate tx for the MV so partial failure doesn't roll back the indexes
        cur.execute("SELECT to_regclass('public.sector_percentiles')")
        if cur.fetchone()[0] is None:
            logger.info("sector_percentiles MV missing — building (one-time, may take ~1 min on full DB)")
            cur.execute("""
                CREATE MATERIALIZED VIEW sector_percentiles AS
                SELECT fl.enterprise_number,
                       substr(ci.nace_code, 1, 2) AS nace2,
                       percent_rank() OVER (
                           PARTITION BY substr(ci.nace_code, 1, 2)
                           ORDER BY fl.revenue NULLS FIRST
                       )::real AS rev_rank,
                       percent_rank() OVER (
                           PARTITION BY substr(ci.nace_code, 1, 2)
                           ORDER BY fl.ebitda NULLS FIRST
                       )::real AS ebitda_rank,
                       percent_rank() OVER (
                           PARTITION BY substr(ci.nace_code, 1, 2)
                           ORDER BY (CASE WHEN fl.revenue > 0
                                          THEN fl.ebitda / fl.revenue END) NULLS FIRST
                       )::real AS margin_rank,
                       percent_rank() OVER (
                           PARTITION BY substr(ci.nace_code, 1, 2)
                           ORDER BY fl.fte_total NULLS FIRST
                       )::real AS fte_rank,
                       percent_rank() OVER (
                           PARTITION BY substr(ci.nace_code, 1, 2)
                           ORDER BY fl.fixed_assets NULLS FIRST
                       )::real AS fixed_assets_rank,
                       COUNT(*) OVER (PARTITION BY substr(ci.nace_code, 1, 2)) AS peer_count
                FROM financial_latest fl
                JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
                WHERE ci.nace_code IS NOT NULL AND length(ci.nace_code) >= 2;
            """)
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS sector_percentiles_pkey
                ON sector_percentiles(enterprise_number);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sector_percentiles_nace2
                ON sector_percentiles(nace2);
            """)
        conn.commit()
        cur.close()
        _trgm_migrated = True
        logger.info(
            "pg_trgm setup complete: normalized %d company names, GIN index ensured",
            normalized_count,
        )
    except Exception:
        conn.rollback()
        logger.exception("pg_trgm migration failed (non-fatal, will retry next startup)")
    finally:
        put_connection(conn)


def normalize_name(name: str) -> str:
    """Normalize a company name for trigram matching (Python-side).

    Strips Belgian legal-form suffixes, lowercases, collapses whitespace.
    Used to normalize query inputs before comparing against name_normalized.
    """
    import re
    if not name:
        return ""
    # Strip Belgian legal suffixes
    cleaned = re.sub(_BELGIAN_SUFFIXES_RE, "", name, flags=re.IGNORECASE)
    # Lowercase and collapse whitespace
    return re.sub(r"\s+", " ", cleaned.lower()).strip()


def refresh_all_normalized_names() -> int:
    """Re-run normalization on all company_info rows. Returns count of rows updated."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            UPDATE company_info
            SET name_normalized = TRIM(REGEXP_REPLACE(
                LOWER(REGEXP_REPLACE(
                    name,
                    %s,
                    '', 'gi'
                )),
                '\\s+', ' ', 'g'
            ))
            WHERE name IS NOT NULL;
        """, (_BELGIAN_SUFFIXES_RE,))
        count = cur.rowcount
        conn.commit()
        cur.close()
        logger.info("Re-normalized %d company names", count)
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)
