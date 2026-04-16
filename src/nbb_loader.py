"""Parse NBB CBSO JSON filings into the financial_data table.

JSON filing structure (application/x.jsonxbrl, schema v0.94):
  {
    "ReferenceNumber": "2021-00000132",   # deposit key
    "EnterpriseName":  "...",
    "LegalForm":       {...},
    "Rubrics": [
      {"Code": "70",   "Value": "5000000.00", "Period": "N"},
      {"Code": "9901", "Value": "500000.00",  "Period": "N"},
      {"Code": "630",  "Value": "200000.00",  "Period": "N"},
      {"Code": "70",   "Value": "4500000.00", "Period": "NM1"},
      ...
    ]
  }

References list structure (application/json from /legalEntity/{CBE}/references):
  Each item may use different field names across API versions — this loader
  handles both known variants and logs unrecognised shapes.

EBITDA = rubric 9901 (EBIT) + rubric 630 (D&A)

Usage:
    python src/nbb_loader.py --cbe 0403101811
    python src/nbb_loader.py --cbe 0403101811 --since-year 2020
    python src/nbb_loader.py --date 2024-01-15          # daily extract
    python src/nbb_loader.py --cbe 0403101811 --dry-run
"""

import argparse
import io
import json
import os
import sqlite3
import sys
import zipfile
from datetime import datetime

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
SCHEMA_SQL = os.path.join(os.path.dirname(__file__), "schema.sql")


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Reference metadata helpers
# The NBB references endpoint returns a list; the exact field names have
# varied across API versions. We try known variants.
# ---------------------------------------------------------------------------

def _get_field(obj, *candidates, default=None):
    """Return first matching key from obj, case-insensitively."""
    lower = {k.lower(): v for k, v in obj.items()}
    for c in candidates:
        v = lower.get(c.lower())
        if v is not None:
            return v
    return default


def extract_ref_metadata(ref_item):
    """Extract (deposit_key, fiscal_year, deposit_date) from a references list item.

    Handles both production API format (ReferenceNumber, ExerciseDates.endDate,
    DepositDate) and older/UAT field names (depositKey, fiscalYear, depositDate).
    """
    deposit_key = _get_field(
        ref_item,
        "referenceNumber", "depositKey", "reference", "ReferenceNumber",
    )

    # Try flat field first, then fall back to nested ExerciseDates.endDate
    fiscal_year = _get_field(
        ref_item,
        "fiscalYear", "exerciseYear", "boekjaar", "exercice",
    )
    if not fiscal_year:
        ex = ref_item.get("ExerciseDates") or ref_item.get("exerciseDates") or {}
        end = ex.get("endDate") or ex.get("EndDate") or ""
        if end:
            fiscal_year = str(end)[:4]  # "YYYY-MM-DD" → "YYYY"

    deposit_date = _get_field(
        ref_item,
        "depositDate", "dateDeposit", "depositionDate", "filingDate", "DepositDate",
    )
    # Model type (VOL / VKT / MIC) — stored in ModelType in production API
    model_type = _get_field(ref_item, "ModelType", "modelType", "model", "filingModel")
    return deposit_key, fiscal_year, deposit_date, model_type


# ---------------------------------------------------------------------------
# Filing JSON parser
# ---------------------------------------------------------------------------

