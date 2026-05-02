#!/usr/bin/env python3
"""Deterministic Person v1 resolver.

Internal-only v1 links every natural-person source row into person/person_link
using three tiers:
  A. Staatsblad structured domicile anchors.
  B. Same normalized name plus common enterprise_number with a Tier-A anchor.
  C. Residual singleton per source row.

Existing person_link rows are never reassigned silently.
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
except Exception:  # pragma: no cover - optional in container/runtime contexts
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.production")


DATABASE_URL = os.getenv("DATABASE_URL", "")
CLUSTER_VERSION = "person_v1_2026_05_02"
UUID_NAMESPACE = "datasnoop:person:v1:"

LOG = logging.getLogger("person_resolver")


def _run_count(cur, label: str, sql: str, params: dict[str, str]) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    count = int(row[0] if row else 0)
    LOG.info("%s: %d", label, count)
    return count


TIER_A_PERSON_SQL = """
WITH source AS (
    SELECT
        md5(%(uuid_ns)s || 'A|' || person_name_normalized || '|' ||
            upper(trim(person_domicile_postcode)) || '|' ||
            coalesce(search_normalize(person_domicile_city), lower(trim(person_domicile_city))))::uuid AS person_id,
        min(trim(person_name)) AS canonical_name,
        min(nullif(trim(person_domicile_city), '')) AS primary_city,
        min(nullif(trim(person_domicile_postcode), '')) AS primary_postcode,
        count(DISTINCT enterprise_number)::int AS role_count,
        min(coalesce(event_date, pub_date)) AS first_seen_date,
        max(coalesce(event_date, pub_date)) AS last_seen_date
    FROM staatsblad_event
    WHERE event_type = 'admin_event'
      AND person_name IS NOT NULL
      AND person_name_normalized IS NOT NULL
      AND nullif(trim(person_domicile_city), '') IS NOT NULL
      AND nullif(trim(person_domicile_postcode), '') IS NOT NULL
    GROUP BY person_name_normalized,
             upper(trim(person_domicile_postcode)),
             coalesce(search_normalize(person_domicile_city), lower(trim(person_domicile_city)))
),
upserted AS (
    INSERT INTO person (
        person_id, canonical_name, primary_city, primary_postcode,
        role_count, first_seen_date, last_seen_date, cluster_version
    )
    SELECT
        person_id, canonical_name, primary_city, primary_postcode,
        role_count, first_seen_date, last_seen_date, %(cluster_version)s
    FROM source
    ON CONFLICT (person_id) DO UPDATE
    SET canonical_name = EXCLUDED.canonical_name,
        primary_city = COALESCE(person.primary_city, EXCLUDED.primary_city),
        primary_postcode = COALESCE(person.primary_postcode, EXCLUDED.primary_postcode),
        role_count = GREATEST(person.role_count, EXCLUDED.role_count),
        first_seen_date = LEAST(person.first_seen_date, EXCLUDED.first_seen_date),
        last_seen_date = GREATEST(person.last_seen_date, EXCLUDED.last_seen_date),
        cluster_version = EXCLUDED.cluster_version
    WHERE person.status = 'active'
    RETURNING 1
)
SELECT count(*) FROM upserted
"""


TIER_A_LINK_SQL = """
WITH source AS (
    SELECT
        md5(%(uuid_ns)s || 'A|' || person_name_normalized || '|' ||
            upper(trim(person_domicile_postcode)) || '|' ||
            coalesce(search_normalize(person_domicile_city), lower(trim(person_domicile_city))))::uuid AS person_id,
        id::text AS source_pk,
        enterprise_number,
        trim(person_name) AS name_as_written
    FROM staatsblad_event
    WHERE event_type = 'admin_event'
      AND person_name IS NOT NULL
      AND person_name_normalized IS NOT NULL
      AND nullif(trim(person_domicile_city), '') IS NOT NULL
      AND nullif(trim(person_domicile_postcode), '') IS NOT NULL
),
inserted AS (
    INSERT INTO person_link (
        person_id, source_table, source_pk, source_mention_seq, source_field,
        enterprise_number, name_as_written, link_kind, confidence,
        confirmed_by_human, cluster_version
    )
    SELECT
        person_id, 'staatsblad_event', source_pk, 0, 'person_name',
        enterprise_number, name_as_written, 'deterministic', 1.0,
        false, %(cluster_version)s
    FROM source
    ON CONFLICT (source_table, source_pk, source_mention_seq) DO NOTHING
    RETURNING 1
)
SELECT count(*) FROM inserted
"""


TIER_B_LINK_SQL = """
WITH tier_a_anchor AS (
    SELECT p.name_normalized, pl.enterprise_number, min(pl.person_id::text)::uuid AS person_id
    FROM person_link pl
    JOIN person p ON p.person_id = pl.person_id
    WHERE pl.source_table = 'staatsblad_event'
      AND pl.confidence = 1.0
      AND pl.enterprise_number IS NOT NULL
      AND p.status = 'active'
    GROUP BY p.name_normalized, pl.enterprise_number
    HAVING count(DISTINCT pl.person_id) = 1
),
source AS (
    SELECT
        a.person_id,
        'administrator' AS source_table,
        concat_ws('|', adm.enterprise_number, adm.deposit_key, adm.name, adm.role) AS source_pk,
        'person_name' AS source_field,
        adm.enterprise_number,
        adm.name AS name_as_written
    FROM administrator adm
    JOIN tier_a_anchor a
      ON a.name_normalized = adm.name_normalized
     AND a.enterprise_number = adm.enterprise_number
    WHERE adm.person_type = 'natural'
      AND adm.name_normalized IS NOT NULL
      AND adm.name IS NOT NULL

    UNION ALL

    SELECT
        a.person_id,
        'shareholder',
        concat_ws('|', sh.enterprise_number, sh.deposit_key, sh.name),
        'name',
        sh.enterprise_number,
        sh.name
    FROM shareholder sh
    JOIN tier_a_anchor a
      ON a.name_normalized = sh.name_normalized
     AND a.enterprise_number = sh.enterprise_number
    WHERE sh.shareholder_type = 'individual'
      AND sh.name_normalized IS NOT NULL
      AND sh.name IS NOT NULL

    UNION ALL

    SELECT
        a.person_id,
        'affiliation',
        concat_ws('|', af.person_name, af.enterprise_number, af.via_enterprise_number, af.affiliation_type),
        'person_name',
        af.enterprise_number,
        af.person_name
    FROM affiliation af
    JOIN tier_a_anchor a
      ON a.name_normalized = af.name_normalized
     AND a.enterprise_number = af.enterprise_number
    WHERE af.name_normalized IS NOT NULL
      AND af.person_name IS NOT NULL
),
inserted AS (
    INSERT INTO person_link (
        person_id, source_table, source_pk, source_mention_seq, source_field,
        enterprise_number, name_as_written, link_kind, confidence,
        confirmed_by_human, cluster_version
    )
    SELECT
        person_id, source_table, source_pk, 0, source_field, enterprise_number,
        name_as_written, 'deterministic', 0.9, false, %(cluster_version)s
    FROM source
    ON CONFLICT (source_table, source_pk, source_mention_seq) DO NOTHING
    RETURNING 1
)
SELECT count(*) FROM inserted
"""


TIER_C_SQL_BY_SOURCE = {
    "staatsblad_event": """
