#!/usr/bin/env python3
"""Build and score the Person v1 public-ramp golden set.

The unit of review is a pair of source mentions from person_link. Each pair
has an expected_same label and the resolver prediction is whether both source
mentions currently point at the same person_id.

The committed JSON intentionally stores link ids, source tables, confidence
bands, labels, and rationales, but not raw names or source_pk values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional outside dev shells
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv:
    # Do not parse developer .env files here; they may contain raw multiline
    # SSH keys. The evaluator is intended to run inside the backend container,
    # where DATABASE_URL is already present in the process environment.
    load_dotenv(ROOT / ".env.production")


PRECISION_FLOOR = 0.99
ALLOWED_DATABASE_ENV_NAMES = {"DATABASE_URL"}
INTERMEDIATE_ROW_KEYS = {
    "left_link_id",
    "right_link_id",
    "left_person_id",
    "right_person_id",
    "left_source_table",
    "right_source_table",
    "left_confidence",
    "right_confidence",
}
PUBLIC_RECORD_KEYS = {
    "stratum",
    "left_link_id",
    "right_link_id",
    "left_source_table",
    "right_source_table",
    "left_confidence",
    "right_confidence",
    "expected_same",
    "predicted_same",
    "rationale",
}
FORBIDDEN_RECORD_KEYS = {
    "name",
    "name_as_written",
    "canonical_name",
    "name_normalized",
    "source_pk",
    "left_person_id",
    "right_person_id",
    "enterprise_number",
}


@dataclass(frozen=True)
class Stratum:
    name: str
    expected_same: bool
    quota: int
    rationale: str
    sql: str


COMMON_BELGIAN_NAME_FILTER = """
(
    p.name_normalized ILIKE '%%janssens%%'
    OR p.name_normalized ILIKE '%%de smet%%'
    OR p.name_normalized ILIKE '%%peeters%%'
    OR p.name_normalized ILIKE '%%lambert%%'
    OR p.name_normalized ILIKE '%%maes%%'
    OR p.name_normalized ILIKE '%%jacobs%%'
    OR p.name_normalized ILIKE '%%willems%%'
    OR p.name_normalized ILIKE '%%mertens%%'
    OR p.name_normalized ILIKE '%%claes%%'
    OR p.name_normalized ILIKE '%%goossens%%'
)
"""


BASE_SELECT = """
SELECT
    l.id AS left_link_id,
    r.id AS right_link_id,
    l.person_id::text AS left_person_id,
    r.person_id::text AS right_person_id,
    l.source_table AS left_source_table,
    r.source_table AS right_source_table,
    round(l.confidence::numeric, 3)::float AS left_confidence,
    round(r.confidence::numeric, 3)::float AS right_confidence