def parse_filing(filing_json, deposit_key=None, fiscal_year=None, deposit_date=None, filing_model=None):
    """Parse an NBB JSON filing response into a list of rubric dicts.

    Args:
        filing_json:  Parsed JSON dict from the NBB API.
        deposit_key:  Filing reference (YYYY-NNNNNNNN). Falls back to
                      ReferenceNumber field inside the response.
        fiscal_year:  From the references list; not always in the filing body.
        deposit_date: From the references list.

    Returns:
        dict with keys:
          enterprise_number, deposit_key, fiscal_year, deposit_date,
          filing_model, rubrics (list of {rubric_code, period, value})
        or None if the filing cannot be parsed.
    """
    if not filing_json:
        return None

    # Deposit key — prefer what we know from the references call
    if not deposit_key:
        deposit_key = _get_field(filing_json, "ReferenceNumber", "referenceNumber", "depositKey")
    if not deposit_key:
        log("  WARNING: no deposit key found in filing — skipping")
        return None

    # Enterprise number — strip dots
    enterprise_number = _get_field(
        filing_json,
        "EnterpriseNumber", "enterpriseNumber", "cbeNumber",
    )
    if enterprise_number:
        enterprise_number = enterprise_number.replace(".", "")

    # Filing model (VOL/VKT/MIC/...) — prefer caller-supplied (from references list)
    if not filing_model:
        filing_model = _get_field(filing_json, "Model", "model", "filingModel", "schema")
    if not filing_model and "LegalForm" in filing_json:
        lf = filing_json["LegalForm"]
        if isinstance(lf, dict):
            filing_model = _get_field(lf, "Model", "model", "code")

    # Rubrics array — the core accounting data
    rubrics_raw = _get_field(filing_json, "Rubrics", "rubrics", "accountingData", "accounts")
    if not rubrics_raw:
        log(f"  WARNING: no Rubrics found in filing {deposit_key}")
        return None

    rubrics = []
    for entry in rubrics_raw:
        code = _get_field(entry, "Code", "rubricKey", "rubric", "code")
        raw_value = _get_field(entry, "Value", "value")
        period = _get_field(entry, "Period", "period") or "N"

        if code is None or raw_value is None:
            continue

        try:
            value = float(str(raw_value).replace(",", ".").strip())
        except (ValueError, TypeError):
            continue

        rubrics.append({
            "rubric_code": str(code).strip(),
            "period": str(period).strip(),
            "value": value,
        })

    return {
        "enterprise_number": enterprise_number,
        "deposit_key": deposit_key,
        "fiscal_year": fiscal_year,
        "deposit_date": deposit_date,
        "filing_model": filing_model,
        "rubrics": rubrics,
    }


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def already_loaded(conn, deposit_key):
    """Check if this filing has already been loaded."""
    row = conn.execute(
        "SELECT 1 FROM nbb_load_log WHERE deposit_key = ?", (deposit_key,)
    ).fetchone()
    return row is not None