WITH source AS (
    SELECT DISTINCT
        md5(%(uuid_ns)s || 'C|staatsblad_event|' || e.id::text)::uuid AS person_id,
        e.id::text AS source_pk,
        e.enterprise_number,
        trim(e.person_name) AS canonical_name,
        coalesce(e.event_date, e.pub_date) AS seen_date
    FROM staatsblad_event e
    WHERE e.event_type = 'admin_event'
      AND e.person_name IS NOT NULL
      AND nullif(trim(e.person_name), '') IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM person_link pl
          WHERE pl.source_table = 'staatsblad_event'
            AND pl.source_pk = e.id::text
            AND pl.source_mention_seq = 0
      )
),
people AS (
    INSERT INTO person (
        person_id, canonical_name, role_count, first_seen_date,
        last_seen_date, cluster_version
    )
    SELECT person_id, canonical_name, 1, seen_date, seen_date, %(cluster_version)s
    FROM source
    ON CONFLICT (person_id) DO UPDATE
    SET canonical_name = EXCLUDED.canonical_name,
        cluster_version = EXCLUDED.cluster_version
    WHERE person.status = 'active'
    RETURNING 1
),
links AS (
    INSERT INTO person_link (
        person_id, source_table, source_pk, source_mention_seq, source_field,
        enterprise_number, name_as_written, link_kind, confidence,
        confirmed_by_human, cluster_version
    )
    SELECT
        person_id, 'staatsblad_event', source_pk, 0, 'person_name',
        enterprise_number, canonical_name, 'deterministic', 0.5,
        false, %(cluster_version)s
    FROM source
    ON CONFLICT (source_table, source_pk, source_mention_seq) DO NOTHING
    RETURNING 1
)
SELECT count(*) FROM links
""",
    "administrator": """
