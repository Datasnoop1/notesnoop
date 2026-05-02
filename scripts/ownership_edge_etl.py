#!/usr/bin/env python3
"""One-shot historical ETL for ownership_edge.

Loads deterministic ownership edges from existing NBB shareholder rows,
NBB participating-interest rows, and relevant Staatsblad event rows.
The script is idempotent: reruns only insert new rows or update rows whose
resolved parent/source metadata improved.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "backend"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional in containers
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv:
    load_dotenv(ROOT / ".env.production")


LOG = logging.getLogger("ownership_edge_etl")


UPSERT_SET = """
    parent_kind = EXCLUDED.parent_kind,
    parent_id = EXCLUDED.parent_id,
    parent_name_raw = EXCLUDED.parent_name_raw,
    parent_identifier_scheme = EXCLUDED.parent_identifier_scheme,
    parent_identifier_value = EXCLUDED.parent_identifier_value,
    parent_country = EXCLUDED.parent_country,
    child_kind = EXCLUDED.child_kind,
    child_id = EXCLUDED.child_id,
    pct = EXCLUDED.pct,
    edge_kind = EXCLUDED.edge_kind,
    source_filing = EXCLUDED.source_filing,
    source_rank = EXCLUDED.source_rank,
    fiscal_year = EXCLUDED.fiscal_year,
    deposit_date = EXCLUDED.deposit_date,
    valid_from = EXCLUDED.valid_from,
    valid_to = EXCLUDED.valid_to,
    confidence = EXCLUDED.confidence,
    updated_at = NOW()
"""


UPSERT_DIFF = """
    ROW(
        ownership_edge.parent_kind,
        ownership_edge.parent_id,
        ownership_edge.parent_name_raw,
        ownership_edge.parent_identifier_scheme,
        ownership_edge.parent_identifier_value,
        ownership_edge.parent_country,
        ownership_edge.child_kind,
        ownership_edge.child_id,
        ownership_edge.pct,
        ownership_edge.edge_kind,
        ownership_edge.source_filing,
        ownership_edge.source_rank,
        ownership_edge.fiscal_year,
        ownership_edge.deposit_date,
        ownership_edge.valid_from,
        ownership_edge.valid_to,
        ownership_edge.confidence
    ) IS DISTINCT FROM ROW(
        EXCLUDED.parent_kind,
        EXCLUDED.parent_id,
        EXCLUDED.parent_name_raw,
        EXCLUDED.parent_identifier_scheme,
        EXCLUDED.parent_identifier_value,
        EXCLUDED.parent_country,
        EXCLUDED.child_kind,
        EXCLUDED.child_id,
        EXCLUDED.pct,
        EXCLUDED.edge_kind,
        EXCLUDED.source_filing,
        EXCLUDED.source_rank,
        EXCLUDED.fiscal_year,
        EXCLUDED.deposit_date,
        EXCLUDED.valid_from,
        EXCLUDED.valid_to,
        EXCLUDED.confidence
    )