def store_filing(conn, parsed, dry_run=False):
    """Write parsed filing to financial_data and nbb_load_log.

    Returns number of rubric rows written.
    """
    if not parsed or not parsed["rubrics"]:
        return 0

    deposit_key = parsed["deposit_key"]
    enterprise_number = parsed["enterprise_number"]
    fiscal_year = parsed["fiscal_year"]
    deposit_date = parsed["deposit_date"]
    filing_model = parsed["filing_model"]
    rubrics = parsed["rubrics"]

    if dry_run:
        log(f"  [dry-run] Would write {len(rubrics)} rubrics for {deposit_key}")
        return len(rubrics)

    conn.executemany(
        """INSERT OR REPLACE INTO financial_data
           (enterprise_number, deposit_key, fiscal_year, deposit_date,
            filing_model, rubric_code, period, value)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (enterprise_number, deposit_key, fiscal_year, deposit_date,
             filing_model, r["rubric_code"], r["period"], r["value"])
            for r in rubrics
        ],
    )
    conn.execute(
        """INSERT OR REPLACE INTO nbb_load_log
           (enterprise_number, deposit_key, rubric_count)
           VALUES (?, ?, ?)""",
        (enterprise_number, deposit_key, len(rubrics)),
    )
    conn.commit()
    return len(rubrics)


# ---------------------------------------------------------------------------
# Company structure extraction (ParticipatingInterests, Shareholders, Admins)
# ---------------------------------------------------------------------------

def _fmt_address(addr):
    """Format an NBB address dict into a single line."""
    if not addr or not isinstance(addr, dict):
        return None
    parts = []
    street = addr.get("Street") or ""
    num = addr.get("Number") or ""
    if street:
        parts.append(f"{street} {num}".strip())
    city = addr.get("OtherCity") or addr.get("City") or ""
    # City codes like "pcd:m9860" need to be kept as-is (no lookup table)
    pc = addr.get("OtherPostalCode") or ""
    if pc or city:
        parts.append(f"{pc} {city}".strip())
    country = addr.get("Country") or addr.get("OtherCountry") or ""
    if country:
        parts.append(country.replace("cty:m", ""))
    return ", ".join(p for p in parts if p) or None


def store_structure_data(conn, filing_json, enterprise_number, deposit_key, fiscal_year, dry_run=False):
    """Extract and store ParticipatingInterests, Shareholders, Administrators."""
    if not filing_json or dry_run:
        return

    # --- Participating Interests (subsidiaries) ---
    for pi in (filing_json.get("ParticipatingInterests") or []):
        ent = pi.get("Entity") or {}
        name = ent.get("Name")
        if not name:
            continue
        identifier = ent.get("Identifier")
        address = _fmt_address(ent.get("Address"))
        country_raw = (ent.get("Address") or {}).get("Country") or ""
        country = country_raw.replace("cty:m", "") if country_raw else None

        # Financial data from rubrics within PI
        rubrics = pi.get("Rubrics") or []
        equity_value = None
        net_result = None
        ownership_pct = None
        for r in rubrics:
            code = r.get("Code") or ""
            val = r.get("Value")
            if val is not None:
                try:
                    val = float(str(val).replace(",", "."))
                except (ValueError, TypeError):
                    val = None
            if "9900" in code or code == "99":
                equity_value = val
            elif "9904" in code:
                net_result = val

        # Ownership percentage sometimes in a separate field
        pct_field = pi.get("PartPercentage") or pi.get("Percentage")
        if pct_field is not None:
            try:
                ownership_pct = float(str(pct_field).replace(",", "."))
            except (ValueError, TypeError):
                pass

        try:
            conn.execute(
                """INSERT OR REPLACE INTO participating_interest
                   (enterprise_number, deposit_key, fiscal_year, name, identifier,
                    address, country, ownership_pct, equity_value, net_result)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (enterprise_number, deposit_key, fiscal_year, name, identifier,
                 address, country, ownership_pct, equity_value, net_result),
            )
        except Exception:
            pass

    # --- Shareholders ---
    sh = filing_json.get("Shareholders") or {}
    for entity_sh in (sh.get("EntityShareHolders") or []):
        ent = entity_sh.get("Entity") or {}
        name = ent.get("Name")
        if not name:
            continue
        try:
            conn.execute(
                """INSERT OR REPLACE INTO shareholder
                   (enterprise_number, deposit_key, fiscal_year, shareholder_type,
                    name, identifier, address, shares_held, ownership_pct)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (enterprise_number, deposit_key, fiscal_year, "entity",
                 name, ent.get("Identifier"), _fmt_address(ent.get("Address")),
                 None, None),
            )
        except Exception:
            pass

    for ind_sh in (sh.get("IndividualShareHolders") or []):
        person = ind_sh.get("Person") or {}
        first = person.get("FirstName") or ""
        last = person.get("LastName") or ""
        name = f"{first} {last}".strip()
        if not name:
            continue
        try:
            conn.execute(
                """INSERT OR REPLACE INTO shareholder
                   (enterprise_number, deposit_key, fiscal_year, shareholder_type,
                    name, identifier, address, shares_held, ownership_pct)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (enterprise_number, deposit_key, fiscal_year, "individual",
                 name, None, _fmt_address(person.get("Address")),
                 None, None),
            )
        except Exception:
            pass

    # --- Administrators ---
    ad = filing_json.get("Administrators") or {}
    for lp in (ad.get("LegalPersons") or []):
        ent = lp.get("Entity") or {}
        name = ent.get("Name")
        if not name:
            continue
        mandates = lp.get("Mandates") or []
        role = mandates[0].get("FunctionMandate", "") if mandates else ""
        dates = mandates[0].get("MandateDates", {}) if mandates else {}
        reps = lp.get("Representatives") or []
        rep_name = None
        if reps:
            r = reps[0]
            rep_name = f"{r.get('FirstName','')} {r.get('LastName','')}".strip() or None
        try:
            conn.execute(
                """INSERT OR REPLACE INTO administrator
                   (enterprise_number, deposit_key, fiscal_year, person_type,
                    name, role, identifier, mandate_start, mandate_end, representative_name)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (enterprise_number, deposit_key, fiscal_year, "legal",
                 name, role, ent.get("Identifier"),
                 dates.get("StartDate"), dates.get("EndDate"), rep_name),
            )
        except Exception:
            pass

    for np_ in (ad.get("NaturalPersons") or []):
        person = np_.get("Person") or {}
        first = person.get("FirstName") or ""
        last = person.get("LastName") or ""
        name = f"{first} {last}".strip()
        if not name:
            continue
        mandates = np_.get("Mandates") or []
        role = mandates[0].get("FunctionMandate", "") if mandates else ""
        dates = mandates[0].get("MandateDates", {}) if mandates else {}
        try:
            conn.execute(
                """INSERT OR REPLACE INTO administrator
                   (enterprise_number, deposit_key, fiscal_year, person_type,
                    name, role, identifier, mandate_start, mandate_end, representative_name)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (enterprise_number, deposit_key, fiscal_year, "natural",
                 name, role, None,
                 dates.get("StartDate"), dates.get("EndDate"), None),
            )
        except Exception:
            pass

    conn.commit()


