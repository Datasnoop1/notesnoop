"""NBB nightly backload — fills the coverage gap during quiet hours.

Iterates companies that don't have a given fiscal year in financial_latest,
calls NBB's per-company /authentic/legalEntity/{cbe}/references + filing
endpoints, and loads anything new into financial_data.

Reverse-chronological by fiscal year — first finishes FY2026, then FY2025,
FY2024, FY2023, FY2022. Within a year, orders by size (largest KBO-
registered companies first) so we maximise impact per API call.

Designed to run via cron at 02:00 nightly for a bounded number of calls:
    0 2 * * * cd /opt/leadpeek && docker exec leadpeek-backend-1 \
        timeout 4h python /app/scripts/nbb_nightly_backload.py \
        --max-calls 5000 \
        >> scripts/_watchdog_state/nightly.log 2>&1

Key-revocation safety: if NBB returns 401 mid-run, we stop the whole run
and exit so the 15-min watchdog picks it up, rotates, and the next night
picks up cleanly. We never try to rotate in-script — that's the watchdog's
responsibility (single writer rule).

Quota safety: `--max-calls` caps total requests per run. Default 5000 is
conservative enough to stay well under any reasonable NBB subscription
quota; rotating Primary keys doesn't reset quota (it's per-subscription),
so "just rotate when exhausted" doesn't help. Nightly budget spreads the
month's quota over ~30 runs.

Progress is persisted to nbb_load_log (every successful load) + a
lightweight checkpoint in `meta` for resume-after-crash.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
import requests


def _backend_candidates(script_file: str | None = None) -> list[Path]:
    """Return possible directories that may contain backend modules."""
    script_path = Path(script_file or __file__).resolve()
    repo_root = script_path.parent.parent
    return [repo_root / "backend", repo_root]


def _bootstrap_backend_path(script_file: str | None = None) -> list[str]:
    """Make backend modules importable in both repo and container layouts."""
    added: list[str] = []
    candidates = _backend_candidates(script_file)
    for candidate in candidates:
        if (candidate / "db.py").exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            added.append(candidate_str)
    if not added:
        script_path = Path(script_file or __file__).resolve()
        raise RuntimeError(f"Could not locate backend modules for {script_path}")
    return added


def _load_backend_module(module_name: str):
    """Load a backend module explicitly from disk if normal import is brittle."""
    module = sys.modules.get(module_name)
    if module is not None:
        return module

    for candidate in _backend_candidates():
        module_path = candidate / f"{module_name}.py"
        if not module_path.exists():
            continue
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    raise ModuleNotFoundError(module_name)


_BACKEND_IMPORT_ROOTS = _bootstrap_backend_path()
_db = _load_backend_module("db")
_nbb_governance = _load_backend_module("nbb_governance")
get_connection = _db.get_connection
put_connection = _db.put_connection
fetch_one = _db.fetch_one
fetch_all = _db.fetch_all
execute = _db.execute
store_governance_snapshot = _nbb_governance.store_governance_snapshot


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("nbb_backload")

NBB_BASE_URL = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")
NBB_KEY = os.getenv("NBB_AUTHENTIC_KEY", "")
USER_AGENT = "Datasnoop/1.0 (Belgian Company Intelligence)"
# Rate limit. 1.25s keeps us well under NBB quota while being ~20% faster
# than the original 1.5s. If NBB returns 429, the run stops and the watchdog
# handles key rotation — so this is safe to tune.
REQUEST_DELAY = 1.25


def _headers() -> dict:
    return {
        "Accept": "application/json",
        "NBB-CBSO-Subscription-Key": NBB_KEY,
        "X-Request-Id": str(uuid.uuid4()),
        "User-Agent": USER_AGENT,
    }


def candidates_for_year(fiscal_year: int, limit: int) -> list[str]:
    """Companies that don't yet have fiscal_year loaded in financial_latest
    AND haven't been marked NO_FILINGS / PDF_ONLY for any prior attempt.

    NO_FILINGS is the global "never filed anything at NBB" sentinel.
    Any legacy NO_FILINGS_FY{year} rows (written briefly on 2026-04-20
    before we confirmed NBB's fiscalYear param is a no-op) also exclude
    via the LIKE match, so we never re-probe those CBEs either.

    Restricted to commercial companies legally required to file annual accounts.
    VZW, VME, foreign entities, public bodies etc. are excluded — they either
    never file with NBB or file so rarely it is not worth burning API quota on
    them during the primary backfill pass.

    Within the required-filer set, largest companies by assets first so each
    API call has maximum deal-sourcing value.

    type_of_enterprise = '2' selects legal persons; '1' is natural persons
    (sole traders) who never file with NBB.
    """
    # Juridical forms that are legally required to file annual accounts with NBB.
    # Excludes VZW (017), VME (070), foreign entities (030/230/235),
    # public bodies, foundations, and other non-filing forms.
    REQUIRED_FILER_FORMS = (
        '610', '615', '616',        # BV / BV met sociaal oogmerk / BV van publiek recht
        '014', '114', '614',        # NV / NV van publiek recht / NV met sociaal oogmerk
        '015', '010', '515',        # BVBA (legacy) / Eenpersoons BVBA / BVBA met SO
        '706', '716',               # CV (new) / CV van publiek recht
        '016', '116',               # CV oud statuut / CV oud statuut van publiek recht
        '008', '108', '508',        # CVBA / CVBA van publiek recht / CVBA met SO
        '006',                      # CVOA
        '001',                      # Europese Coöperatieve Vennootschap
        '011',                      # VOF (Vennootschap onder firma)
        '012',                      # GewComV (Gewone commanditaire vennootschap)
        '013',                      # CommVA (Commanditaire vennootschap op aandelen)
        '612',                      # CommV (new form)
        '060', '065',               # ESV / EESV
        '027',                      # SE (Societas Europaea)
    )
    rows = fetch_all(
        """
        SELECT e.enterprise_number
        FROM enterprise e
        WHERE e.status = 'AC'
          AND e.type_of_enterprise = '2'
          AND e.juridical_form = ANY(%s)
          AND NOT EXISTS (
              SELECT 1
              FROM financial_by_year fby
              WHERE fby.enterprise_number = e.enterprise_number
                AND fby.fiscal_year = %s
          )
          AND NOT EXISTS (
              SELECT 1
              FROM nbb_load_log ll
              WHERE ll.enterprise_number = e.enterprise_number
                AND (ll.deposit_key LIKE 'NO_FILINGS%%'
                     OR ll.deposit_key = 'PDF_ONLY')
          )
        ORDER BY (
            SELECT fl.total_assets
            FROM financial_latest fl
            WHERE fl.enterprise_number = e.enterprise_number
        ) DESC NULLS FIRST, e.enterprise_number
        LIMIT %s
        """,
        (list(REQUIRED_FILER_FORMS), fiscal_year, limit),
    )
    return [r["enterprise_number"] for r in rows]


def fetch_references(cbe: str, fiscal_year: int, session: requests.Session) -> tuple[int, list[dict]]:
    """Return (status_code, refs). refs is empty on 4xx/5xx."""
    try:
        resp = session.get(
            f"{NBB_BASE_URL}/authentic/legalEntity/{cbe}/references",
            headers=_headers(),
            params={"fiscalYear": str(fiscal_year)},
            timeout=20,
        )
    except Exception as e:
        log.warning("refs %s fy=%d network error: %s", cbe, fiscal_year, e)
        return 0, []
    if resp.status_code != 200:
        return resp.status_code, []
    try:
        payload = resp.json()
    except Exception:
        return resp.status_code, []
    if isinstance(payload, list):
        return 200, payload
    if isinstance(payload, dict):
        return 200, [payload]
    return 200, []


def fetch_filing(cbe: str, reference_number: str, session: requests.Session) -> Optional[dict]:
    # NB: the correct NBB path is /authentic/deposit/{ref}/accountingData
    # (NOT /authentic/legalEntity/{cbe}/account/{ref}/...), matching the
    # live handler in backend/routers/companies/financials.py + nbb_client.py.
    try:
        resp = session.get(
            f"{NBB_BASE_URL}/authentic/deposit/{reference_number}/accountingData",
            headers={**_headers(), "Accept": "application/x.jsonxbrl"},
            timeout=30,
        )
    except Exception as e:
        log.warning("filing %s ref=%s network: %s", cbe, reference_number, e)
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def _pick(d: dict, *keys):
    """Return the first non-empty value in d for any of the given keys."""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def store_filing(conn, cbe: str, filing_json: dict, ref_meta: dict) -> int:
    """Insert rubrics + load_log row. Returns number of rubric rows stored.

    Accepts NBB ref_meta in either PascalCase (legacy) or camelCase (2026 schema).
    """
    deposit_key = _pick(ref_meta, "ReferenceNumber", "referenceNumber")
    if not deposit_key:
        return 0
    exercise = _pick(ref_meta, "ExerciseDates", "exerciseDates") or {}
    end_date = _pick(exercise, "endDate", "EndDate") or ""
    fiscal_year = int(end_date[:4]) if end_date and len(end_date) >= 4 else None
    deposit_date = _pick(ref_meta, "DepositDate", "depositDate") or ""
    filing_model = _pick(ref_meta, "ModelType", "modelType") or ""

    rubrics = filing_json.get("Rubrics") or filing_json.get("rubrics") or []
    rows = []
    for r in rubrics:
        code = _pick(r, "Code", "code") or ""
        value = _pick(r, "Value", "value")
        period = _pick(r, "Period", "period") or "N"
        if code and value is not None:
            try:
                rows.append((
                    cbe, deposit_key, fiscal_year, deposit_date,
                    filing_model, code, period, float(value),
                ))
            except (TypeError, ValueError):
                continue

    cur = conn.cursor()
    try:
        if rows:
            psycopg2.extras.execute_batch(
                cur,
                """INSERT INTO financial_data
                   (enterprise_number, deposit_key, fiscal_year, deposit_date,
                    filing_model, rubric_code, period, value)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                rows,
            )
        cur.execute(
            "INSERT INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (cbe, deposit_key, len(rows)),
        )
        conn.commit()
        try:
            store_governance_snapshot(conn, cbe, deposit_key, fiscal_year, filing_json)
        except Exception as gov_err:
            log.warning("governance store failed for %s filing %s: %s", cbe, deposit_key, gov_err)
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def mark_no_filings(conn, cbe: str, sentinel: str) -> None:
    """Record NO_FILINGS or PDF_ONLY so we don't keep retrying this CBE."""
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
            "VALUES (%s, %s, 0) ON CONFLICT DO NOTHING",
            (cbe, sentinel),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close()