"""


STRATA: list[Stratum] = [
    Stratum(
        name="common_belgian_surname_tier_a_positive",
        expected_same=True,
        quota=20,
        rationale=(
            "Positive pair: two Staatsblad structured-domicile mentions under "
            "the same Tier-A person for high-homonym Belgian surnames."
        ),
        sql=f"""
        WITH groups AS (
            SELECT pl.person_id, array_agg(pl.id ORDER BY pl.id) AS ids
            FROM person_link pl
            JOIN person p ON p.person_id = pl.person_id
            WHERE pl.source_table = 'staatsblad_event'
              AND pl.confidence >= 0.99
              AND {COMMON_BELGIAN_NAME_FILTER}
            GROUP BY pl.person_id
            HAVING count(*) >= 2
            ORDER BY md5(pl.person_id::text)
            LIMIT %(limit)s
        )
        {BASE_SELECT}
        FROM groups g
        JOIN person_link l ON l.id = g.ids[1]
        JOIN person_link r ON r.id = g.ids[2]
        """,
    ),
    Stratum(
        name="tier_a_structured_domicile_positive",
        expected_same=True,
        quota=80,
        rationale=(
            "Positive pair: two Staatsblad structured-domicile mentions under "
            "the same Tier-A person. This broad support stratum keeps the "
            "overall golden set near 500 rows when rarer homonym traps are scarce."
        ),
        sql=f"""
        WITH groups AS (
            SELECT pl.person_id, array_agg(pl.id ORDER BY pl.id) AS ids
            FROM person_link pl
            WHERE pl.source_table = 'staatsblad_event'
              AND pl.confidence >= 0.99
            GROUP BY pl.person_id
            HAVING count(*) >= 2
            ORDER BY md5(pl.person_id::text)
            LIMIT %(limit)s
        )
        {BASE_SELECT}
        FROM groups g
        JOIN person_link l ON l.id = g.ids[1]
        JOIN person_link r ON r.id = g.ids[2]
        """,
    ),
    Stratum(
        name="multilingual_accent_variant_positive",
        expected_same=True,
        quota=50,
        rationale=(
            "Positive pair: same Tier-A person with distinct raw spellings, "
            "covering accent/capitalization/name-variant normalization."
        ),
        sql=f"""
        {BASE_SELECT}
        FROM person_link l
        JOIN person_link r
          ON r.person_id = l.person_id
         AND r.id > l.id
         AND r.name_as_written IS DISTINCT FROM l.name_as_written
        WHERE l.source_table = 'staatsblad_event'
          AND r.source_table = 'staatsblad_event'
          AND l.confidence >= 0.99
          AND r.confidence >= 0.99
        ORDER BY md5(l.id::text || ':' || r.id::text)
        LIMIT %(limit)s
        """,
    ),
    Stratum(
        name="legal_representative_affiliation_positive",
        expected_same=True,
        quota=70,
        rationale=(
            "Positive pair: affiliation-row natural person folded into a "
            "Staatsblad/admin/shareholder person through the Tier-B co-occurrence anchor."
        ),
        sql=f"""
        {BASE_SELECT}
        FROM person_link l
        JOIN person_link r
          ON r.person_id = l.person_id
         AND r.id <> l.id
        WHERE l.source_table = 'affiliation'
          AND l.confidence >= 0.89
          AND l.confidence < 0.91
          AND r.source_table <> 'affiliation'
        ORDER BY md5(l.id::text || ':' || r.id::text)
        LIMIT %(limit)s
        """,
    ),
    Stratum(
        name="tier_b_admin_shareholder_cooccurrence_positive",
        expected_same=True,
        quota=70,
        rationale=(
            "Positive pair: administrator/shareholder row folded into a Tier-A "
            "Staatsblad person through exact normalized-name plus enterprise "
            "co-occurrence."
        ),
        sql=f"""
        {BASE_SELECT}
        FROM person_link l
        JOIN person_link r
          ON r.person_id = l.person_id
         AND r.id <> l.id
        WHERE l.source_table IN ('administrator', 'shareholder')
          AND l.confidence >= 0.89
          AND l.confidence < 0.91
          AND r.source_table = 'staatsblad_event'
          AND r.confidence >= 0.99
        ORDER BY md5(l.id::text || ':' || r.id::text)
        LIMIT %(limit)s
        """,
    ),
    Stratum(
        name="foreign_or_no_domicile_repeat_positive",
        expected_same=True,
        quota=80,
        rationale=(
            "Positive pair: repeated administrator mention for the same normalized "
            "name and enterprise without a Tier-A domicile anchor. v1 often leaves "
            "these as Tier-C singletons, so this stratum measures recall loss."
        ),
        sql=f"""
        WITH residual_admin AS (
            SELECT pl.id, pl.person_id, pl.enterprise_number, p.name_normalized
            FROM person_link pl
            JOIN person p ON p.person_id = pl.person_id
            WHERE pl.source_table = 'administrator'
              AND pl.confidence >= 0.49
              AND pl.confidence < 0.51
              AND pl.enterprise_number IS NOT NULL
              AND p.name_normalized IS NOT NULL
        ),
        pairs AS (
            SELECT a.id AS left_id, b.id AS right_id
            FROM residual_admin a
            JOIN residual_admin b
              ON b.enterprise_number = a.enterprise_number
             AND b.name_normalized = a.name_normalized
             AND b.id > a.id
             AND b.person_id <> a.person_id
            ORDER BY md5(a.id::text || ':' || b.id::text)
            LIMIT %(limit)s
        )
        {BASE_SELECT}
        FROM pairs p
        JOIN person_link l ON l.id = p.left_id
        JOIN person_link r ON r.id = p.right_id
        """,
    ),
    Stratum(
        name="same_city_homonym_negative",
        expected_same=False,
        quota=20,
        rationale=(
            "Negative pair: same normalized name and city, but different Tier-A "
            "postcode anchors. These are the public false-merge traps."
        ),
        sql=f"""
        WITH anchors AS (
            SELECT pl.id, pl.person_id, p.name_normalized, p.primary_city, p.primary_postcode
            FROM person_link pl
            JOIN person p ON p.person_id = pl.person_id
            WHERE pl.source_table = 'staatsblad_event'
              AND pl.confidence >= 0.99
              AND p.primary_city IS NOT NULL
              AND p.primary_postcode IS NOT NULL
        ),
        pairs AS (
            SELECT a.id AS left_id, b.id AS right_id
            FROM anchors a
            JOIN anchors b
              ON b.name_normalized = a.name_normalized
             AND b.primary_city = a.primary_city
             AND b.primary_postcode <> a.primary_postcode
             AND b.person_id <> a.person_id
             AND b.id > a.id
            ORDER BY md5(a.id::text || ':' || b.id::text)
            LIMIT %(limit)s
        )
        {BASE_SELECT}
        FROM pairs p
        JOIN person_link l ON l.id = p.left_id
        JOIN person_link r ON r.id = p.right_id
        """,
    ),
    Stratum(
        name="ambiguous_same_enterprise_negative",
        expected_same=False,
        quota=70,
        rationale=(
            "Negative pair: same normalized name and enterprise has multiple "
            "Tier-A anchors; the resolver must not fold the ambiguous admin row "
            "into one person."
        ),
        sql=f"""
        WITH anchors AS (
            SELECT pl.id, pl.person_id, pl.enterprise_number, p.name_normalized
            FROM person_link pl
            JOIN person p ON p.person_id = pl.person_id
            WHERE pl.source_table = 'staatsblad_event'
              AND pl.confidence >= 0.99
              AND pl.enterprise_number IS NOT NULL
        ),
        pairs AS (
            SELECT a.id AS left_id, b.id AS right_id
            FROM anchors a
            JOIN anchors b
              ON b.name_normalized = a.name_normalized
             AND b.enterprise_number = a.enterprise_number
             AND b.person_id <> a.person_id
             AND b.id > a.id
            ORDER BY md5(a.id::text || ':' || b.id::text)
            LIMIT %(limit)s
        )
        {BASE_SELECT}
        FROM pairs p
        JOIN person_link l ON l.id = p.left_id
        JOIN person_link r ON r.id = p.right_id
        """,
    ),
    Stratum(
        name="false_merge_trap_same_name_different_anchor_negative",
        expected_same=False,
        quota=30,
        rationale=(
            "Negative pair: common-name Tier-A anchors with different cities or "
            "postcodes. This simulates known false-merge regression traps when "
            "only the name matches."
        ),
        sql=f"""
        WITH anchors AS (
            SELECT pl.id, pl.person_id, p.name_normalized, p.primary_city, p.primary_postcode
            FROM person_link pl
            JOIN person p ON p.person_id = pl.person_id
            WHERE pl.source_table = 'staatsblad_event'
              AND pl.confidence >= 0.99
              AND p.primary_city IS NOT NULL
              AND p.primary_postcode IS NOT NULL
              AND {COMMON_BELGIAN_NAME_FILTER}
        ),
        pairs AS (
            SELECT a.id AS left_id, b.id AS right_id
            FROM anchors a
            JOIN anchors b
              ON b.name_normalized = a.name_normalized
             AND (
                    b.primary_city <> a.primary_city
                 OR b.primary_postcode <> a.primary_postcode
             )
             AND b.person_id <> a.person_id
             AND b.id > a.id
            ORDER BY md5(a.id::text || ':' || b.id::text)
            LIMIT %(limit)s
        )
        {BASE_SELECT}
        FROM pairs p
        JOIN person_link l ON l.id = p.left_id
        JOIN person_link r ON r.id = p.right_id
        """,
    ),
    Stratum(
        name="same_name_different_anchor_negative",
        expected_same=False,
        quota=60,
        rationale=(
            "Negative pair: same normalized name with different Tier-A city or "
            "postcode anchors. This broad support stratum expands false-merge "
            "coverage beyond the common-surname subset."
        ),
        sql=f"""
        WITH anchors AS (
            SELECT pl.id, pl.person_id, p.name_normalized, p.primary_city, p.primary_postcode
            FROM person_link pl
            JOIN person p ON p.person_id = pl.person_id
            WHERE pl.source_table = 'staatsblad_event'
              AND pl.confidence >= 0.99
              AND p.primary_city IS NOT NULL
              AND p.primary_postcode IS NOT NULL
        ),
        pairs AS (
            SELECT a.id AS left_id, b.id AS right_id
            FROM anchors a
            JOIN anchors b
              ON b.name_normalized = a.name_normalized
             AND (
                    b.primary_city <> a.primary_city
                 OR b.primary_postcode <> a.primary_postcode
             )
             AND b.person_id <> a.person_id
             AND b.id > a.id
            ORDER BY md5(a.id::text || ':' || b.id::text)
            LIMIT %(limit)s
        )
        {BASE_SELECT}
        FROM pairs p
        JOIN person_link l ON l.id = p.left_id
        JOIN person_link r ON r.id = p.right_id
        """,
    ),
]


def _get_dsn(env_name: str) -> str:
    if env_name not in ALLOWED_DATABASE_ENV_NAMES:
        allowed = ", ".join(sorted(ALLOWED_DATABASE_ENV_NAMES))
        raise SystemExit(f"{env_name} is not an allowed database env name; use one of: {allowed}")
    dsn = os.getenv(env_name, "").strip()
    if not dsn:
        raise SystemExit(f"{env_name} is not configured")
    return dsn


def _fetch_records(conn: psycopg2.extensions.connection, stratum: Stratum) -> list[dict[str, Any]]:
    # Pull extra rows to compensate for duplicate pairs across strata.
    limit = max(stratum.quota * 4, stratum.quota + 25)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(stratum.sql, {"limit": limit})
        rows = [dict(row) for row in cur.fetchall()]
    sanitized_rows: list[dict[str, Any]] = []
    for row in rows:
        # Queries intentionally select only ids/source/confidence/person_id.
        # Keep this allowlist here so future query edits cannot accidentally
        # carry raw names, source_pk values, or enterprise numbers into the
        # committed artifact.
        unexpected = set(row) - INTERMEDIATE_ROW_KEYS
        if unexpected:
            raise RuntimeError(f"unexpected raw columns in golden-set query: {sorted(unexpected)}")
        row = {key: row[key] for key in INTERMEDIATE_ROW_KEYS}
        row["stratum"] = stratum.name
        row["expected_same"] = stratum.expected_same
        row["predicted_same"] = row["left_person_id"] == row["right_person_id"]
        row["rationale"] = stratum.rationale
        sanitized_rows.append(row)
    return sanitized_rows


def build_golden_set(conn: psycopg2.extensions.connection) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int]] = set()
    strata_counts: dict[str, int] = {}
    strata_shortfalls: dict[str, int] = {}

    for stratum in STRATA:
        added = 0
        for row in _fetch_records(conn, stratum):
            left = int(row["left_link_id"])
            right = int(row["right_link_id"])
            pair = (min(left, right), max(left, right))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            records.append(row)
            added += 1
            if added >= stratum.quota:
                break
        strata_counts[stratum.name] = added
        if added < stratum.quota:
            strata_shortfalls[stratum.name] = stratum.quota - added

    metrics = score(records)
    metrics["strata_counts"] = strata_counts
    metrics["strata_shortfalls"] = strata_shortfalls
    metrics["target_size"] = sum(s.quota for s in STRATA)
    return records, metrics


def score(records: list[dict[str, Any]]) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    by_stratum: dict[str, dict[str, int]] = {}
    for row in records:
        expected = bool(row["expected_same"])
        predicted = bool(row["predicted_same"])
        bucket = by_stratum.setdefault(
            row["stratum"], {"count": 0, "tp": 0, "fp": 0, "tn": 0, "fn": 0}
        )
        bucket["count"] += 1
        if expected and predicted:
            tp += 1
            bucket["tp"] += 1
        elif not expected and predicted:
            fp += 1
            bucket["fp"] += 1
        elif not expected and not predicted:
            tn += 1
            bucket["tn"] += 1
        else:
            fn += 1
            bucket["fn"] += 1

    precision_den = tp + fp
    recall_den = tp + fn
    precision = tp / precision_den if precision_den else 1.0
    recall = tp / recall_den if recall_den else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "record_count": len(records),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "precision_floor": PRECISION_FLOOR,
        "precision_floor_met": precision >= PRECISION_FLOOR,
        "by_stratum": by_stratum,
    }


def public_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "stratum": row["stratum"],
        "left_link_id": int(row["left_link_id"]),
        "right_link_id": int(row["right_link_id"]),
        "left_source_table": row["left_source_table"],
        "right_source_table": row["right_source_table"],
        "left_confidence": row["left_confidence"],
        "right_confidence": row["right_confidence"],
        "expected_same": bool(row["expected_same"]),
        "predicted_same": bool(row["predicted_same"]),
        "rationale": row["rationale"],
    }


def validate_public_payload(payload: dict[str, Any]) -> None:
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError("payload.records must be a list")
    for idx, record in enumerate(records):
        keys = set(record)
        if keys != PUBLIC_RECORD_KEYS:
            raise RuntimeError(
                f"record {idx} has unexpected schema: missing={sorted(PUBLIC_RECORD_KEYS - keys)} "
                f"extra={sorted(keys - PUBLIC_RECORD_KEYS)}"
            )
        forbidden = keys & FORBIDDEN_RECORD_KEYS
        if forbidden:
            raise RuntimeError(f"record {idx} contains forbidden raw-data keys: {sorted(forbidden)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-artifact", type=Path)
    args = parser.parse_args()

    if args.validate_artifact:
        payload = json.loads(args.validate_artifact.read_text(encoding="utf-8"))
        validate_public_payload(payload)
        print(f"{len(payload['records'])} records schema-clean")
        return 0

    if not args.output:
        raise SystemExit("--output is required unless --validate-artifact is used")

    try:
        conn = psycopg2.connect(
            _get_dsn(args.database_url_env),
            connect_timeout=10,
            application_name="datasnoop:person_golden_set_eval",
        )
    except psycopg2.OperationalError:
        raise SystemExit("database connection failed; DSN details redacted")
    try:
        records, metrics = build_golden_set(conn)
    finally:
        conn.close()

    if not metrics["precision_floor_met"]:
        raise RuntimeError("precision floor not met; refusing to write launch artifact")

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "production person_link/person tables",
        "record_privacy": "link ids and labels only; raw names/source_pk omitted",
        "metrics": metrics,
        "records": [public_record(row) for row in records],
    }
    # Required privacy guard: validate the public schema before any file write.
    validate_public_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0 if metrics["precision_floor_met"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