# ---------------------------------------------------------------------------
# Derived metrics — for logging / dry-run display
# ---------------------------------------------------------------------------

def compute_ebitda(rubrics):
    """Compute EBITDA from a list of rubric dicts (current period only).

    EBITDA = rubric 9901 (EBIT) + rubric 630 (D&A).

    Returns dict with revenue, ebit, da, ebitda, ebitda_partial, net_profit, fte.

    The ebitda_partial flag indicates fidelity of the EBITDA value:
        False -> both EBIT and D&A present; ebitda is the true value
        True  -> EBIT present but D&A missing (typical of abbreviated/micro
                 filings); ebitda equals EBIT and is therefore an underestimate
        None  -> EBIT itself is missing; ebitda is None and the flag is undefined
    """
    values = {}
    for r in rubrics:
        if r["period"] == "N":
            values[r["rubric_code"]] = r["value"]

    ebit = values.get("9901")
    da   = values.get("630")
    ebitda = None
    if ebit is not None:
        ebitda = ebit + (da or 0.0)

    return {
        "revenue": values.get("70"),
        "ebit":    ebit,
        "da":      da,
        "ebitda":  ebitda,
        "ebitda_partial": (None if ebit is None else (da is None)),
        "net_profit": values.get("9904"),
        "fte":     values.get("9087"),
    }


def fmt(value, decimals=0):
    if value is None:
        return "n/a"
    if decimals:
        return f"{value:,.{decimals}f}"
    return f"{value:,.0f}"


# ---------------------------------------------------------------------------
# Load a single company by CBE
# ---------------------------------------------------------------------------

def load_company(conn, client, cbe, since_year=None, dry_run=False):
    cbe = str(cbe).replace(".", "")
    log(f"Loading financials for CBE {cbe}")

    refs = client.get_references(cbe)
    if not refs:
        log(f"  No filings found for {cbe}")
        # Write sentinel so the catch-up query skips this CBE next run
        if not dry_run:
            conn.execute(
                "INSERT OR IGNORE INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
                "VALUES (?, 'NO_FILINGS', 0)",
                (cbe,)
            )
            conn.commit()
        return

    if since_year:
        def _ref_year(r):
            _, fy, _, _ = extract_ref_metadata(r)
            try:
                return int(fy) if fy else 0
            except (ValueError, TypeError):
                return 0
        refs = [r for r in refs if _ref_year(r) >= int(since_year)]

    refs_sorted = sorted(refs, key=lambda r: _get_field(r, "depositDate", "DepositDate", "dateDeposit", "filingDate", default="") or "")

    log(f"  {len(refs_sorted)} filing(s) to process")

    # No NBB filings at all — stamp immediately so catch-up skips this company next run
    if not dry_run and not refs_sorted:
        conn.execute(
            "INSERT OR IGNORE INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
            "VALUES (?, 'NO_FILINGS', 0)",
            (cbe,)
        )
        conn.commit()

    loaded = 0
    skipped = 0
    no_json = 0

    for ref in refs_sorted:
        deposit_key, fiscal_year, deposit_date, model_type = extract_ref_metadata(ref)

        if not deposit_key:
            log(f"  WARNING: ref with no deposit key: {ref}")
            continue

        if not dry_run and already_loaded(conn, deposit_key):
            skipped += 1
            continue

        filing_json = client.get_filing_json(deposit_key)
        if filing_json is None:
            log(f"  {deposit_key} ({fiscal_year}): no JSON data (pre-2022 or not XBRL)")
            no_json += 1
            continue

        parsed = parse_filing(filing_json, deposit_key=deposit_key,
                              fiscal_year=fiscal_year, deposit_date=deposit_date,
                              filing_model=model_type)
        if not parsed:
            log(f"  {deposit_key}: could not parse filing")
            continue

        # Patch enterprise number from CBE argument if not in filing
        if not parsed["enterprise_number"]:
            parsed["enterprise_number"] = cbe

        metrics = compute_ebitda(parsed["rubrics"])
        n = store_filing(conn, parsed, dry_run=dry_run)

        # Extract company structure (shareholders, subsidiaries, admins)
        store_structure_data(conn, filing_json,
                             parsed["enterprise_number"], deposit_key, fiscal_year,
                             dry_run=dry_run)

        log(
            f"  {deposit_key} FY{fiscal_year}: "
            f"revenue={fmt(metrics['revenue'])} "
            f"EBIT={fmt(metrics['ebit'])} "
            f"D&A={fmt(metrics['da'])} "
            f"EBITDA={fmt(metrics['ebitda'])} "
            f"net={fmt(metrics['net_profit'])} "
            f"FTE={fmt(metrics['fte'])} "
            f"({n} rubrics)"
        )
        loaded += 1

    # If we saw refs but got no usable JSON at all (all pre-XBRL), stamp a sentinel
    # so the catch-up query won't attempt this company again next run.
    if not dry_run and loaded == 0 and skipped == 0 and no_json > 0:
        conn.execute(
            "INSERT OR IGNORE INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
            "VALUES (?, 'NO_FILINGS', 0)",
            (cbe,)
        )
        conn.commit()
        log(f"  Stamped NO_FILINGS (all {no_json} filing(s) are pre-XBRL)")

    log(f"  Done — {loaded} loaded, {skipped} already in DB")


