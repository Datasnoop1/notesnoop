"""Example PE screening queries against the Belgian company database.

Results are printed as formatted tables. Use --export to save to CSV.

Usage:
    python scripts/screen.py                          # default screen
    python scripts/screen.py --nace 26               # NACE prefix filter
    python scripts/screen.py --province VAN           # zipcode prefix
    python scripts/screen.py --revenue-min 5000000 --revenue-max 50000000
    python scripts/screen.py --ebitda-margin-min 10
    python scripts/screen.py --fte-min 20 --fte-max 250
    python scripts/screen.py --leverage-max 4
    python scripts/screen.py --export results.csv
    python scripts/screen.py --summary               # sector benchmarks
"""

import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")

# Belgian province zipcode prefixes
PROVINCE_ZIPCODES = {
    "ANT": ("2", "Antwerpen"),
    "OVL": ("9", "Oost-Vlaanderen"),
    "WVL": ("8", "West-Vlaanderen"),
    "VBR": ("3", "Vlaams-Brabant"),
    "LIM": ("35", "Limburg"),
    "BRU": ("1", "Brussels"),
    "BRA": ("14", "Brabant Wallon"),
    "HAI": ("7", "Hainaut"),
    "LIE": ("4", "Liège"),
    "LUX": ("6", "Luxembourg"),
    "NAM": ("5", "Namur"),
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fmt_eur(v, decimals=0):
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"€{v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"€{v/1_000:.0f}K"
    return f"€{v:.0f}"


def fmt_pct(v):
    return f"{v:.1f}%" if v is not None else "—"


def fmt_n(v):
    return f"{v:,.0f}" if v is not None else "—"


def build_screen_query(args):
    """Build the screening SQL from CLI filters. Returns (sql, params)."""
    conditions = []
    params = []

    # Only active companies with financial data
    conditions.append("ps.status = 'AC'")
    conditions.append("ps.revenue IS NOT NULL")

    if args.nace:
        conditions.append("ps.nace_code LIKE ?")
        params.append(f"{args.nace}%")

    if args.province:
        prefix = args.province.upper()
        if prefix not in PROVINCE_ZIPCODES:
            print(f"Unknown province '{prefix}'. Valid: {', '.join(PROVINCE_ZIPCODES)}")
            sys.exit(1)
        zipcode_prefix, _ = PROVINCE_ZIPCODES[prefix]
        conditions.append("ps.zipcode LIKE ?")
        params.append(f"{zipcode_prefix}%")

    if args.zipcode:
        conditions.append("ps.zipcode LIKE ?")
        params.append(f"{args.zipcode}%")

    if args.legal_form:
        conditions.append("ps.juridical_form = ?")
        params.append(args.legal_form)

    if args.revenue_min is not None:
        conditions.append("ps.revenue >= ?")
        params.append(args.revenue_min)

    if args.revenue_max is not None:
        conditions.append("ps.revenue <= ?")
        params.append(args.revenue_max)

    if args.ebitda_min is not None:
        conditions.append("ps.ebitda >= ?")
        params.append(args.ebitda_min)

    if args.ebitda_margin_min is not None:
        conditions.append("ps.ebitda_margin_pct >= ?")
        params.append(args.ebitda_margin_min)

    if args.fte_min is not None:
        conditions.append("ps.fte_total >= ?")
        params.append(args.fte_min)

    if args.fte_max is not None:
        conditions.append("ps.fte_total <= ?")
        params.append(args.fte_max)

    if args.leverage_max is not None:
        # leverage = net_debt / ebitda
        conditions.append("ps.ebitda > 0")
        conditions.append("(ps.net_debt / ps.ebitda) <= ?")
        params.append(args.leverage_max)

    if args.founded_after:
        conditions.append("ps.founding_date >= ?")
        params.append(f"{args.founded_after}-01-01")

    if args.founded_before:
        conditions.append("ps.founding_date <= ?")
        params.append(f"{args.founded_before}-12-31")

    # Most recent filing per company
    where = " AND ".join(conditions)
    sql = f"""
        WITH latest AS (
            SELECT enterprise_number, MAX(fiscal_year) AS max_year
            FROM pe_screen
            WHERE revenue IS NOT NULL
            GROUP BY enterprise_number
        )
        SELECT
            ps.enterprise_number   AS cbe,
            ps.name,
            ps.nace_code,
            ps.municipality_nl     AS municipality,
            ps.zipcode,
            ps.fiscal_year         AS fy,
            ps.revenue,
            ps.ebitda,
            ps.ebitda_margin_pct   AS ebitda_pct,
            ps.net_profit,
            ps.net_margin_pct      AS net_pct,
            ps.net_debt,
            CASE WHEN ps.ebitda > 0
                 THEN ROUND(ps.net_debt / ps.ebitda, 1) END AS leverage,
            ps.fte_total           AS fte,
            ps.revenue_per_fte
        FROM pe_screen ps
        JOIN latest l
          ON l.enterprise_number = ps.enterprise_number
         AND l.max_year = ps.fiscal_year
        WHERE {where}
        ORDER BY ps.revenue DESC
    """
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    return sql, params


def print_screen_results(rows):
    if not rows:
        print("No results.")
        return

    # Header
    print(
        f"{'CBE':<12} {'Name':<40} {'NACE':<6} {'City':<20} "
        f"{'FY':>4} {'Revenue':>10} {'EBITDA':>9} {'Mgn%':>6} "
        f"{'Net D':>9} {'Lev':>5} {'FTE':>6}"
    )
    print("-" * 140)
    for r in rows:
        name = (r["name"] or "—")[:39]
        city = (r["municipality"] or "—")[:19]
        print(
            f"{r['cbe']:<12} {name:<40} {(r['nace_code'] or '—'):<6} {city:<20} "
            f"{(r['fy'] or '—'):>4} {fmt_eur(r['revenue']):>10} {fmt_eur(r['ebitda']):>9} "
            f"{fmt_pct(r['ebitda_pct']):>6} {fmt_eur(r['net_debt']):>9} "
            f"{(str(r['leverage']) if r['leverage'] is not None else '—'):>5} "
            f"{fmt_n(r['fte']):>6}"
        )
    print(f"\n{len(rows)} companies")


def run_sector_summary(conn, nace_prefix=None):
    """Print sector benchmark stats."""
    where = "ps.revenue IS NOT NULL AND ps.status = 'AC'"
    params = []
    if nace_prefix:
        where += " AND ps.nace_code LIKE ?"
        params.append(f"{nace_prefix}%")

    sql = f"""
        WITH latest AS (
            SELECT enterprise_number, MAX(fiscal_year) AS max_year
            FROM pe_screen WHERE revenue IS NOT NULL
            GROUP BY enterprise_number
        )
        SELECT
            SUBSTR(ps.nace_code, 1, 2)          AS nace2,
            COUNT(DISTINCT ps.enterprise_number) AS company_count,
            ROUND(AVG(ps.revenue))               AS avg_revenue,
            ROUND(AVG(ps.ebitda_margin_pct), 1)  AS avg_ebitda_margin,
            ROUND(AVG(ps.fte_total), 1)          AS avg_fte,
            ROUND(SUM(ps.revenue))               AS total_revenue
        FROM pe_screen ps
        JOIN latest l
          ON l.enterprise_number = ps.enterprise_number
         AND l.max_year = ps.fiscal_year
        WHERE {where}
        GROUP BY nace2
        HAVING company_count >= 3
        ORDER BY total_revenue DESC
        LIMIT 30
    """
    rows = conn.execute(sql, params).fetchall()

    if not rows:
        print("No sector data.")
        return

    print(f"{'NACE2':<6} {'Companies':>10} {'Avg Revenue':>13} {'Avg EBITDA%':>12} {'Avg FTE':>9} {'Sector Revenue':>16}")
    print("-" * 72)
    for r in rows:
        print(
            f"{r['nace2']:<6} {r['company_count']:>10,} {fmt_eur(r['avg_revenue']):>13} "
            f"{fmt_pct(r['avg_ebitda_margin']):>12} {fmt_n(r['avg_fte']):>9} "
            f"{fmt_eur(r['total_revenue']):>16}"
        )


def run_db_stats(conn):
    """Print overall database statistics."""
    stats = {
        "Enterprises (total)":    conn.execute("SELECT COUNT(*) FROM enterprise").fetchone()[0],
        "Enterprises (active)":   conn.execute("SELECT COUNT(*) FROM enterprise WHERE status='AC'").fetchone()[0],
        "Companies with financials": conn.execute("SELECT COUNT(DISTINCT enterprise_number) FROM financial_data").fetchone()[0],
        "Total filings":          conn.execute("SELECT COUNT(DISTINCT deposit_key) FROM financial_data").fetchone()[0],
        "Rubric rows":            conn.execute("SELECT COUNT(*) FROM financial_data").fetchone()[0],
        "KBO extract number":     conn.execute("SELECT MAX(extract_number) FROM kbo_extract_log").fetchone()[0],
    }
    print("=== Database Statistics ===")
    for k, v in stats.items():
        print(f"  {k:<30} {v:>12,}")


def export_csv(rows, path):
    if not rows:
        print("Nothing to export.")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(rows[0].keys())
        for r in rows:
            writer.writerow(list(r))
    print(f"Exported {len(rows)} rows to {path}")


def main():
    parser = argparse.ArgumentParser(description="Screen Belgian companies for PE deal sourcing")

    # Filters
    parser.add_argument("--nace", help="NACE code prefix (e.g. 26, 281, 46)")
    parser.add_argument("--province", help=f"Province code: {', '.join(PROVINCE_ZIPCODES)}")
    parser.add_argument("--zipcode", help="Zipcode prefix (e.g. 9000, 2)")
    parser.add_argument("--legal-form", help="KBO juridical form code (e.g. 014 for NV)")
    parser.add_argument("--revenue-min", type=float, help="Minimum revenue (EUR)")
    parser.add_argument("--revenue-max", type=float, help="Maximum revenue (EUR)")
    parser.add_argument("--ebitda-min", type=float, help="Minimum EBITDA (EUR)")
    parser.add_argument("--ebitda-margin-min", type=float, help="Minimum EBITDA margin (%%)")
    parser.add_argument("--fte-min", type=float, help="Minimum FTE")
    parser.add_argument("--fte-max", type=float, help="Maximum FTE")
    parser.add_argument("--leverage-max", type=float, help="Maximum net debt / EBITDA")
    parser.add_argument("--founded-after", type=int, help="Founded after year (e.g. 1990)")
    parser.add_argument("--founded-before", type=int, help="Founded before year (e.g. 2010)")
    parser.add_argument("--limit", type=int, default=50, help="Max rows (default 50)")

    # Modes
    parser.add_argument("--summary", action="store_true", help="Show sector benchmarks instead of company list")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--export", help="Export results to CSV file")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")

    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)

    conn = connect(db_path)

    if args.stats:
        run_db_stats(conn)
        conn.close()
        return

    if args.summary:
        run_sector_summary(conn, nace_prefix=args.nace)
        conn.close()
        return

    sql, params = build_screen_query(args)
    rows = conn.execute(sql, params).fetchall()

    print_screen_results(rows)

    if args.export:
        export_csv(rows, args.export)

    conn.close()


if __name__ == "__main__":
    main()
