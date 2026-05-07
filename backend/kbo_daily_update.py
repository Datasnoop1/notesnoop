"""KBO daily updater — downloads and applies KBO update ZIPs to PostgreSQL.

Downloads the latest update ZIPs from kbopub.economie.fgov.be,
applies deletes + inserts to the live database, and refreshes company_info.

Run daily via cron (host-side wrapper executes inside backend container):
  0 6 * * * bash /opt/leadpeek/scripts/kbo_update.sh
"""

import csv
import io
import os
import re
import sys
import time
import tempfile
import logging
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# Add parent to path so we can import db module
sys.path.insert(0, os.path.dirname(__file__))
from db import get_conn, execute, fetch_one, fetch_all, transaction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("kbo_updater")

# KBO Open Data portal endpoints (2026-05-07: auth + URL fix).
# The portal redirects unauthenticated GETs to /login. Our previous code
# accidentally relied on this — it landed on the login page, found zero
# `Update*.zip` links, and silently reported "no updates available". The
# auth flow below logs in via Spring Security's j_spring_security_check
# before scraping the file listing at /affiliation/xml?form=.
KBO_LOGIN_GET    = "https://kbopub.economie.fgov.be/kbo-open-data/login"
KBO_LOGIN_POST   = "https://kbopub.economie.fgov.be/kbo-open-data/static/j_spring_security_check"
KBO_FILES_PAGE   = "https://kbopub.economie.fgov.be/kbo-open-data/affiliation/xml?form="
# Hrefs on the file page are relative (e.g. `files/KboOpenData_..._Update.zip`).
# This is the base they resolve against.
KBO_FILES_BASE   = "https://kbopub.economie.fgov.be/kbo-open-data/affiliation/xml/"
KBO_USER_AGENT   = "Mozilla/5.0 (Datasnoop KBO Updater)"

# Credentials are read from env (KBO_USER, KBO_PASS). Missing creds
# cause a hard failure rather than the silent "no updates" trap.
KBO_USER = os.environ.get("KBO_USER", "").strip()
KBO_PASS = os.environ.get("KBO_PASS", "").strip()

# Safety guards: a single delta should never delete more than these
# limits (typical KBO daily delta is <1000 rows per table). When any
# guard trips, abort the extract instead of letting CASCADE wipe child
# rows or letting an enormous batch wipe historical data. Configure via
# env per deploy.
KBO_MAX_ENTERPRISE_DELETE    = int(os.environ.get("KBO_MAX_ENTERPRISE_DELETE",    "1000"))
KBO_MAX_ESTABLISHMENT_DELETE = int(os.environ.get("KBO_MAX_ESTABLISHMENT_DELETE", "5000"))
KBO_MAX_BRANCH_DELETE        = int(os.environ.get("KBO_MAX_BRANCH_DELETE",        "1000"))

# Download size cap (zip-bomb / disk-fill defense). KBO daily Update.zip
# files are typically 0.4–1.5 MB. 256 MB leaves a wide safety margin
# against any plausible legitimate growth while killing a hostile
# multi-GB download well before /tmp fills.
KBO_MAX_DOWNLOAD_BYTES = int(os.environ.get("KBO_MAX_DOWNLOAD_BYTES", str(256 * 1024 * 1024)))

# Hostname the portal must redirect to after login. Defends against a
# hijacked DNS / MITM that would otherwise present a page with
# "/affiliation/index" in its URL but on a different host.
KBO_EXPECTED_HOST = "kbopub.economie.fgov.be"

BATCH_SIZE = 5_000

TABLE_MAP = {
    "enterprise":    ("enterprise",    "enterprise_number"),
    "establishment": ("establishment", "establishment_number"),
    "denomination":  ("denomination",  "entity_number"),
    "address":       ("address",       "entity_number"),
    "activity":      ("activity",      "entity_number"),
    "contact":       ("contact",       "entity_number"),
    "branch":        ("branch",        "id"),
    "code":          ("code",          None),
}

# Tables where we delete ALL rows for affected entities
ENTITY_DELETE_TABLES = {"denomination", "address", "activity", "contact"}