# ---------------------------------------------------------------------------
# Load a daily extract (ZIP of all filings for one date)
# ---------------------------------------------------------------------------

def load_daily_extract(conn, client, date, dry_run=False):
    log(f"Loading daily extract for {date}")
    resp = client.get_extract_json(date)
    if resp is None:
        log(f"  No data for {date} (404)")
        return

    zip_bytes = resp.content
    log(f"  ZIP: {len(zip_bytes):,} bytes")

    loaded = skipped = errors = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        log(f"  {len(names)} filing(s) in ZIP")

        for name in names:
            try:
                with zf.open(name) as f:
                    filing_json = json.load(f)
            except Exception as e:
                log(f"  ERROR reading {name}: {e}")
                errors += 1
                continue

            deposit_key = _get_field(filing_json, "ReferenceNumber", "referenceNumber", "depositKey")
            if not deposit_key:
                # Try to derive from filename (often named by deposit key)
                deposit_key = os.path.splitext(os.path.basename(name))[0]

            if not dry_run and already_loaded(conn, deposit_key):
                skipped += 1
                continue

            parsed = parse_filing(filing_json, deposit_key=deposit_key)
            if not parsed:
                errors += 1
                continue

            if not parsed.get("enterprise_number"):
                log(f"  {deposit_key}: skipped (no enterprise_number)")
                errors += 1
                continue

            metrics = compute_ebitda(parsed["rubrics"])
            n = store_filing(conn, parsed, dry_run=dry_run)

            # Extract company structure
            ent = parsed.get("enterprise_number")
            if ent:
                store_structure_data(conn, filing_json, ent, deposit_key,
                                     parsed.get("fiscal_year"), dry_run=dry_run)

            log(
                f"  {deposit_key}: "
                f"EBITDA={fmt(metrics['ebitda'])} "
                f"({n} rubrics)"
            )
            loaded += 1

    log(f"  Done — {loaded} loaded, {skipped} skipped, {errors} errors")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Load NBB financial filings into SQLite")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cbe", help="Load all filings for one CBE number")
    group.add_argument("--date", help="Load daily extract for YYYY-MM-DD")

    parser.add_argument("--since-year", type=int, help="Only load filings from this fiscal year onwards")
    parser.add_argument("--dry-run", action="store_true", help="Parse and log without writing to DB")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)

    if not os.path.exists(db_path) and not args.dry_run:
        log(f"ERROR: database not found at {db_path}. Run scripts/init_db.py first.")
        sys.exit(1)

    # Apply schema additions (idempotent CREATE IF NOT EXISTS)
    conn = sqlite3.connect(db_path)
    with open(SCHEMA_SQL, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    # Import here to avoid circular dependency if running standalone
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.nbb_client import NBBClient
    client = NBBClient()

    if args.cbe:
        load_company(conn, client, args.cbe, since_year=args.since_year, dry_run=args.dry_run)
    else:
        load_daily_extract(conn, client, args.date, dry_run=args.dry_run)

    conn.close()


if __name__ == "__main__":
    main()
