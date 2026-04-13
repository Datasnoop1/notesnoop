"""Apply KBO daily update ZIPs to the SQLite database.

Update ZIPs contain *_delete.csv and *_insert.csv pairs for each table.
The insert file contains ALL current rows for affected entities.

Usage:
    python src/kbo_updater.py data/KboOpenData_*_Update.zip [...]
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

BATCH_SIZE = 10_000

# Map from CSV filename prefix → (table, primary_key_columns)
# Used to extract entity numbers from delete files
TABLE_MAP = {
    "enterprise":    ("enterprise",    ["EnterpriseNumber"]),
    "establishment": ("establishment", ["EstablishmentNumber"]),
    "denomination":  ("denomination",  ["EntityNumber", "Language", "TypeOfDenomination"]),
    "address":       ("address",       ["EntityNumber", "TypeOfAddress"]),
    "activity":      ("activity",      ["EntityNumber", "ActivityGroup", "NaceVersion", "NaceCode", "Classification"]),
    "contact":       ("contact",       ["EntityNumber", "EntityContact", "ContactType", "Value"]),
    "branch":        ("branch",        ["Id"]),
    "code":          ("code",          ["Category", "Code", "Language"]),
}

# Tables where we delete by EntityNumber/EnterpriseNumber (not full PK)
# i.e. delete all rows for the entity before reinserting
ENTITY_DELETE_TABLES = {
    "denomination", "address", "activity", "contact",
}


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def strip_dots(number):
    if number:
        return number.replace(".", "")
    return number


def convert_date(date_str):
    if not date_str or not date_str.strip():
        return ""
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", date_str.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return date_str


def open_csv(zf, filename):
    f = zf.open(filename)
    text = io.TextIOWrapper(f, encoding="utf-8")
    reader = csv.DictReader(text)
    return reader


def get_entity_column(table_name):
    """Return the column name that holds the entity/enterprise number for a table."""
    if table_name == "enterprise":
        return "EnterpriseNumber"
    elif table_name == "establishment":
        return "EnterpriseNumber"
    elif table_name == "branch":
        return "EnterpriseNumber"
    else:
        return "EntityNumber"


def apply_deletes(conn, zf, filename, table_name):
    """Delete rows from table based on entity numbers in a delete CSV."""
    reader = open_csv(zf, filename)
    entity_col = get_entity_column(table_name)
    db_col = "enterprise_number" if entity_col == "EnterpriseNumber" else "entity_number"

    if table_name in ("enterprise", "establishment", "branch"):
        # Delete by primary key
        pk_col = {
            "enterprise": "enterprise_number",
            "establishment": "establishment_number",
            "branch": "id",
        }[table_name]
        pk_csv = {
            "enterprise": "EnterpriseNumber",
            "establishment": "EstablishmentNumber",
            "branch": "Id",
        }[table_name]
        batch = []
        for row in reader:
            batch.append((strip_dots(row[pk_csv]),))
            if len(batch) >= BATCH_SIZE:
                conn.executemany(f"DELETE FROM {table_name} WHERE {pk_col} = ?", batch)
                batch.clear()
        if batch:
            conn.executemany(f"DELETE FROM {table_name} WHERE {pk_col} = ?", batch)
    elif table_name == "code":
        # code.csv in updates is always the full table — handled separately
        pass
    else:
        # Delete all rows for these entity numbers (denomination, address, activity, contact)
        numbers = set()
        for row in reader:
            numbers.add(strip_dots(row[entity_col]))
        # Use IN clause in batches
        numbers = list(numbers)
        for i in range(0, len(numbers), BATCH_SIZE):
            chunk = numbers[i:i + BATCH_SIZE]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(
                f"DELETE FROM {table_name} WHERE entity_number IN ({placeholders})",
                chunk,
            )


def apply_inserts(conn, zf, filename, table_name):
    """Insert rows from an insert CSV into the table."""
    reader = open_csv(zf, filename)
    count = 0

    if table_name == "enterprise":
        batch = []
        for row in reader:
            batch.append((
                strip_dots(row["EnterpriseNumber"]),
                row["Status"],
                row["JuridicalSituation"],
                row["TypeOfEnterprise"],
                row["JuridicalForm"] or None,
                row["JuridicalFormCAC"] or None,
                convert_date(row["StartDate"]),
            ))
            if len(batch) >= BATCH_SIZE:
                conn.executemany("INSERT OR REPLACE INTO enterprise VALUES (?,?,?,?,?,?,?)", batch)
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT OR REPLACE INTO enterprise VALUES (?,?,?,?,?,?,?)", batch)
            count += len(batch)

    elif table_name == "establishment":
        batch = []
        for row in reader:
            batch.append((
                strip_dots(row["EstablishmentNumber"]),
                convert_date(row["StartDate"]),
                strip_dots(row["EnterpriseNumber"]),
            ))
            if len(batch) >= BATCH_SIZE:
                conn.executemany("INSERT OR REPLACE INTO establishment VALUES (?,?,?)", batch)
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT OR REPLACE INTO establishment VALUES (?,?,?)", batch)
            count += len(batch)

    elif table_name == "denomination":
        batch = []
        for row in reader:
            batch.append((
                strip_dots(row["EntityNumber"]),
                row["Language"],
                row["TypeOfDenomination"],
                row["Denomination"],
            ))
            if len(batch) >= BATCH_SIZE:
                conn.executemany("INSERT OR REPLACE INTO denomination VALUES (?,?,?,?)", batch)
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT OR REPLACE INTO denomination VALUES (?,?,?,?)", batch)
            count += len(batch)

    elif table_name == "address":
        batch = []
        for row in reader:
            batch.append((
                strip_dots(row["EntityNumber"]),
                row["TypeOfAddress"],
                row["CountryNL"] or None,
                row["CountryFR"] or None,
                row["Zipcode"] or None,
                row["MunicipalityNL"] or None,
                row["MunicipalityFR"] or None,
                row["StreetNL"] or None,
                row["StreetFR"] or None,
                row["HouseNumber"] or None,
                row["Box"] or None,
                row["ExtraAddressInfo"] or None,
                convert_date(row["DateStrikingOff"]) or None,
            ))
            if len(batch) >= BATCH_SIZE:
                conn.executemany(
                    "INSERT OR REPLACE INTO address VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch
                )
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany(
                "INSERT OR REPLACE INTO address VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch
            )
            count += len(batch)

    elif table_name == "activity":
        batch = []
        for row in reader:
            batch.append((
                strip_dots(row["EntityNumber"]),
                row["ActivityGroup"],
                row["NaceVersion"],
                row["NaceCode"],
                row["Classification"],
            ))
            if len(batch) >= BATCH_SIZE:
                conn.executemany("INSERT OR REPLACE INTO activity VALUES (?,?,?,?,?)", batch)
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT OR REPLACE INTO activity VALUES (?,?,?,?,?)", batch)
            count += len(batch)

    elif table_name == "contact":
        batch = []
        for row in reader:
            batch.append((
                strip_dots(row["EntityNumber"]),
                row["EntityContact"],
                row["ContactType"],
                row["Value"],
            ))
            if len(batch) >= BATCH_SIZE:
                conn.executemany("INSERT OR REPLACE INTO contact VALUES (?,?,?,?)", batch)
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT OR REPLACE INTO contact VALUES (?,?,?,?)", batch)
            count += len(batch)

    elif table_name == "branch":
        batch = []
        for row in reader:
            batch.append((
                strip_dots(row["Id"]),
                convert_date(row["StartDate"]),
                strip_dots(row["EnterpriseNumber"]),
            ))
            if len(batch) >= BATCH_SIZE:
                conn.executemany("INSERT OR REPLACE INTO branch VALUES (?,?,?)", batch)
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT OR REPLACE INTO branch VALUES (?,?,?)", batch)
            count += len(batch)

    elif table_name == "code":
        # Full replacement
        conn.execute("DELETE FROM code")
        batch = []
        for row in reader:
            batch.append((row["Category"], row["Code"], row["Language"], row["Description"]))
            if len(batch) >= BATCH_SIZE:
                conn.executemany("INSERT INTO code VALUES (?,?,?,?)", batch)
                count += len(batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT INTO code VALUES (?,?,?,?)", batch)
            count += len(batch)

    return count


def process_zip(conn, zip_path):
    """Apply a single update ZIP to the database."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        # Read meta to get extract number
        if "meta.csv" in names:
            with zf.open("meta.csv") as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                meta = {row["Variable"]: row["Value"] for row in reader}
            extract_number = int(meta.get("ExtractNumber", 0))
            extract_type = meta.get("ExtractType", "update")
        else:
            log(f"  WARNING: no meta.csv in {zip_path}")
            extract_number = 0
            extract_type = "update"

        # Check if already applied
        already = conn.execute(
            "SELECT 1 FROM kbo_extract_log WHERE extract_number = ?", (extract_number,)
        ).fetchone()
        if already:
            log(f"  Extract {extract_number} already applied — skipping")
            return False

        log(f"  Applying extract {extract_number} ({extract_type})")

        # Group files by table name
        # Expected naming: <table>_delete.csv / <table>_insert.csv
        # or just: <table>.csv (for code full replacement)
        delete_files = {}
        insert_files = {}
        for name in names:
            if name == "meta.csv":
                continue
            base = os.path.basename(name).lower()
            if base.endswith("_delete.csv"):
                table = base[: -len("_delete.csv")]
                delete_files[table] = name
            elif base.endswith("_insert.csv"):
                table = base[: -len("_insert.csv")]
                insert_files[table] = name
            elif base == "code.csv":
                insert_files["code"] = name

        # Process in order: deletes first, then inserts
        all_tables = sorted(set(list(delete_files) + list(insert_files)))
        for table in all_tables:
            if table not in TABLE_MAP:
                log(f"  WARNING: unknown table '{table}' — skipping")
                continue

            t1 = time.time()
            del_count = 0
            ins_count = 0

            if table in delete_files:
                apply_deletes(conn, zf, delete_files[table], table)

            if table in insert_files:
                ins_count = apply_inserts(conn, zf, insert_files[table], table)

            log(f"  {table}: +{ins_count:,} rows ({time.time() - t1:.1f}s)")

        conn.execute(
            "INSERT OR REPLACE INTO kbo_extract_log(extract_number, extract_type) VALUES (?, ?)",
            (extract_number, extract_type),
        )
        conn.commit()
        return True


def main():
    parser = argparse.ArgumentParser(description="Apply KBO update ZIPs to SQLite")
    parser.add_argument("zipfiles", nargs="+", help="KBO update ZIP file(s)")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        log(f"ERROR: database not found at {db_path}")
        log("Run scripts/init_db.py and src/kbo_loader.py first")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -32000")
    conn.execute("PRAGMA foreign_keys = OFF")

    # Sort ZIPs by extract number (embedded in filename) to apply in order
    zip_paths = sorted(
        [os.path.abspath(p) for p in args.zipfiles],
        key=lambda p: re.search(r"_(\d+)_", os.path.basename(p)) and
                      int(re.search(r"_(\d+)_", os.path.basename(p)).group(1)) or 0,
    )

    applied = 0
    t0 = time.time()
    for zip_path in zip_paths:
        log(f"Processing: {os.path.basename(zip_path)}")
        if not os.path.exists(zip_path):
            log(f"  ERROR: file not found — skipping")
            continue
        try:
            if process_zip(conn, zip_path):
                applied += 1
        except Exception as e:
            log(f"  ERROR processing {zip_path}: {e}")
            conn.rollback()

    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    log(f"Done. Applied {applied}/{len(zip_paths)} updates in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