def is_pdf_only(refs: list[dict]) -> bool:
    """NBB model codes m120 / m211 / m212 indicate abbreviated / micro
    schemes that file only as PDF (no JSON-XBRL available)."""
    if not refs:
        return False

    def _end_date(r: dict) -> str:
        return (_pick(r, "ExerciseDates", "exerciseDates") or {}).get("endDate", "") or ""

    # Newest ref first — most recent model is the relevant one.
    refs_sorted = sorted(
        refs,
        key=lambda r: (_end_date(r), _pick(r, "DepositDate", "depositDate") or ""),
        reverse=True,
    )
    for r in refs_sorted:
        model = str(_pick(r, "ModelType", "modelType") or "").lower()
        end_date = _end_date(r)
        if end_date >= "2022-04-01" and model in {"m120", "m211", "m212"}:
            return True
    return False


def run(max_calls: int, start_year: int, end_year: int, per_year_cap: int, skip_rebuild: bool = False) -> None:
    if not NBB_KEY:
        log.error("NBB_AUTHENTIC_KEY not set — aborting")
        sys.exit(2)

    start_ts = time.time()
    session = requests.Session()
    calls = 0
    loaded = 0
    rubrics_total = 0
    no_filings = 0
    pdf_only = 0
    errors = 0

    conn = get_connection()
    since_reconnect = 0
    try:
        def _cycle_connection():
            nonlocal conn, since_reconnect
            put_connection(conn)
            conn = get_connection()
            since_reconnect = 0

        # Reverse chronological: 2026 → 2025 → 2024 → 2023 → 2022
        for fy in range(start_year, end_year - 1, -1):
            if calls >= max_calls:
                log.info("max-calls (%d) hit — stopping", max_calls)
                break

            year_budget = min(per_year_cap, max_calls - calls)
            log.info("=== FY%d — budget %d calls ===", fy, year_budget)
            cbes = candidates_for_year(fy, year_budget)
            log.info("FY%d: %d candidate CBEs", fy, len(cbes))

            for cbe in cbes:
                if calls >= max_calls:
                    break
                calls += 1

                status, refs = fetch_references(cbe, fy, session)
                # 401 → key revoked; stop the run so watchdog rotates.
                if status == 401:
                    log.error("401 from NBB for %s fy=%d — stopping for watchdog", cbe, fy)
                    return
                if status == 429:
                    log.error("429 rate-limit from NBB — stopping run")
                    return
                if status >= 500:
                    errors += 1
                    time.sleep(REQUEST_DELAY)
                    continue
                if not refs:
                    # 404/empty → NBB has NO filings for this CBE under ANY year.
                    # Verified empirically: NBB silently ignores the `fiscalYear`
                    # query param and always returns the full history, so an
                    # empty response is global, not year-specific. Retire the
                    # CBE permanently with the unqualified NO_FILINGS sentinel.
                    mark_no_filings(conn, cbe, "NO_FILINGS")
                    no_filings += 1
                    time.sleep(REQUEST_DELAY)
                    continue

                # Detect PDF-only filer via model codes
                if is_pdf_only(refs):
                    mark_no_filings(conn, cbe, "PDF_ONLY")
                    pdf_only += 1
                    time.sleep(REQUEST_DELAY)
                    continue

                # NBB returned every year's refs, not just the requested one —
                # so iterate ALL refs and load every non-PDF, non-loaded one
                # in a single visit. After this, the CBE has everything we can
                # get and won't be a candidate for any year going forward.
                refs_sorted = sorted(
                    refs,
                    key=lambda r: _pick(r, "DepositDate", "depositDate") or "",
                    reverse=True,
                )
                time.sleep(REQUEST_DELAY)

                for ref_meta in refs_sorted:
                    if calls >= max_calls:
                        break
                    reference_number = _pick(ref_meta, "ReferenceNumber", "referenceNumber")
                    if not reference_number:
                        continue

                    # Skip PDF-only model codes before 2022-04 JSON cutoff
                    model = str(_pick(ref_meta, "ModelType", "modelType") or "").lower()
                    end_date = (_pick(ref_meta, "ExerciseDates", "exerciseDates") or {}).get("endDate", "") or ""
                    if end_date < "2022-04-01" or model in {"m120", "m211", "m212"}:
                        continue

                    already = fetch_one(
                        "SELECT 1 FROM nbb_load_log WHERE enterprise_number=%s AND deposit_key=%s",
                        (cbe, reference_number),
                    )
                    if already:
                        continue

                    calls += 1
                    if calls > max_calls:
                        break

                    filing = fetch_filing(cbe, reference_number, session)
                    if not filing:
                        errors += 1
                        time.sleep(REQUEST_DELAY)
                        continue

                    try:
                        n = store_filing(conn, cbe, filing, ref_meta)
                    except Exception as e:
                        log.warning("store_filing failed for %s: %s", cbe, e)
                        errors += 1
                        time.sleep(REQUEST_DELAY)
                        continue

                    if n > 0:
                        loaded += 1
                        rubrics_total += n
                        since_reconnect += 1
                        if since_reconnect >= 100:
                            _cycle_connection()
                    time.sleep(REQUEST_DELAY)

                if loaded % 50 == 0 and loaded > 0:
                    log.info("progress FY%d: %d loaded, %d rubrics, %d calls",
                             fy, loaded, rubrics_total, calls)

        # Refresh financial_latest + financial_by_year. Skipped for daytime
        # runs (skip_rebuild=True) to avoid blocking the next run — the
        # nightly 02:00 run always rebuilds so screener data is fresh by morning.
        if skip_rebuild:
            log.info("skipping materialized table rebuild (skip_rebuild=True)")
        else:
            log.info("refreshing materialized tables...")
            cur = conn.cursor()
            try:
                nbb_batch_pipeline = _load_backend_module("nbb_batch_pipeline")
                nbb_batch_pipeline.rebuild_materialized_tables()
            except Exception as e:
                log.warning("refresh failed (non-fatal): %s", e)
            finally:
                cur.close()

    finally:
        put_connection(conn)

    elapsed = time.time() - start_ts
    log.info("=" * 60)
    log.info("Backload done in %.0fs: %d calls, %d loaded, %d rubrics, %d pdf-only, %d no-filings, %d errors",
             elapsed, calls, loaded, rubrics_total, pdf_only, no_filings, errors)
    log.info("=" * 60)

    # Write a summary to meta for the admin page
    try:
        execute(
            "INSERT INTO meta (variable, value) VALUES (%s, %s) "
            "ON CONFLICT (variable) DO UPDATE SET value = EXCLUDED.value",
            ("nbb_nightly_backload_last",
             f"{datetime.now(timezone.utc).isoformat()}: {loaded} loaded, {rubrics_total} rubrics, {pdf_only} pdf-only, {no_filings} no-filings, {errors} errors, {calls} calls"),
        )
    except Exception:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="NBB nightly backload — reverse-chronological gap fill")
    ap.add_argument("--max-calls", type=int, default=5000,
                    help="Hard cap on NBB API calls for this run (default 5000)")
    ap.add_argument("--start-year", type=int, default=2024,
                    help="Newest fiscal year to backfill (default 2024 — 2025/2026 "
                         "filings are too sparse this early in the year; re-enable "
                         "them manually later).")
    ap.add_argument("--end-year", type=int, default=2022,
                    help="Oldest fiscal year to backfill (default 2022)")
    ap.add_argument("--per-year-cap", type=int, default=3000,
                    help="Max candidates per fiscal year before rolling to the next (default 3000)")
    ap.add_argument("--skip-rebuild", action="store_true", default=False,
                    help="Skip materialized table rebuild at end of run (use for daytime runs)")
    args = ap.parse_args()

    run(args.max_calls, args.start_year, args.end_year, args.per_year_cap, args.skip_rebuild)