"""


SHAREHOLDER_SQL = f"""
WITH base AS (
    SELECT
        sh.enterprise_number,
        sh.deposit_key,
        sh.name,
        sh.identifier,
        sh.shareholder_type,
        sh.ownership_pct,
        CASE
            WHEN sh.fiscal_year ~ '^[0-9]{{4}}$' THEN sh.fiscal_year::int
            ELSE NULL
        END AS fy,
        concat_ws('|', sh.enterprise_number, sh.deposit_key, sh.name) AS source_pk,
        regexp_replace(coalesce(sh.identifier, ''), '\\D', '', 'g') AS identifier_digits,
        nullif(regexp_replace(upper(trim(coalesce(sh.identifier, ''))), '\\s+', '', 'g'), '') AS identifier_value
    FROM shareholder_fact sh
    WHERE sh.enterprise_number ~ '^[0-9]{{10}}$'
      AND nullif(trim(sh.name), '') IS NOT NULL
),
fy_next AS (
    SELECT
        enterprise_number,
        fy,
        lead(fy) OVER (PARTITION BY enterprise_number ORDER BY fy) AS next_fy
    FROM (
        SELECT DISTINCT enterprise_number, fy
        FROM base
        WHERE fy IS NOT NULL
    ) years
),
source AS (
    SELECT
        CASE
            WHEN b.shareholder_type = 'individual' AND p.person_id IS NOT NULL THEN 'person'
            WHEN b.identifier_digits ~ '^[0-9]{{10}}$' THEN 'company'
            WHEN b.identifier_value IS NOT NULL THEN 'external_org'
            ELSE 'unknown'
        END AS parent_kind,
        CASE
            WHEN b.shareholder_type = 'individual' AND p.person_id IS NOT NULL THEN p.person_id::text
            WHEN b.identifier_digits ~ '^[0-9]{{10}}$' THEN b.identifier_digits
            WHEN b.identifier_value IS NOT NULL THEN 'FOREIGN_REG:' || b.identifier_value
            ELSE 'unknown:' || substr(
                encode(
                    digest(
                        coalesce(search_normalize(b.name), lower(trim(b.name)), '') || '|',
                        'sha256'
                    ),
                    'hex'
                ),
                1,
                16
            )
        END AS parent_id,
        b.name AS parent_name_raw,
        CASE
            WHEN b.shareholder_type = 'individual' AND p.person_id IS NOT NULL THEN 'UUID'
            WHEN b.identifier_digits ~ '^[0-9]{{10}}$' THEN 'CBE'
            WHEN b.identifier_value IS NOT NULL THEN 'FOREIGN_REG'
            ELSE NULL
        END AS parent_identifier_scheme,
        CASE
            WHEN b.shareholder_type = 'individual' AND p.person_id IS NOT NULL THEN p.person_id::text
            WHEN b.identifier_digits ~ '^[0-9]{{10}}$' THEN b.identifier_digits
            WHEN b.identifier_value IS NOT NULL THEN b.identifier_value
            ELSE NULL
        END AS parent_identifier_value,
        CASE WHEN b.identifier_digits ~ '^[0-9]{{10}}$' THEN 'BE' ELSE NULL END AS parent_country,
        'company' AS child_kind,
        b.enterprise_number AS child_id,
        CASE
            WHEN b.ownership_pct IS NULL OR b.ownership_pct::text = 'NaN' THEN NULL
            ELSE round(greatest(0, least(100, b.ownership_pct))::numeric, 2)
        END AS pct,
        'shareholder' AS edge_kind,
        'shareholder' AS source_table,
        b.source_pk,
        0 AS source_action_seq,
        b.deposit_key AS source_filing,
        1 AS source_rank,
        b.fy AS fiscal_year,
        NULL::date AS deposit_date,
        CASE WHEN b.fy IS NOT NULL THEN make_date(b.fy, 1, 1) ELSE NULL END AS valid_from,
        CASE WHEN fy_next.next_fy IS NOT NULL THEN make_date(fy_next.next_fy, 1, 1) ELSE NULL END AS valid_to,
        1.0::real AS confidence
    FROM base b
    LEFT JOIN person_link pl
      ON pl.source_table = 'shareholder'
     AND pl.source_pk = b.source_pk
     AND pl.source_mention_seq = 0
    LEFT JOIN person p
      ON p.person_id = pl.person_id
     AND p.status = 'active'
    LEFT JOIN fy_next
      ON fy_next.enterprise_number = b.enterprise_number
     AND fy_next.fy = b.fy
),
upserted AS (
    INSERT INTO ownership_edge (
        parent_kind, parent_id, parent_name_raw, parent_identifier_scheme,
        parent_identifier_value, parent_country, child_kind, child_id, pct,
        edge_kind, source_table, source_pk, source_action_seq, source_filing,
        source_rank, fiscal_year, deposit_date, valid_from, valid_to,
        confidence
    )
    SELECT
        parent_kind, parent_id, parent_name_raw, parent_identifier_scheme,
        parent_identifier_value, parent_country, child_kind, child_id, pct,
        edge_kind, source_table, source_pk, source_action_seq, source_filing,
        source_rank, fiscal_year, deposit_date, valid_from, valid_to,
        confidence
    FROM source
    ON CONFLICT (source_table, source_pk, source_action_seq) DO UPDATE
    SET {UPSERT_SET}
    WHERE {UPSERT_DIFF}
    RETURNING 1
)
SELECT count(*) FROM upserted
"""


PARTICIPATING_SQL = f"""
WITH base AS (
    SELECT
        pi.enterprise_number,
        pi.deposit_key,
        pi.name,
        pi.identifier,
        pi.country,
        pi.ownership_pct,
        CASE
            WHEN pi.fiscal_year ~ '^[0-9]{{4}}$' THEN pi.fiscal_year::int
            ELSE NULL
        END AS fy,
        concat_ws('|', pi.enterprise_number, pi.deposit_key, pi.name) AS source_pk,
        regexp_replace(coalesce(pi.identifier, ''), '\\D', '', 'g') AS child_cbe
    FROM participating_interest_fact pi
    WHERE pi.enterprise_number ~ '^[0-9]{{10}}$'
      AND nullif(trim(pi.name), '') IS NOT NULL
),
fy_next AS (
    SELECT
        enterprise_number,
        fy,
        lead(fy) OVER (PARTITION BY enterprise_number ORDER BY fy) AS next_fy
    FROM (
        SELECT DISTINCT enterprise_number, fy
        FROM base
        WHERE fy IS NOT NULL
    ) years
),
source AS (
    SELECT
        'company' AS parent_kind,
        b.enterprise_number AS parent_id,
        parent_d.denomination AS parent_name_raw,
        'CBE' AS parent_identifier_scheme,
        b.enterprise_number AS parent_identifier_value,
        'BE' AS parent_country,
        'company' AS child_kind,
        b.child_cbe AS child_id,
        CASE
            WHEN b.ownership_pct IS NULL OR b.ownership_pct::text = 'NaN' THEN NULL
            ELSE round(greatest(0, least(100, b.ownership_pct))::numeric, 2)
        END AS pct,
        'participating' AS edge_kind,
        'participating_interest' AS source_table,
        b.source_pk,
        0 AS source_action_seq,
        b.deposit_key AS source_filing,
        2 AS source_rank,
        b.fy AS fiscal_year,
        NULL::date AS deposit_date,
        CASE WHEN b.fy IS NOT NULL THEN make_date(b.fy, 1, 1) ELSE NULL END AS valid_from,
        CASE WHEN fy_next.next_fy IS NOT NULL THEN make_date(fy_next.next_fy, 1, 1) ELSE NULL END AS valid_to,
        1.0::real AS confidence
    FROM base b
    LEFT JOIN LATERAL (
        SELECT d.denomination
        FROM denomination d
        WHERE d.entity_number = b.enterprise_number
          AND d.type_of_denomination = '001'
          AND d.language IN ('2', '1')
        ORDER BY CASE d.language WHEN '2' THEN 0 WHEN '1' THEN 1 ELSE 2 END
        LIMIT 1
    ) parent_d ON true
    LEFT JOIN fy_next
      ON fy_next.enterprise_number = b.enterprise_number
     AND fy_next.fy = b.fy
    WHERE b.child_cbe ~ '^[0-9]{{10}}$'
      AND b.child_cbe <> b.enterprise_number
),
upserted AS (
    INSERT INTO ownership_edge (
        parent_kind, parent_id, parent_name_raw, parent_identifier_scheme,
        parent_identifier_value, parent_country, child_kind, child_id, pct,
        edge_kind, source_table, source_pk, source_action_seq, source_filing,
        source_rank, fiscal_year, deposit_date, valid_from, valid_to,
        confidence
    )
    SELECT
        parent_kind, parent_id, parent_name_raw, parent_identifier_scheme,
        parent_identifier_value, parent_country, child_kind, child_id, pct,
        edge_kind, source_table, source_pk, source_action_seq, source_filing,
        source_rank, fiscal_year, deposit_date, valid_from, valid_to,
        confidence
    FROM source
    ON CONFLICT (source_table, source_pk, source_action_seq) DO UPDATE
    SET {UPSERT_SET}
    WHERE {UPSERT_DIFF}
    RETURNING 1
)
SELECT count(*) FROM upserted
"""


STAATSBLAD_SQL = f"""
WITH base AS (
    SELECT
        ev.id,
        ev.enterprise_number,
        ev.pub_reference,
        ev.pub_date,
        ev.event_type,
        ev.event_date,
        ev.person_name,
        ev.entity_name,
        coalesce(nullif(trim(ev.entity_name), ''), nullif(trim(ev.person_name), '')) AS parent_name
    FROM staatsblad_event ev
    WHERE ev.enterprise_number ~ '^[0-9]{{10}}$'
      AND ev.event_type IN ('capital_event', 'share_transfer', 'ownership_change', 'ma_event')
      AND coalesce(nullif(trim(ev.entity_name), ''), nullif(trim(ev.person_name), '')) IS NOT NULL
),
source AS (
    SELECT
        CASE
            WHEN b.person_name IS NOT NULL AND p.person_id IS NOT NULL THEN 'person'
            ELSE 'unknown'
        END AS parent_kind,
        CASE
            WHEN b.person_name IS NOT NULL AND p.person_id IS NOT NULL THEN p.person_id::text
            ELSE 'unknown:' || substr(
                encode(
                    digest(
                        coalesce(search_normalize(b.parent_name), lower(trim(b.parent_name)), '') || '|',
                        'sha256'
                    ),
                    'hex'
                ),
                1,
                16
            )
        END AS parent_id,
        b.parent_name AS parent_name_raw,
        CASE WHEN b.person_name IS NOT NULL AND p.person_id IS NOT NULL THEN 'UUID' ELSE NULL END AS parent_identifier_scheme,
        CASE WHEN b.person_name IS NOT NULL AND p.person_id IS NOT NULL THEN p.person_id::text ELSE NULL END AS parent_identifier_value,
        NULL::char(2) AS parent_country,
        'company' AS child_kind,
        b.enterprise_number AS child_id,
        NULL::numeric(5,2) AS pct,
        CASE b.event_type
            WHEN 'capital_event' THEN 'gazette_capital'
            WHEN 'share_transfer' THEN 'gazette_transfer'
            WHEN 'ownership_change' THEN 'gazette_ownership'
            WHEN 'ma_event' THEN 'gazette_ma'
        END AS edge_kind,
        'staatsblad_event' AS source_table,
        b.id::text AS source_pk,
        0 AS source_action_seq,
        b.pub_reference AS source_filing,
        CASE b.event_type
            WHEN 'share_transfer' THEN 3
            WHEN 'ownership_change' THEN 4
            WHEN 'ma_event' THEN 5
            WHEN 'capital_event' THEN 6
        END AS source_rank,
        NULL::int AS fiscal_year,
        b.pub_date AS deposit_date,
        coalesce(b.event_date, b.pub_date) AS valid_from,
        NULL::date AS valid_to,
        0.7::real AS confidence
    FROM base b
    LEFT JOIN person_link pl
      ON pl.source_table = 'staatsblad_event'
     AND pl.source_pk = b.id::text
     AND pl.source_mention_seq = 0
    LEFT JOIN person p
      ON p.person_id = pl.person_id
     AND p.status = 'active'
),
upserted AS (
    INSERT INTO ownership_edge (
        parent_kind, parent_id, parent_name_raw, parent_identifier_scheme,
        parent_identifier_value, parent_country, child_kind, child_id, pct,
        edge_kind, source_table, source_pk, source_action_seq, source_filing,
        source_rank, fiscal_year, deposit_date, valid_from, valid_to,
        confidence
    )
    SELECT
        parent_kind, parent_id, parent_name_raw, parent_identifier_scheme,
        parent_identifier_value, parent_country, child_kind, child_id, pct,
        edge_kind, source_table, source_pk, source_action_seq, source_filing,
        source_rank, fiscal_year, deposit_date, valid_from, valid_to,
        confidence
    FROM source
    ON CONFLICT (source_table, source_pk, source_action_seq) DO UPDATE
    SET {UPSERT_SET}
    WHERE {UPSERT_DIFF}
    RETURNING 1
)
SELECT count(*) FROM upserted
"""


VALIDATION_SQL = """
SELECT
    count(*) AS total_edges,
    count(*) FILTER (WHERE source_table = 'shareholder') AS shareholder_edges,
    count(*) FILTER (WHERE source_table = 'participating_interest') AS participating_edges,
    count(*) FILTER (WHERE source_table = 'staatsblad_event') AS staatsblad_edges,
    count(*) FILTER (WHERE parent_kind = 'external_org') AS external_org_edges,
    count(*) FILTER (WHERE parent_kind = 'unknown') AS unknown_edges,
    count(*) FILTER (WHERE parent_kind = 'person') AS person_edges