def strip_dots(number):
    if number:
        return number.replace(".", "").strip()
    return number


def convert_date(date_str):
    if not date_str or not date_str.strip():
        return None
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", date_str.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return date_str


def get_last_extract():
    """Get the last applied extract number from the database."""
    row = fetch_one("SELECT MAX(extract_number) AS n FROM kbo_extract_log")
    return row["n"] or 0


class KBOAuthError(RuntimeError):
    """Raised when KBO login fails or credentials are missing.

    Distinct from a generic discovery exception so cron-level handlers
    (and the operator's nightly health email) can surface auth issues
    explicitly instead of recording them as 'no updates available'.
    """


def authed_session():
    """Return a requests.Session that has logged in to the KBO portal.

    Spring Security flow:
      1. GET /kbo-open-data/login           — get JSESSIONID cookie
      2. POST /static/j_spring_security_check — submit credentials
      3. Successful login redirects to /affiliation/index

    Affirmative success check: after the POST + redirect chain, the
    final URL must be on the expected host AND its path must contain
    "/affiliation/". Anything else — landing back at /login, an
    unexpected host, a 5xx, a redirect to nowhere — raises KBOAuthError
    so the cron emits a non-zero exit code instead of "happy zero with
    no work done".
    """
    if not (KBO_USER and KBO_PASS):
        raise KBOAuthError(
            "KBO_USER / KBO_PASS env vars are not set. The daily updater "
            "cannot authenticate with the KBO portal — silently reporting "
            "'no updates' would let real changes accumulate undetected. "
            "Set both vars in /opt/leadpeek/.env.production and restart."
        )
    session = requests.Session()
    session.headers["User-Agent"] = KBO_USER_AGENT
    # Step 1: prime cookie jar. raise_for_status protects against a 5xx
    # masquerading as "we're authenticated" later.
    pre = session.get(KBO_LOGIN_GET, timeout=30)
    pre.raise_for_status()
    # Step 2: submit credentials. Spring Security responds 200 on success
    # (after redirect chain) with the post-login landing page.
    resp = session.post(
        KBO_LOGIN_POST,
        data={"j_username": KBO_USER, "j_password": KBO_PASS},
        timeout=30,
        allow_redirects=True,
    )
    resp.raise_for_status()
    # Affirmative success check (host pinned + path required). Anything
    # else — including landing back on /login, on a 200 with no redirect,
    # or on a redirected hostname we don't expect — is a hard fail.
    parsed = urlparse(resp.url)
    if parsed.hostname != KBO_EXPECTED_HOST or "/affiliation/" not in parsed.path:
        raise KBOAuthError(
            f"KBO login failed for user '{KBO_USER}' — expected to land on "
            f"{KBO_EXPECTED_HOST}/kbo-open-data/affiliation/* but got "
            f"{parsed.hostname}{parsed.path}. Verify credentials and that "
            f"the portal hasn't been redesigned again."
        )
    log.info("KBO login OK as %s", KBO_USER)
    return session


