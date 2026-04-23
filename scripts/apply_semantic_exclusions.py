"""Apply semantic-corpus exclusions for operator-defined legal forms.

Usage:

  python scripts/apply_semantic_exclusions.py
  python scripts/apply_semantic_exclusions.py --apply

Dry-run prints the impacted queue rows plus already-created semantic
artifacts. `--apply` then:
  1. marks matching enrichment jobs as `excluded`
  2. clears bulk semantic fields from `company_enrichment`
  3. deletes matching `company_embedding` rows

The excluded forms are defined centrally in `backend/enrichment_routing.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

for env_path in (ROOT / ".env", ROOT / ".env.production"):
    if env_path.exists():
        load_dotenv(env_path)
        break

from db import fetch_all, fetch_one, transaction  # noqa: E402
from enrichment_queue import ensure_schema as ensure_queue_schema  # noqa: E402
from enrichment_routing import EXCLUDED_JURIDICAL_FORMS  # noqa: E402
from semantic_bootstrap import ensure_semantic_schema  # noqa: E402


def _forms_array() -> list[str]:
    return sorted(EXCLUDED_JURIDICAL_FORMS)


def _queue_counts() -> list[dict]:
    return fetch_all(
        """
        SELECT
            j.status,
            e.juridical_form,
            COALESCE(code.description, e.juridical_form) AS juridical_form_label,
            COUNT(*)::int AS n
          FROM enrichment_job j
          JOIN enterprise e
            ON e.enterprise_number = j.enterprise_number
     LEFT JOIN code
            ON code.category = 'JuridicalForm'
           AND code.language = 'NL'
           AND code.code = e.juridical_form
         WHERE TRIM(COALESCE(e.juridical_form, '')) = ANY(%s)
      GROUP BY j.status, e.juridical_form, juridical_form_label
      ORDER BY n DESC, j.status, e.juridical_form
        """,
        (_forms_array(),),
    )


def _artifact_counts() -> dict:
    row = fetch_one(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE ce.bulk_summary IS NOT NULL
            )::int AS bulk_rows,
            COUNT(*) FILTER (
                WHERE emb.enterprise_number IS NOT NULL
            )::int AS embedding_rows
          FROM enterprise e
     LEFT JOIN company_enrichment ce
            ON ce.enterprise_number = e.enterprise_number
     LEFT JOIN company_embedding emb
            ON emb.enterprise_number = e.enterprise_number
         WHERE TRIM(COALESCE(e.juridical_form, '')) = ANY(%s)
        """,
        (_forms_array(),),
    )
    return row or {"bulk_rows": 0, "embedding_rows": 0}


def _print_summary() -> None:
    rows = _queue_counts()
    artifacts = _artifact_counts()
    total_jobs = sum(int(r["n"] or 0) for r in rows)
    print(
        "excluded_forms=%s queue_rows=%s bulk_rows=%s embedding_rows=%s"
        % (
            ",".join(_forms_array()),
            total_jobs,
            int(artifacts.get("bulk_rows", 0) or 0),
            int(artifacts.get("embedding_rows", 0) or 0),
        )
    )
    for row in rows:
        print(
            "  status=%s form=%s label=%s count=%s"
            % (
                row["status"],
                row["juridical_form"],
                row["juridical_form_label"],
                row["n"],
            )
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply",
        action="store_true",
        help="persist the exclusions and purge existing semantic artifacts",
    )
    args = ap.parse_args()

    ensure_queue_schema()
    ensure_semantic_schema()
    _print_summary()

    if not args.apply:
        print("dry-run only; rerun with --apply to persist semantic exclusions")
        return 0

    with transaction() as (_conn, cur):
        cur.execute(
            """
            UPDATE enrichment_job j
               SET status = 'excluded',
                   priority = 0,
                   attempts = 0,
                   claimed_at = NULL,
                   finished_at = COALESCE(j.finished_at, NOW()),
                   last_error = NULL
              FROM enterprise e
             WHERE e.enterprise_number = j.enterprise_number
               AND TRIM(COALESCE(e.juridical_form, '')) = ANY(%s)
               AND j.status IS DISTINCT FROM 'excluded'
            """,
            (_forms_array(),),
        )
        excluded_jobs = cur.rowcount

        cur.execute(
            """
            UPDATE company_enrichment ce
               SET bulk_summary = NULL,
                   bulk_summary_at = NULL,
                   bulk_website_hash = NULL,
                   bulk_website_url = NULL,
                   bulk_confidence = NULL
              FROM enterprise e
             WHERE e.enterprise_number = ce.enterprise_number
               AND TRIM(COALESCE(e.juridical_form, '')) = ANY(%s)
               AND (
                    ce.bulk_summary IS NOT NULL
                 OR ce.bulk_summary_at IS NOT NULL
                 OR ce.bulk_website_hash IS NOT NULL
                 OR ce.bulk_website_url IS NOT NULL
                 OR ce.bulk_confidence IS NOT NULL
               )
            """,
            (_forms_array(),),
        )
        cleared_bulk_rows = cur.rowcount

        cur.execute(
            """
            DELETE FROM company_embedding emb
             USING enterprise e
             WHERE e.enterprise_number = emb.enterprise_number
               AND TRIM(COALESCE(e.juridical_form, '')) = ANY(%s)
            """,
            (_forms_array(),),
        )
        deleted_embeddings = cur.rowcount

    print(
        "updated queue_rows=%s cleared_bulk_rows=%s deleted_embeddings=%s"
        % (excluded_jobs, cleared_bulk_rows, deleted_embeddings)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
