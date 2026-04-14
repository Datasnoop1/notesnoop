"""KBO daily updater — downloads and applies KBO update ZIPs to PostgreSQL.

Downloads the latest update ZIPs from kbopub.economie.fgov.be,
applies deletes + inserts to the live database, and refreshes company_info.

Run daily via cron:
  0 6 * * * cd /opt/leadpeek/backend && python kbo_daily_update.py >> /var/log/kbo_update.log 2>&1
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
from db import get_conn, execute, fetch_one, fetch_all

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
            "User-Agent": "Mozilla/5.0 (DataPeak KBO Updater)"
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
    filename = url.split("/")[-1]
    dest = os.path.join(dest_dir, filename)
    log.info(f"Downloading {filename}...")
    resp = requests.get(url, timeout=120, stream=True, headers={
        "User-Agent": "Mozilla/5.0 (DataPeak KBO Updater)"
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


def apply_deletes(zf, filename, table_name):
    """Delete rows from table based on entity numbers in a delete CSV."""
    import zipfile
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
                execute(f"DELETE FROM {table_name} WHERE {pk_col} IN ({placeholders})", tuple(batch))
                del_count += len(batch)
                batch.clear()
        if batch:
            placeholders = ",".join(["%s"] * len(batch))
            execute(f"DELETE FROM {table_name} WHERE {pk_col} IN ({placeholders})", tuple(batch))
            del_count += len(batch)
    elif table_name == "code":
        pass  # Full replacement
    else:
        # Delete all rows for affected entity numbers
        entity_col = "EntityNumber"
        numbers = set()
        for row in reader:
            numbers.add(strip_dots(row[entity_col]))
        numbers = list(numbers)
        for i in range(0, len(numbers), BATCH_SIZE):
            chunk = numbers[i:i + BATCH_SIZE]
            placeholders = ",".join(["%s"] * len(chunk))
            execute(f"DELETE FROM {table_name} WHERE entity_number IN ({placeholders})", tuple(chunk))
            del_count += len(chunk)

    return del_count


def apply_inserts(zf, filename, table_name):
    """Insert rows from an insert CSV into the table."""
    reader = open_csv_from_zip(zf, filename)
    count = 0

    if table_name == "enterprise":
        for row in reader:
            execute("""
                INSERT INTO enterprise (enterprise_number, status, juridical_situation, type_of_enterprise, juridical_form, juridical_form_cac, start_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (enterprise_number) DO UPDATE SET
                    status = EXCLUDED.status, juridical_situation = EXCLUDED.juridical_situation,
                    type_of_enterprise = EXCLUDED.type_of_enterprise, juridical_form = EXCLUDED.juridical_form,
                    juridical_form_cac = EXCLUDED.juridical_form_cac, start_date = EXCLUDED.start_date
            """, (strip_dots(row["EnterpriseNumber"]), row["Status"], row["JuridicalSituation"],
                  row["TypeOfEnterprise"], row.get("JuridicalForm") or None,
                  row.get("JuridicalFormCAC") or None, convert_date(row["StartDate"])))
            count += 1

    elif table_name == "denomination":
        for row in reader:
            execute("""
                INSERT INTO denomination (entity_number, language, type_of_denomination, denomination)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (strip_dots(row["EntityNumber"]), row["Language"], row["TypeOfDenomination"], row["Denomination"]))
            count += 1

    elif table_name == "address":
        for row in reader:
            execute("""
                INSERT INTO address (entity_number, type_of_address, country_nl, country_fr, zipcode, municipality_nl, municipality_fr, street_nl, street_fr, house_number, box, extra_address_info, date_striking_off)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (strip_dots(row["EntityNumber"]), row["TypeOfAddress"],
                  row.get("CountryNL") or None, row.get("CountryFR") or None,
                  row.get("Zipcode") or None, row.get("MunicipalityNL") or None,
                  row.get("MunicipalityFR") or None, row.get("StreetNL") or None,
                  row.get("StreetFR") or None, row.get("HouseNumber") or None,
                  row.get("Box") or None, row.get("ExtraAddressInfo") or None,
                  convert_date(row.get("DateStrikingOff", "")) or None))
            count += 1

    elif table_name == "activity":
        for row in reader:
            execute("""
                INSERT INTO activity (entity_number, activity_group, nace_version, nace_code, classification)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (strip_dots(row["EntityNumber"]), row["ActivityGroup"],
                  row["NaceVersion"], row["NaceCode"], row["Classification"]))
            count += 1

    elif table_name == "contact":
        for row in reader:
            execute("""
                INSERT INTO contact (entity_number, entity_contact, contact_type, value)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (strip_dots(row["EntityNumber"]), row["EntityContact"],
                  row["ContactType"], row["Value"]))
            count += 1

    elif table_name == "establishment":
        for row in reader:
            execute("""
                INSERT INTO establishment (establishment_number, start_date, enterprise_number)
                VALUES (%s, %s, %s)
                ON CONFLICT (establishment_number) DO UPDATE SET
                    start_date = EXCLUDED.start_date, enterprise_number = EXCLUDED.enterprise_number
            """, (strip_dots(row["EstablishmentNumber"]), convert_date(row["StartDate"]),
                  strip_dots(row["EnterpriseNumber"])))
            count += 1

    elif table_name == "branch":
        for row in reader:
            execute("""
                INSERT INTO branch (id, start_date, enterprise_number)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    start_date = EXCLUDED.start_date, enterprise_number = EXCLUDED.enterprise_number
            """, (strip_dots(row["Id"]), convert_date(row["StartDate"]),
                  strip_dots(row["EnterpriseNumber"])))
            count += 1

    elif table_name == "code":
        execute("DELETE FROM code")
        for row in reader:
            execute("""
                INSERT INTO code (category, code, language, description)
                VALUES (%s, %s, %s, %s)
            """, (row["Category"], row["Code"], row["Language"], row["Description"]))
            count += 1

    return count


def refresh_company_info():
    """Refresh the company_info table from enterprise + denomination + address + activity."""
    log.info("Refreshing company_info table...")
    t0 = time.time()
    execute("""
        INSERT INTO company_info (enterprise_number, name, city, zipcode, nace_code)
        SELECT
            e.enterprise_number,
            d.denomination AS name,
            a.municipality_nl AS city,
            a.zipcode,
            act.nace_code
        FROM enterprise e
        LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
            AND d.type_of_denomination = '001' AND d.language = '1'
        LEFT JOIN address a ON a.entity_number = e.enterprise_number
            AND a.type_of_address = 'REGO'
        LEFT JOIN (
            SELECT entity_number, nace_code
            FROM activity
            WHERE activity_group = '001' AND nace_version = '2008' AND classification = 'MAIN'
        ) act ON act.entity_number = e.enterprise_number
        WHERE e.status = 'AC'
        ON CONFLICT (enterprise_number) DO UPDATE SET
            name = EXCLUDED.name,
            city = EXCLUDED.city,
            zipcode = EXCLUDED.zipcode,
            nace_code = EXCLUDED.nace_code
    """)
    log.info(f"company_info refreshed in {time.time() - t0:.1f}s")


def process_zip(zip_path):
    """Apply a single update ZIP to the PostgreSQL database."""
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

        # Check if already applied
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

        all_tables = sorted(set(list(delete_files) + list(insert_files)))
        for table in all_tables:
            if table not in TABLE_MAP:
                log.warning(f"Unknown table '{table}' — skipping")
                continue

            t1 = time.time()
            del_count = 0
            ins_count = 0

            if table in delete_files:
                del_count = apply_deletes(zf, delete_files[table], table)

            if table in insert_files:
                ins_count = apply_inserts(zf, insert_files[table], table)

            log.info(f"  {table}: -{del_count:,} +{ins_count:,} ({time.time() - t1:.1f}s)")

        # Log extract as applied
        execute(
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