FROM ownership_edge
"""


def _run_count(cur, label: str, sql: str) -> int:
    LOG.info("running %s", label)
    cur.execute(sql)
    row = cur.fetchone()
    count = int(row[0] if row else 0)
    LOG.info("%s changed rows: %d", label, count)
    return count


def run(database_url: str) -> dict[str, int]:
    if not database_url:
        raise SystemExit("DATABASE_URL is not set")
    counts: dict[str, int] = {}
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SET lock_timeout = '5s'")
            cur.execute("SET statement_timeout = '30min'")
            counts["shareholder"] = _run_count(cur, "shareholder", SHAREHOLDER_SQL)
            counts["participating_interest"] = _run_count(cur, "participating_interest", PARTICIPATING_SQL)
            counts["staatsblad_event"] = _run_count(cur, "staatsblad_event", STAATSBLAD_SQL)
            cur.execute(VALIDATION_SQL)
            row = cur.fetchone()
            if row:
                keys = (
                    "total_edges",
                    "shareholder_edges",
                    "participating_edges",
                    "staatsblad_edges",
                    "external_org_edges",
                    "unknown_edges",
                    "person_edges",
                )
                counts.update({key: int(value or 0) for key, value in zip(keys, row)})
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate ownership_edge from historical governance sources.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    counts = run(args.database_url)
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
