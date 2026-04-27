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

# Hard caps so a stalled socket can never hang a caller forever. The
# enrichment worker froze for ~20.5h on 2026-04-26 because a sync DB call on
# the asyncio event loop got stuck on a half-open socket — Linux TCP
# keepalive + retries can take hours to declare the connection dead. These
# values bound the worst case to seconds.
DB_CONNECT_TIMEOUT_S = int(os.getenv("DB_CONNECT_TIMEOUT_S", "10"))
# 120s server-side cap. Backend admin queries are the legitimate long ones;
# anything longer is almost certainly a stuck connection. The enrichment
# worker has its own tighter per-job ceiling on top of this.
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "120000"))

# Simple pool: min 1, max 3 connections (Supabase session pooler is limited)
_pool = None


def _get_pool():
    global _pool
    if _pool is None or _pool.closed:
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set in environment / .env file")
        _pool = psycopg2.pool.SimpleConnectionPool(
            2,
            10,
            _DATABASE_URL,
            connect_timeout=DB_CONNECT_TIMEOUT_S,
            options=f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}",
        )
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


_STALE_CONN_ERRS = (
    psycopg2.InterfaceError,
    psycopg2.OperationalError,
)


def _is_stale_conn_error(exc: Exception) -> bool:
    """Match the specific "pooled connection died on the server side"
    failures that retrying on a fresh connection should recover from.
    Don't retry on query-syntax errors or data errors."""
    if not isinstance(exc, _STALE_CONN_ERRS):
        return False
    msg = str(exc).lower()
    return (
        "connection already closed" in msg
        or "ssl syscall error" in msg
        or "server closed the connection" in msg
        or "connection is bad" in msg
        or "no connection" in msg
    )


def _discard_connection(conn):
    """Close + discard a broken connection instead of returning it to the pool."""
    try:
        conn.close()
    except Exception:
        pass


def fetch_all(sql: str, params: tuple | list = None) -> list[dict]:
    """Execute a query and return all rows as a list of dicts.
    One retry on a fresh connection if the pool handed us a stale one."""
    for attempt in (1, 2):
        conn = get_connection()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            conn.commit()
            return [dict(r) for r in rows]
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if attempt == 1 and _is_stale_conn_error(e):
                _discard_connection(conn)
                continue
            raise
        finally:
            # On retry we already discarded; otherwise return to pool.
            if conn.closed == 0:
                put_connection(conn)


def fetch_one(sql: str, params: tuple | list = None) -> dict | None:
    """Execute a query and return the first row as a dict, or None.
    One retry on a fresh connection if the pool handed us a stale one."""
    for attempt in (1, 2):
        conn = get_connection()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, params)
            row = cur.fetchone()
            cur.close()
            conn.commit()
            return dict(row) if row else None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if attempt == 1 and _is_stale_conn_error(e):
                _discard_connection(conn)
                continue
            raise
        finally:
            if conn.closed == 0:
                put_connection(conn)


def execute(sql: str, params: tuple | list = None):
    """Execute a write query (INSERT/UPDATE/DELETE) and commit.
    One retry on a fresh connection if the pool handed us a stale one."""
    for attempt in (1, 2):
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
            cur.close()
            return
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if attempt == 1 and _is_stale_conn_error(e):
                _discard_connection(conn)
                continue
            raise
        finally:
            if conn.closed == 0:
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
    """Enable pg_trgm and ensure name_normalized is populated.

    Safe to call on every startup — all statements use IF NOT EXISTS / are idempotent.
    Runs once per process (guarded by _trgm_migrated flag).

    Search V2 supersedes this with a GENERATED column on company_info
    (via migrations/2026-04-24_search_v2.sql). We detect the V2 migration
    by the presence of `f_unaccent()` and skip the legacy backfill in
    that case — the V2 migration owns both the column shape AND the
    index. The legacy branch stays as a safety net for environments
    where the operator hasn't applied the migration yet.
    """
    global _trgm_migrated
    if _trgm_migrated:
        return

    conn = get_connection()
    try:
        cur = conn.cursor()

        # 1. Enable the pg_trgm extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

        # 1b. Detect search V2 migration. If the IMMUTABLE f_unaccent()
        #     wrapper exists, the V2 migration has been applied and
        #     company_info.name_normalized is a GENERATED STORED column.
        #     In that case we skip the legacy ADD COLUMN / UPDATE path —
        #     those would either no-op (IF NOT EXISTS) or fail (can't
        #     UPDATE a generated column).
        cur.execute(
            "SELECT 1 FROM pg_proc WHERE proname = 'f_unaccent' LIMIT 1"
        )
        v2_applied = cur.fetchone() is not None
        if v2_applied:
            logger.info("search V2 migration detected — skipping legacy name_normalized backfill")
            # Still ensure the people-side GIN indexes exist (they are
            # created by the V2 migration too, but IF NOT EXISTS makes
            # this belt-and-suspenders safe).
            conn.commit()
            cur.close()
            _trgm_migrated = True
            return

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

        # 6b. Valuation AI commentary cache — generated text for each CBE so
        #     the PDF primer + repeat on-screen lookups don't each pay an LLM
        #     call. Refresh via scripts/generate_valuation_commentary.py.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS valuation_commentary_cache (
                enterprise_number TEXT PRIMARY KEY,
                commentary        TEXT NOT NULL,
                sector_used       TEXT,
                source_used       TEXT,
                lang              VARCHAR(2) DEFAULT 'en',
                generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_valuation_commentary_gen ON valuation_commentary_cache(generated_at DESC);")

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


