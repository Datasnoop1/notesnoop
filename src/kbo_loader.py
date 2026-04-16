"""Parse a KBO full ZIP into SQLite.

Usage:
    python src/kbo_loader.py data/KboOpenData_*_Full.zip
"""

import argparse
import csv
import io
import os
import re
import sqlite3
import sys
import time
import zipfile
from datetime import datetime

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
SCHEMA_SQL = os.path.join(os.path.dirname(__file__), "schema.sql")

BATCH_SIZE = 50_000


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def strip_dots(number):
    """Normalize entity/enterprise numbers: remove dots and zero-pad to 10 digits.

    KBO occasionally ships enterprise numbers as 9-digit strings (the leading
    zero dropped). Pad them so joins on enterprise_number remain consistent.
    Establishment numbers are 10 digits; zfill leaves them unchanged.
    Empty / None input is returned unchanged.
    """
    if not number:
        return number
    cleaned = number.replace(".", "")
    if cleaned.isdigit() and len(cleaned) < 10:
        cleaned = cleaned.zfill(10)
    return cleaned


def convert_date(date_str):
    """Convert dd-mm-yyyy to YYYY-MM-DD. Returns empty string on failure."""
    if not date_str or not date_str.strip():
        return ""
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", date_str.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return date_str


def open_csv(zf, filename):
    """Open a CSV file inside a ZipFile, return a csv.reader."""
    f = zf.open(filename)
    text = io.TextIOWrapper(f, encoding="utf-8")
    reader = csv.reader(text)
    header = next(reader)  # skip header
    return reader, header


def load_meta(conn, zf):
    """Load meta.csv and return the extract number."""
    reader, _ = open_csv(zf, "meta.csv")
    extract_number = None
    for row in reader:
        variable, value = row[0], row[1]
        conn.execute(
            "INSERT OR REPLACE INTO meta(variable, value) VALUES (?, ?)",
            (variable, value),
        )
        if variable == "ExtractNumber":
            extract_number = int(value)
    return extract_number