def discover_update_zips(session=None):
    """Scrape the authenticated file-listing page for Update ZIP URLs.

    Returns a sorted list of (extract_number, full_url) tuples.

    On any failure — auth, network, parser — raises rather than returning
    an empty list so the cron job exits with a non-zero status. The old
    behaviour of swallowing the exception and returning [] caused 22 days
    of silent data freeze before anyone noticed.
    """
    log.info("Discovering available update ZIPs from KBO portal...")
    if session is None:
        session = authed_session()
    resp = session.get(KBO_FILES_PAGE, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    zips = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.endswith("_Update.zip"):
            continue
        match = re.search(r"_(\d+)_", href)
        if not match:
            continue
        num = int(match.group(1))
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = "https://kbopub.economie.fgov.be" + href
        else:
            # Relative to KBO_FILES_BASE, e.g. "files/KboOpenData_...zip"
            full_url = KBO_FILES_BASE + href.lstrip("/")
        zips.append((num, full_url))
    zips.sort(key=lambda x: x[0])
    log.info("Found %d update ZIPs on portal", len(zips))
    if not zips:
        # Defensive: if we found zero ZIPs but auth succeeded, something
        # changed at KBO's end (page redesign, account de-subscribed,
        # etc.). Loud failure beats silent freeze.
        log.warning(
            "Authenticated but found zero Update.zip links on the file "
            "page — investigate: KBO may have redesigned the portal again "
            "or this account may have been unsubscribed."
        )
    return zips


def download_zip(url, dest_dir, session=None):
    """Download a ZIP to a temp dir using an authenticated session.

    Aborts and removes the partial file if the download exceeds
    KBO_MAX_DOWNLOAD_BYTES — defends against zip-bomb / disk-fill on a
    malformed or hostile portal response.
    """
    filename = os.path.basename(url.rstrip("/"))
    dest = os.path.join(dest_dir, filename)
    log.info(f"Downloading {filename}...")
    if session is None:
        session = authed_session()
    written = 0
    with session.get(url, timeout=180, stream=True) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                written += len(chunk)
                if written > KBO_MAX_DOWNLOAD_BYTES:
                    f.close()
                    try:
                        os.remove(dest)
                    except OSError:
                        pass
                    raise RuntimeError(
                        f"Download {filename} exceeded "
                        f"KBO_MAX_DOWNLOAD_BYTES={KBO_MAX_DOWNLOAD_BYTES} "
                        f"after {written} bytes — aborted."
                    )
                f.write(chunk)
    size_mb = written / 1024 / 1024
    log.info(f"Downloaded {filename} ({size_mb:.1f} MB)")
    return dest


def open_csv_from_zip(zf, filename):
    f = zf.open(filename)
    text = io.TextIOWrapper(f, encoding="utf-8")
    return csv.DictReader(text)


def apply_deletes(cur, zf, filename, table_name):
    """Delete rows from table based on entity numbers in a delete CSV."""
    reader = open_csv_from_zip(zf, filename)
    del_count = 0

    if table_name in ("enterprise", "establishment", "branch"):
        pk_col = {"enterprise": "enterprise_number", "establishment": "establishment_number", "branch": "id"}[table_name]
        pk_csv = {"enterprise": "EnterpriseNumber", "establishment": "EstablishmentNumber", "branch": "Id"}[table_name]
        batch = []
        for row in reader:
            batch.append(strip_dots(row[pk_csv]))
            if len(batch) >= BATCH_SIZE:
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(f"DELETE FROM {table_name} WHERE {pk_col} IN ({placeholders})", tuple(batch))
                del_count += len(batch)
                batch.clear()
        if batch:
            placeholders = ",".join(["%s"] * len(batch))
            cur.execute(f"DELETE FROM {table_name} WHERE {pk_col} IN ({placeholders})", tuple(batch))
            del_count += len(batch)
    elif table_name == "code":
        pass  # Full replacement
    else:
        entity_col = "EntityNumber"
        numbers = set()
        for row in reader:
            numbers.add(strip_dots(row[entity_col]))
        numbers = list(numbers)
        for i in range(0, len(numbers), BATCH_SIZE):
            chunk = numbers[i:i + BATCH_SIZE]
            placeholders = ",".join(["%s"] * len(chunk))
            cur.execute(f"DELETE FROM {table_name} WHERE entity_number IN ({placeholders})", tuple(chunk))
            del_count += len(chunk)

    return del_count


def _batch_insert(cur, sql, reader, row_mapper):
    """Batch-insert CSV rows using executemany. Returns row count."""
    count = 0
    batch = []
    for row in reader:
        batch.append(row_mapper(row))
        if len(batch) >= BATCH_SIZE:
            cur.executemany(sql, batch)
            count += len(batch)
            batch.clear()
    if batch:
        cur.executemany(sql, batch)
        count += len(batch)
    return count


def apply_inserts(cur, zf, filename, table_name):
    """Insert rows from an insert CSV using batched executemany."""
    reader = open_csv_from_zip(zf, filename)

    if table_name == "enterprise":
        return _batch_insert(cur, """
            INSERT INTO enterprise (enterprise_number, status, juridical_situation, type_of_enterprise, juridical_form, juridical_form_cac, start_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (enterprise_number) DO UPDATE SET
                status = EXCLUDED.status, juridical_situation = EXCLUDED.juridical_situation,
                type_of_enterprise = EXCLUDED.type_of_enterprise, juridical_form = EXCLUDED.juridical_form,
                juridical_form_cac = EXCLUDED.juridical_form_cac, start_date = EXCLUDED.start_date
        """, reader, lambda r: (
            strip_dots(r["EnterpriseNumber"]), r["Status"], r["JuridicalSituation"],
            r["TypeOfEnterprise"], r.get("JuridicalForm") or None,
            r.get("JuridicalFormCAC") or None, convert_date(r["StartDate"])
        ))

    if table_name == "denomination":
        return _batch_insert(cur, """
            INSERT INTO denomination (entity_number, language, type_of_denomination, denomination)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, reader, lambda r: (
            strip_dots(r["EntityNumber"]), r["Language"], r["TypeOfDenomination"], r["Denomination"]
        ))

    if table_name == "address":
        return _batch_insert(cur, """
            INSERT INTO address (entity_number, type_of_address, country_nl, country_fr, zipcode, municipality_nl, municipality_fr, street_nl, street_fr, house_number, box, extra_address_info, date_striking_off)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, reader, lambda r: (
            strip_dots(r["EntityNumber"]), r["TypeOfAddress"],
            r.get("CountryNL") or None, r.get("CountryFR") or None,
            r.get("Zipcode") or None, r.get("MunicipalityNL") or None,
            r.get("MunicipalityFR") or None, r.get("StreetNL") or None,
            r.get("StreetFR") or None, r.get("HouseNumber") or None,
            r.get("Box") or None, r.get("ExtraAddressInfo") or None,
            convert_date(r.get("DateStrikingOff", "")) or None
        ))

    if table_name == "activity":
        return _batch_insert(cur, """
            INSERT INTO activity (entity_number, activity_group, nace_version, nace_code, classification)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, reader, lambda r: (
            strip_dots(r["EntityNumber"]), r["ActivityGroup"],
            r["NaceVersion"], r["NaceCode"], r["Classification"]
        ))

    if table_name == "contact":
        return _batch_insert(cur, """
            INSERT INTO contact (entity_number, entity_contact, contact_type, value)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, reader, lambda r: (
            strip_dots(r["EntityNumber"]), r["EntityContact"],
            r["ContactType"], r["Value"]
        ))

    if table_name == "establishment":
        return _batch_insert(cur, """
            INSERT INTO establishment (establishment_number, start_date, enterprise_number)
            VALUES (%s, %s, %s)
            ON CONFLICT (establishment_number) DO UPDATE SET
                start_date = EXCLUDED.start_date, enterprise_number = EXCLUDED.enterprise_number
        """, reader, lambda r: (
            strip_dots(r["EstablishmentNumber"]), convert_date(r["StartDate"]),
            strip_dots(r["EnterpriseNumber"])
        ))

    if table_name == "branch":
        return _batch_insert(cur, """
            INSERT INTO branch (id, start_date, enterprise_number)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                start_date = EXCLUDED.start_date, enterprise_number = EXCLUDED.enterprise_number
        """, reader, lambda r: (
            strip_dots(r["Id"]), convert_date(r["StartDate"]),
            strip_dots(r["EnterpriseNumber"])
        ))

    if table_name == "code":
        cur.execute("DELETE FROM code")
        return _batch_insert(cur, """
            INSERT INTO code (category, code, language, description)
            VALUES (%s, %s, %s, %s)
        """, reader, lambda r: (
            r["Category"], r["Code"], r["Language"], r["Description"]
        ))

    return 0


def refresh_company_info():
    """Refresh the company_info table from enterprise + denomination + address + activity.

    DISTINCT ON picks one row per enterprise. Denomination ranking: prefer
    NL (language='2'), then FR ('1'), then unspecified ('0'), then DE/EN.
    Earlier versions only matched language='1' which left ~1.5M companies
    with NULL names — anything filed in NL or with no language tag (Toyota,
    Cargill, Janssen, AB InBev …) showed as a CBE in the UI.

    NACE source: prefer activity_group='006' (RSZ — what the EMPLOYEES
    actually do day-to-day) over '001' (VAT/BTW — how the company files
    taxes). RSZ classification reflects real business activity. The VAT
    classification is often legacy/admin and produces nonsense answers
    like Microsoft → "Market research", Viatris → "Real estate broker",
    or D'Hondt Insurance → "Real estate brokerage". Falls back to '001'
    when no '006' MAIN entry exists (typical for companies without
    employees). Within each group, prefer NACE 2025 over 2008.

    ON CONFLICT uses COALESCE so a refresh never overwrites a good name with
    NULL just because this run couldn't resolve a denomination.
    """
    log.info("Refreshing company_info table...")
    t0 = time.time()
    execute("""
        INSERT INTO company_info (enterprise_number, name, city, zipcode, nace_code)
        SELECT DISTINCT ON (e.enterprise_number)
            e.enterprise_number,
            d.denomination AS name,
            a.municipality_nl AS city,
            a.zipcode,
            act.nace_code
        FROM enterprise e
        LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
            AND d.type_of_denomination = '001'
        LEFT JOIN address a ON a.entity_number = e.enterprise_number
            AND a.type_of_address = 'REGO'
        LEFT JOIN LATERAL (
            -- Pick the best MAIN NACE per enterprise. Prefer activity_group
            -- '006' (RSZ — what employees do = real business activity) over
            -- '001' (VAT — tax filing classification). Within group, prefer
            -- NACE 2025 over 2008 over 2003.
            SELECT nace_code
            FROM activity
            WHERE entity_number = e.enterprise_number
              AND classification = 'MAIN'
              AND activity_group IN ('006', '001')
            ORDER BY
                CASE activity_group WHEN '006' THEN 1 WHEN '001' THEN 2 ELSE 3 END,
                CASE nace_version  WHEN '2025' THEN 1 WHEN '2008' THEN 2
                                   WHEN '2003' THEN 3 ELSE 4 END
            LIMIT 1
        ) act ON TRUE
        WHERE e.status = 'AC'
        ORDER BY e.enterprise_number,
                 CASE d.language
                     WHEN '2' THEN 1
                     WHEN '1' THEN 2
                     WHEN '0' THEN 3
                     WHEN '3' THEN 4
                     WHEN '4' THEN 5
                     ELSE 6
                 END,
                 d.denomination NULLS LAST,
                 a.zipcode NULLS LAST, act.nace_code NULLS LAST
        ON CONFLICT (enterprise_number) DO UPDATE SET
            name     = COALESCE(EXCLUDED.name,     company_info.name),
            city     = COALESCE(EXCLUDED.city,     company_info.city),
            zipcode  = COALESCE(EXCLUDED.zipcode,  company_info.zipcode),
            nace_code = COALESCE(EXCLUDED.nace_code, company_info.nace_code)
    """)
    log.info(f"company_info refreshed in {time.time() - t0:.1f}s")


def refresh_nace_lookup():
    """Re-seed nace_lookup from the canonical KBO `code` table.

    KBO ships every NACE code with NL/FR descriptions in code.csv,
    versioned (Nace2003 / Nace2008 / Nace2025). The display table here
    used to be loaded once at migration time with NACE 2003 descriptions
    — but the activity table records 2008 / 2025 codes, and the codes
    were re-used between revisions for completely different industries
    (`64200` was "Telecommunicatie" in 2003, "Holdings" in 2008). So a
    company tagged 64200 was being shown as a telecom firm.

    Re-seeding from `code` keeps the lookup in lockstep with whatever
    KBO has just shipped. NACE 2025 wins where present, with 2008 as
    the fallback. NACE 2003 is intentionally never the source of truth
    here.

    `company_count` is a separate per-row aggregate maintained elsewhere
    — preserve whatever value already exists rather than zero it on
    every refresh.
    """
    log.info("Refreshing nace_lookup descriptions...")
    t0 = time.time()
    execute("""
        WITH backup AS (
            SELECT nace_code, company_count FROM nace_lookup
        ),
        ranked AS (
            SELECT DISTINCT ON (c.code)
                   c.code AS nace_code,
                   c.description,
                   COALESCE(b.company_count, 0) AS company_count
            FROM code c
            LEFT JOIN backup b ON b.nace_code = c.code
            WHERE c.category IN ('Nace2025', 'Nace2008')
              AND c.language = 'NL'
            ORDER BY c.code,
                     CASE c.category WHEN 'Nace2025' THEN 1
                                     WHEN 'Nace2008' THEN 2
                                     ELSE 3 END
        )
        INSERT INTO nace_lookup (nace_code, description, company_count)
        SELECT nace_code, description, company_count FROM ranked
        ON CONFLICT (nace_code) DO UPDATE SET
            description   = EXCLUDED.description,
            company_count = COALESCE(EXCLUDED.company_count, nace_lookup.company_count)
    """)
    log.info(f"nace_lookup refreshed in {time.time() - t0:.1f}s")


# FK-aware processing order. The KBO schema has:
#   establishment.enterprise_number -> enterprise.enterprise_number  (CASCADE)
#   branch.enterprise_number        -> enterprise.enterprise_number  (CASCADE)
# Other entity-keyed tables (denomination, address, activity, contact)
# have no formal FK because entity_number is polymorphic.
#
# DELETE child rows before parents so a single delta with both an
# establishment and its parent enterprise in delete files doesn't trip
# even on temporarily-inconsistent intermediate states. INSERT parents
# first so child INSERTs don't 23503 if the new parent isn't there yet.
DELETE_ORDER = (
    "contact", "address", "denomination", "activity",  # entity_number — no FK
    "branch", "establishment",                          # FK -> enterprise
    "enterprise",                                       # FK target
    "code",                                             # standalone metadata
)
INSERT_ORDER = (
    "code",
    "enterprise",
    "establishment", "branch",
    "denomination", "address", "activity", "contact",
)


def _count_csv_rows(zf, name):
    """Count data rows in a CSV inside the zip (header excluded)."""
    n = 0
    with zf.open(name) as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
        for _ in reader:
            n += 1
    return n


# Tables whose pre-flight delete count is checked against an env-tunable
# cap. (table_name, max_env_var, default_cap). Tables not listed here
# are unguarded — they're either unbounded by design (code) or have no
# CASCADE consequences (denomination/address/activity/contact, which
# are entity_number-keyed and not referenced by other tables).
_GUARDED_DELETE_TABLES = (
    ("enterprise",    KBO_MAX_ENTERPRISE_DELETE),
    ("establishment", KBO_MAX_ESTABLISHMENT_DELETE),
    ("branch",        KBO_MAX_BRANCH_DELETE),
)


def _check_delete_caps(zf, delete_files, extract_number):
    """Pre-flight guard. Counts deletes for each guarded table; returns
    True if all are within their caps, False if any exceed (and logs
    the offender so the operator can investigate or raise the cap).
    """
    for table, cap in _GUARDED_DELETE_TABLES:
        name = delete_files.get(table)
        if not name:
            continue
        n = _count_csv_rows(zf, name)
        if n > cap:
            log.error(
                "Extract %d wants to delete %d rows from '%s' (cap=%d). "
                "Aborting before commit. If this is intentional, raise "
                "the corresponding KBO_MAX_*_DELETE env var in "
                "/opt/leadpeek/.env.production and re-run.",
                extract_number, n, table, cap,
            )
            return False
    return True


def process_zip(zip_path):
    """Apply a single update ZIP to the PostgreSQL database atomically.

    Phases:
      1. Sanity guard — count enterprise deletes; abort if > threshold.
      2. DELETE child rows first (FK-safe even if CASCADE is dropped).
      3. INSERT parent rows first.
      4. Stamp kbo_extract_log inside the same transaction.
    """
    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # Read meta
        if "meta.csv" not in names:
            log.warning(f"No meta.csv in {zip_path} — skipping")
            return False

        with zf.open("meta.csv") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
            meta = {row["Variable"]: row["Value"] for row in reader}

        extract_number = int(meta.get("ExtractNumber", 0))

        # Check if already applied (outside transaction — read-only)
        row = fetch_one("SELECT 1 AS done FROM kbo_extract_log WHERE extract_number = %s", (extract_number,))
        if row:
            log.info(f"Extract {extract_number} already applied — skipping")
            return False

        log.info(f"Applying extract {extract_number}...")

        # Group files
        delete_files = {}
        insert_files = {}
        for name in names:
            if name == "meta.csv":
                continue
            base = os.path.basename(name).lower()
            if base.endswith("_delete.csv"):
                table = base[:-len("_delete.csv")]
                delete_files[table] = name
            elif base.endswith("_insert.csv"):
                table = base[:-len("_insert.csv")]
                insert_files[table] = name
            elif base == "code.csv":
                insert_files["code"] = name

        # Phase 1: row-count guards. Refuse to apply a delta whose
        # delete counts exceed any of the per-table caps. Protects
        # against a buggy KBO release or a malformed download
        # cascade-wiping huge swaths of historical data.
        if not _check_delete_caps(zf, delete_files, extract_number):
            return False

        # Process all tables in a single transaction for atomicity
        with transaction() as (conn, cur):
            # Phase 2: DELETEs in child-first order
            for table in DELETE_ORDER:
                if table in delete_files and table in TABLE_MAP:
                    t1 = time.time()
                    n = apply_deletes(cur, zf, delete_files[table], table)
                    log.info(f"  DEL {table}: -{n:,} ({time.time() - t1:.1f}s)")
            # Phase 3: INSERTs in parent-first order
            for table in INSERT_ORDER:
                if table in insert_files and table in TABLE_MAP:
                    t1 = time.time()
                    n = apply_inserts(cur, zf, insert_files[table], table)
                    log.info(f"  INS {table}: +{n:,} ({time.time() - t1:.1f}s)")

            # Log extract as applied (within same transaction)
            cur.execute(
                "INSERT INTO kbo_extract_log (extract_number, extract_type) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (extract_number, meta.get("ExtractType", "update")),
            )
        return True


def main():
    log.info("=" * 60)
    log.info("KBO Daily Update — starting")
    log.info("=" * 60)

    last_extract = get_last_extract()
    log.info(f"Last applied extract: {last_extract}")

    # Authenticate ONCE, reuse the session for discovery + downloads.
    # Hard-fail if credentials missing or login rejected — do not let
    # this regress to the silent "0 updates" trap that lost 22 days.
    try:
        session = authed_session()
    except KBOAuthError as e:
        log.error("KBO authentication failed: %s", e)
        sys.exit(2)

    # Discover available updates
    try:
        available = discover_update_zips(session=session)
    except Exception as e:
        log.error("KBO discovery failed: %s", e)
        sys.exit(3)
    new_updates = [(num, url) for num, url in available if num > last_extract]

    if not new_updates:
        log.info("No new updates available")
        return

    log.info(f"Found {len(new_updates)} new update(s) to apply")

    with tempfile.TemporaryDirectory() as tmpdir:
        applied = 0
        for num, url in new_updates:
            try:
                zip_path = download_zip(url, tmpdir, session=session)
                if process_zip(zip_path):
                    applied += 1
                # Clean up downloaded file
                os.remove(zip_path)
                time.sleep(1)  # Be nice to KBO servers
            except Exception as e:
                log.error(f"Failed to process extract {num}: {e}")
                continue

        if applied > 0:
            # Refresh nace_lookup BEFORE company_info — the description table
            # is read-only metadata, so applying it first keeps a refreshed
            # company_info pointing to fresh descriptions even if the run
            # crashes in between.
            refresh_nace_lookup()
            refresh_company_info()
            # Update snapshot date in meta
            execute(
                "INSERT INTO meta (variable, value) VALUES ('SnapshotDate', %s) ON CONFLICT (variable) DO UPDATE SET value = EXCLUDED.value",
                (datetime.now().strftime("%d-%m-%Y"),),
            )

    log.info(f"Done. Applied {applied}/{len(new_updates)} updates")


if __name__ == "__main__":
    main()