WITH source AS (
    SELECT DISTINCT
        md5(%(uuid_ns)s || 'C|administrator|' ||
            concat_ws('|', enterprise_number, deposit_key, name, role))::uuid AS person_id,
        concat_ws('|', enterprise_number, deposit_key, name, role) AS source_pk,
        enterprise_number,
        trim(name) AS canonical_name
    FROM administrator
    WHERE person_type = 'natural'
      AND name IS NOT NULL
      AND nullif(trim(name), '') IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM person_link pl
          WHERE pl.source_table = 'administrator'
            AND pl.source_pk = concat_ws('|', administrator.enterprise_number, administrator.deposit_key, administrator.name, administrator.role)
            AND pl.source_mention_seq = 0
      )
),
people AS (
    INSERT INTO person (person_id, canonical_name, role_count, cluster_version)
    SELECT person_id, canonical_name, 1, %(cluster_version)s
    FROM source
    ON CONFLICT (person_id) DO UPDATE
    SET canonical_name = EXCLUDED.canonical_name,
        cluster_version = EXCLUDED.cluster_version
    WHERE person.status = 'active'
    RETURNING 1
),
links AS (
    INSERT INTO person_link (
        person_id, source_table, source_pk, source_mention_seq, source_field,
        enterprise_number, name_as_written, link_kind, confidence,
        confirmed_by_human, cluster_version
    )
    SELECT
        person_id, 'administrator', source_pk, 0, 'person_name',
        enterprise_number, canonical_name, 'deterministic', 0.5,
        false, %(cluster_version)s
    FROM source
    ON CONFLICT (source_table, source_pk, source_mention_seq) DO NOTHING
    RETURNING 1
)
SELECT count(*) FROM links
""",
    "shareholder": """
WITH source AS (
    SELECT DISTINCT
        md5(%(uuid_ns)s || 'C|shareholder|' ||
            concat_ws('|', enterprise_number, deposit_key, name))::uuid AS person_id,
        concat_ws('|', enterprise_number, deposit_key, name) AS source_pk,
        enterprise_number,
        trim(name) AS canonical_name
    FROM shareholder
    WHERE shareholder_type = 'individual'
      AND name IS NOT NULL
      AND nullif(trim(name), '') IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM person_link pl
          WHERE pl.source_table = 'shareholder'
            AND pl.source_pk = concat_ws('|', shareholder.enterprise_number, shareholder.deposit_key, shareholder.name)
            AND pl.source_mention_seq = 0
      )
),
people AS (
    INSERT INTO person (person_id, canonical_name, role_count, cluster_version)
    SELECT person_id, canonical_name, 1, %(cluster_version)s
    FROM source
    ON CONFLICT (person_id) DO UPDATE
    SET canonical_name = EXCLUDED.canonical_name,
        cluster_version = EXCLUDED.cluster_version
    WHERE person.status = 'active'
    RETURNING 1
),
links AS (
    INSERT INTO person_link (
        person_id, source_table, source_pk, source_mention_seq, source_field,
        enterprise_number, name_as_written, link_kind, confidence,
        confirmed_by_human, cluster_version
    )
    SELECT
        person_id, 'shareholder', source_pk, 0, 'name',
        enterprise_number, canonical_name, 'deterministic', 0.5,
        false, %(cluster_version)s
    FROM source
    ON CONFLICT (source_table, source_pk, source_mention_seq) DO NOTHING
    RETURNING 1
)
SELECT count(*) FROM links
""",
    "affiliation": """
