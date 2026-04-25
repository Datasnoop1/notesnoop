"""KBO daily updater — downloads and applies KBO update ZIPs to PostgreSQL.

Downloads the latest update ZIPs from kbopub.economie.fgov.be,
applies deletes + inserts to the live database, and refreshes company_info.

Run daily via cron:
  0 6 * * * cd /opt/datasnoop/backend && python kbo_daily_update.py >> /var/log/kbo_update.log 2>&1
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

KBO_BASE = "https://kbopub.economie.fgov.be/kbo-open-data/login"
KBO_DATA = "https://kbopub.economie.fgov.be/kbo-open-data/affiliation/xml/files"
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


def discover_update_zips():
    """Scrape the KBO open data page for available update ZIP URLs."""
    log.info("Discovering available update ZIPs from KBO portal...")
    try:
        session = requests.Session()
        # The KBO open data portal requires a session
        resp = session.get(KBO_DATA, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Datasnoop KBO Updater)"
        })
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        zips = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "Update" in href and href.endswith(".zip"):
                # Extract extract number from filename
                match = re.search(r"_(\d+)_", href)
                if match:
                    num = int(match.group(1))
                    full_url = href if href.startswith("http") else f"https://kbopub.economie.fgov.be{href}"
                    zips.append((num, full_url))

        zips.sort(key=lambda x: x[0])
        log.info(f"Found {len(zips)} update ZIPs on portal")
        return zips
    except Exception as e:
        log.error(f"Failed to discover update ZIPs: {e}")
        return []


def download_zip(url, dest_dir):
    """Download a ZIP file to a temporary directory."""
    filename = os.path.basename(url.rstrip("/"))
    dest = os.path.join(dest_dir, filename)
    log.info(f"Downloading {filename}...")
    resp = requests.get(url, timeout=120, stream=True, headers={
        "User-Agent": "Mozilla/5.0 (Datasnoop KBO Updater)"
    })
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size_mb = os.path.getsize(dest) / 1024 / 1024
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
        LEFT JOIN (
            SELECT entity_number, nace_code
            FROM activity
            WHERE activity_group = '001' AND nace_version = '2008' AND classification = 'MAIN'
        ) act ON act.entity_number = e.enterprise_number
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


def process_zip(zip_path):
    """Apply a single update ZIP to the PostgreSQL database atomically."""
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

        # Process all tables in a single transaction for atomicity
        with transaction() as (conn, cur):
            all_tables = sorted(set(list(delete_files) + list(insert_files)))
            for table in all_tables:
                if table not in TABLE_MAP:
                    log.warning(f"Unknown table '{table}' — skipping")
                    continue

                t1 = time.time()
                del_count = 0
                ins_count = 0

                if table in delete_files:
                    del_count = apply_deletes(cur, zf, delete_files[table], table)

                if table in insert_files:
                    ins_count = apply_inserts(cur, zf, insert_files[table], table)

                log.info(f"  {table}: -{del_count:,} +{ins_count:,} ({time.time() - t1:.1f}s)")

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

    # Discover available updates
    available = discover_update_zips()
    new_updates = [(num, url) for num, url in available if num > last_extract]

    if not new_updates:
        log.info("No new updates available")
        return

    log.info(f"Found {len(new_updates)} new update(s) to apply")

    with tempfile.TemporaryDirectory() as tmpdir:
        applied = 0
        for num, url in new_updates:
            try:
                zip_path = download_zip(url, tmpdir)
                if process_zip(zip_path):
                    applied += 1
                # Clean up downloaded file
                os.remove(zip_path)
                time.sleep(1)  # Be nice to KBO servers
            except Exception as e:
                log.error(f"Failed to process extract {num}: {e}")
                continue

        if applied > 0:
            # Refresh company_info after all updates
            refresh_company_info()
            # Update snapshot date in meta
            execute(
                "INSERT INTO meta (variable, value) VALUES ('SnapshotDate', %s) ON CONFLICT (variable) DO UPDATE SET value = EXCLUDED.value",
                (datetime.now().strftime("%d-%m-%Y"),),
            )

    log.info(f"Done. Applied {applied}/{len(new_updates)} updates")


if __name__ == "__main__":
    main()
