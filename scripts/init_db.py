"""Create the Belgian company database from schema.sql."""

import argparse
import os
import sqlite3
import sys

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")
SCHEMA_SQL = os.path.join(os.path.dirname(__file__), "..", "src", "schema.sql")


def main():
    parser = argparse.ArgumentParser(description="Initialize the Belgian company database")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database file")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    with open(SCHEMA_SQL, "r", encoding="utf-8") as f:
        schema = f.read()

    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.close()

    print(f"Database initialized at {db_path}")


if __name__ == "__main__":
    main()