WITH source AS (
    SELECT DISTINCT
        md5(%(uuid_ns)s || 'C|affiliation|' ||
            concat_ws('|', person_name, enterprise_number, via_enterprise_number, affiliation_type))::uuid AS person_id,
        concat_ws('|', person_name, enterprise_number, via_enterprise_number, affiliation_type) AS source_pk,
        enterprise_number,
        trim(person_name) AS canonical_name,
        first_seen_at::date AS first_seen_date,
        last_seen_at::date AS last_seen_date
    FROM affiliation
    WHERE person_name IS NOT NULL
      AND nullif(trim(person_name), '') IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM person_link pl
          WHERE pl.source_table = 'affiliation'
            AND pl.source_pk = concat_ws('|', affiliation.person_name, affiliation.enterprise_number, affiliation.via_enterprise_number, affiliation.affiliation_type)
            AND pl.source_mention_seq = 0
      )
),
people AS (
    INSERT INTO person (
        person_id, canonical_name, role_count, first_seen_date,
        last_seen_date, cluster_version
    )
    SELECT person_id, canonical_name, 1, first_seen_date, last_seen_date, %(cluster_version)s
    FROM source
    ON CONFLICT (person_id) DO UPDATE
    SET canonical_name = EXCLUDED.canonical_name,
        cluster_version = EXCLUDED.cluster_version
    WHERE person.status = 'active'
    RETURNING 1
),
links AS (
    INSERT INTO person_link (
        person_id, source_table, source_pk, source_mention_seq, source_field,
        enterprise_number, name_as_written, link_kind, confidence,
        confirmed_by_human, cluster_version
    )
    SELECT
        person_id, 'affiliation', source_pk, 0, 'person_name',
        enterprise_number, canonical_name, 'deterministic', 0.5,
        false, %(cluster_version)s
    FROM source
    ON CONFLICT (source_table, source_pk, source_mention_seq) DO NOTHING
    RETURNING 1
)
SELECT count(*) FROM links
""",
}


ROLE_COUNT_SQL = """
WITH counts AS (
    SELECT
        person_id,
        count(*)::int AS role_count,
        min(enterprise_number) FILTER (WHERE enterprise_number IS NOT NULL) AS any_enterprise
    FROM person_link
    GROUP BY person_id
),
updated AS (
    UPDATE person p
    SET role_count = counts.role_count,
        cluster_version = %(cluster_version)s
    FROM counts
    WHERE p.person_id = counts.person_id
      AND p.status = 'active'
      AND (
          p.role_count IS DISTINCT FROM counts.role_count
          OR p.cluster_version IS DISTINCT FROM %(cluster_version)s
      )
    RETURNING 1
)
SELECT count(*) FROM updated
"""


def run(incremental: bool = True) -> dict[str, int]:
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL not configured")

    params = {"uuid_ns": UUID_NAMESPACE, "cluster_version": CLUSTER_VERSION}
    results: dict[str, int] = {}
    conn = psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10,
        application_name="datasnoop:person_resolver",
    )
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '30min'")
                results["tier_a_persons"] = _run_count(
                    cur, "tier_a_persons", TIER_A_PERSON_SQL, params
                )
                results["tier_a_links"] = _run_count(
                    cur, "tier_a_links", TIER_A_LINK_SQL, params
                )
                results["tier_b_links"] = _run_count(
                    cur, "tier_b_links", TIER_B_LINK_SQL, params
                )
                for source_name, sql in TIER_C_SQL_BY_SOURCE.items():
                    results[f"tier_c_{source_name}_links"] = _run_count(
                        cur, f"tier_c_{source_name}_links", sql, params
                    )
                results["role_counts_updated"] = _run_count(
                    cur, "role_counts_updated", ROLE_COUNT_SQL, params
                )
                cur.execute("ANALYZE person")
                cur.execute("ANALYZE person_link")
        LOG.info("person resolver complete mode=%s", "incremental" if incremental else "full")
        return results
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Person v1 deterministic resolver")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Accepted for the nightly cron; v1 runs idempotent set-based inserts.",
    )
    args = parser.parse_args()
    run(incremental=args.incremental)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    raise SystemExit(main())