# ---------------------------------------------------------------------------
# Phase-22 schema additions
# ---------------------------------------------------------------------------
# These run UNCONDITIONALLY at startup, regardless of whether the search V2
# migration has been applied. They were originally added inside
# ``ensure_trgm_setup`` but the V2 detection in that function returns early,
# which silently skipped every Phase-22 ALTER on prod environments where V2
# was already in place. Pulling them into a separate function decouples
# them from the trgm migration and makes the boot path explicit.

_phase22_migrated = False


def ensure_phase22_schema():
    """Apply Phase-22 schema additions: traction columns on activity_log,
    invoice_vendor_pattern + invoice_misclassification_log tables, deeper
    columns on platform_invoice. Idempotent — safe to call on every
    startup.
    """
    global _phase22_migrated
    if _phase22_migrated:
        return

    conn = get_connection()
    seed_pending = False
    try:
        cur = conn.cursor()

        # --- platform_invoice: parent/child taxonomy + classifier metadata ---
        for stmt in (
            "ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS parent_category TEXT",
            "ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS child_category TEXT",
            "ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS confidence REAL",
            "ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS reason TEXT",
            "ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS vendor_pattern_id INTEGER",
            "ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS line_items JSONB",
            "ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS classified_at TIMESTAMPTZ",
            "ALTER TABLE platform_invoice ADD COLUMN IF NOT EXISTS classifier_model TEXT",
        ):
            cur.execute(stmt)

        # --- invoice_vendor_pattern (operator-curated short-circuits) ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoice_vendor_pattern (
                id              SERIAL PRIMARY KEY,
                pattern         TEXT NOT NULL CHECK (length(pattern) BETWEEN 2 AND 200),
                vendor_canonical TEXT,
                parent_category TEXT NOT NULL,
                child_category  TEXT,
                priority        INTEGER NOT NULL DEFAULT 0,
                created_by      TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_used_at    TIMESTAMPTZ,
                hit_count       INTEGER NOT NULL DEFAULT 0
            );
        """)
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'invoice_vendor_pattern_pattern_len'
                ) THEN
                    BEGIN
                        ALTER TABLE invoice_vendor_pattern
                            ADD CONSTRAINT invoice_vendor_pattern_pattern_len
                            CHECK (length(pattern) BETWEEN 2 AND 200);
                    EXCEPTION WHEN check_violation THEN
                        NULL;
                    END;
                END IF;
            END$$;
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoice_vendor_pattern_priority
            ON invoice_vendor_pattern(priority DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_platform_invoice_classified
            ON platform_invoice(classified_at DESC);
        """)

        # --- invoice_misclassification_log (operator correction trail) ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoice_misclassification_log (
                id              SERIAL PRIMARY KEY,
                invoice_id      INTEGER REFERENCES platform_invoice(id) ON DELETE CASCADE,
                old_parent      TEXT,
                old_child       TEXT,
                new_parent      TEXT,
                new_child       TEXT,
                old_vendor      TEXT,
                new_vendor      TEXT,
                old_amount_cents BIGINT,
                new_amount_cents BIGINT,
                corrected_by    TEXT,
                corrected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_invoice_misclass_invoice
            ON invoice_misclassification_log(invoice_id);
        """)

        # --- activity_log: traction columns (sessions, UA bucket, country) ---
        for stmt in (
            "ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS session_id TEXT",
            "ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS ua_family TEXT",
            "ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS device_type TEXT",
            "ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS country_code VARCHAR(2)",
        ):
            cur.execute(stmt)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_log_session
            ON activity_log(session_id, created_at DESC)
            WHERE session_id IS NOT NULL;
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_log_ua_date
            ON activity_log(ua_family, created_at DESC)
            WHERE ua_family IS NOT NULL;
        """)

        conn.commit()
        cur.close()
        seed_pending = True
        _phase22_migrated = True
        logger.info("Phase-22 schema ensured")
    except Exception:
        conn.rollback()
        logger.exception("Phase-22 schema migration failed (non-fatal)")
    finally:
        put_connection(conn)

    # Post-commit: seed default vendor patterns (uses a fresh pooled
    # connection, so the table must already be visible — i.e. the
    # transaction above must have committed first).
    if seed_pending:
        try:
            from invoice_classifier import seed_default_patterns
            n = seed_default_patterns()
            if n:
                logger.info("Seeded %d invoice vendor patterns", n)
        except Exception:
            logger.exception("seed_default_patterns failed (non-fatal)")


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
    """Re-run normalization on all company_info rows. Returns count of rows updated.

    Post-search-V2 migration `company_info.name_normalized` is a
    GENERATED STORED column — Postgres rejects any UPDATE that targets
    it. We detect that situation via `f_unaccent()` and short-circuit
    with a no-op return so admin callers don't see a 500.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        # V2 migration guard — generated columns are self-maintained.
        cur.execute("SELECT 1 FROM pg_proc WHERE proname = 'f_unaccent' LIMIT 1")
        if cur.fetchone() is not None:
            cur.close()
            logger.info(
                "refresh_all_normalized_names: search V2 detected — "
                "name_normalized is a generated column, no-op"
            )
            return 0

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