def load_enterprise(conn, zf):
    reader, _ = open_csv(zf, "enterprise.csv")
    batch = []
    count = 0
    for row in reader:
        batch.append((
            strip_dots(row[0]),     # EnterpriseNumber
            row[1],                 # Status
            row[2],                 # JuridicalSituation
            row[3],                 # TypeOfEnterprise
            row[4] or None,         # JuridicalForm
            row[5] or None,         # JuridicalFormCAC
            convert_date(row[6]),   # StartDate
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO enterprise VALUES (?,?,?,?,?,?,?)", batch
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO enterprise VALUES (?,?,?,?,?,?,?)", batch
        )
        count += len(batch)
    log(f"  enterprise: {count:,} rows")


def load_establishment(conn, zf):
    reader, _ = open_csv(zf, "establishment.csv")
    batch = []
    count = 0
    for row in reader:
        batch.append((
            strip_dots(row[0]),     # EstablishmentNumber
            convert_date(row[1]),   # StartDate
            strip_dots(row[2]),     # EnterpriseNumber
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO establishment VALUES (?,?,?)", batch
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO establishment VALUES (?,?,?)", batch
        )
        count += len(batch)
    log(f"  establishment: {count:,} rows")


def load_denomination(conn, zf):
    reader, _ = open_csv(zf, "denomination.csv")
    batch = []
    count = 0
    for row in reader:
        batch.append((
            strip_dots(row[0]),     # EntityNumber
            row[1],                 # Language
            row[2],                 # TypeOfDenomination
            row[3],                 # Denomination
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO denomination VALUES (?,?,?,?)", batch
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO denomination VALUES (?,?,?,?)", batch
        )
        count += len(batch)
    log(f"  denomination: {count:,} rows")


def load_address(conn, zf):
    reader, _ = open_csv(zf, "address.csv")
    batch = []
    count = 0
    for row in reader:
        batch.append((
            strip_dots(row[0]),     # EntityNumber
            row[1],                 # TypeOfAddress
            row[2] or None,         # CountryNL
            row[3] or None,         # CountryFR
            row[4] or None,         # Zipcode
            row[5] or None,         # MunicipalityNL
            row[6] or None,         # MunicipalityFR
            row[7] or None,         # StreetNL
            row[8] or None,         # StreetFR
            row[9] or None,         # HouseNumber
            row[10] or None,        # Box
            row[11] or None,        # ExtraAddressInfo
            convert_date(row[12]) or None,  # DateStrikingOff
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO address VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                batch,
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO address VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch
        )
        count += len(batch)
    log(f"  address: {count:,} rows")


def load_activity(conn, zf):
    reader, _ = open_csv(zf, "activity.csv")
    batch = []
    count = 0
    for row in reader:
        batch.append((
            strip_dots(row[0]),     # EntityNumber
            row[1],                 # ActivityGroup
            row[2],                 # NaceVersion
            row[3],                 # NaceCode
            row[4],                 # Classification
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO activity VALUES (?,?,?,?,?)", batch
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO activity VALUES (?,?,?,?,?)", batch
        )
        count += len(batch)
    log(f"  activity: {count:,} rows")


def load_contact(conn, zf):
    reader, _ = open_csv(zf, "contact.csv")
    batch = []
    count = 0
    for row in reader:
        batch.append((
            strip_dots(row[0]),     # EntityNumber
            row[1],                 # EntityContact
            row[2],                 # ContactType
            row[3],                 # Value
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO contact VALUES (?,?,?,?)", batch
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO contact VALUES (?,?,?,?)", batch
        )
        count += len(batch)
    log(f"  contact: {count:,} rows")


def load_branch(conn, zf):
    reader, _ = open_csv(zf, "branch.csv")
    batch = []
    count = 0
    for row in reader:
        batch.append((
            strip_dots(row[0]),     # Id
            convert_date(row[1]),   # StartDate
            strip_dots(row[2]),     # EnterpriseNumber
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO branch VALUES (?,?,?)", batch
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO branch VALUES (?,?,?)", batch
        )
        count += len(batch)
    log(f"  branch: {count:,} rows")


def load_code(conn, zf):
    reader, _ = open_csv(zf, "code.csv")
    batch = []
    count = 0
    for row in reader:
        batch.append((
            row[0],     # Category
            row[1],     # Code
            row[2],     # Language
            row[3],     # Description
        ))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO code VALUES (?,?,?,?)", batch
            )
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO code VALUES (?,?,?,?)", batch
        )
        count += len(batch)
    log(f"  code: {count:,} rows")


def main():
    parser = argparse.ArgumentParser(description="Load KBO full ZIP into SQLite")
    parser.add_argument("zipfile", help="Path to KBO full ZIP file")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
    args = parser.parse_args()

    zip_path = os.path.abspath(args.zipfile)
    db_path = os.path.abspath(args.db)

    if not os.path.exists(zip_path):
        log(f"ERROR: ZIP file not found: {zip_path}")
        sys.exit(1)

    # Ensure DB directory exists and schema is applied
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")  # 64MB cache
    conn.execute("PRAGMA foreign_keys = OFF")    # OFF during bulk load for speed

    with open(SCHEMA_SQL, "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    log(f"Loading KBO full ZIP: {zip_path}")
    t0 = time.time()

    with zipfile.ZipFile(zip_path) as zf:
        # Load meta first to get extract number
        extract_number = load_meta(conn, zf)
        log(f"  Extract number: {extract_number}")
        conn.commit()

        # Load tables in dependency order
        loaders = [
            ("enterprise", load_enterprise),
            ("establishment", load_establishment),
            ("denomination", load_denomination),
            ("address", load_address),
            ("activity", load_activity),
            ("contact", load_contact),
            ("branch", load_branch),
            ("code", load_code),
        ]

        for name, loader in loaders:
            t1 = time.time()
            loader(conn, zf)
            conn.commit()
            log(f"  {name} committed ({time.time() - t1:.1f}s)")

    # Record this extract
    if extract_number is not None:
        conn.execute(
            "INSERT OR REPLACE INTO kbo_extract_log(extract_number, extract_type) VALUES (?, 'full')",
            (extract_number,),
        )
        conn.commit()

    # Re-enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    elapsed = time.time() - t0
    log(f"Done. Total time: {elapsed:.0f}s")


if __name__ == "__main__":
    main()
