# Belgian Company Database

Build a searchable database of Belgian companies combining KBO registry data with NBB annual accounts — a self-hosted Belfirst alternative for PE deal sourcing and screening.

## Tech Stack

- Python 3.12+
- SQLite (single file database, portable)
- `requests` for API calls
- `streamlit` for UI (local browser app, deployable later)
- `pandas` for data handling in UI layer

## Project Structure

```
belgian-company-db/
├── CLAUDE.md
├── requirements.txt             # pip dependencies
├── data/                        # KBO ZIPs and NBB downloads (gitignored)
├── db/                          # SQLite database file (gitignored)
├── docs/
│   ├── kbo-schema.md            # KBO CSV structure and field reference
│   ├── nbb-api.md               # NBB CBSO API endpoints and auth
│   └── belgian-gaap.md          # Rubric code → financial line item mapping
├── src/
│   ├── kbo_loader.py            # Parse KBO full ZIP → SQLite
│   ├── kbo_updater.py           # Apply KBO daily update ZIPs
│   ├── nbb_client.py            # NBB CBSO API wrapper
│   ├── nbb_loader.py            # Parse NBB JSON filings → SQLite
│   ├── pipeline.py              # Daily orchestrator (KBO update + NBB ingest)
│   └── schema.sql               # Full database schema
├── app/
│   ├── app.py                   # Streamlit main app
│   └── pages/                   # Streamlit multi-page structure
│       ├── 1_screener.py        # Company screener with filters
│       ├── 2_company.py         # Single company deep-dive
│       └── 3_sector.py          # Sector benchmarking
├── scripts/
│   ├── init_db.py               # Create database from schema.sql
│   └── screen.py                # Example screening queries
├── .env                         # API keys (gitignored)
└── .gitignore
```

## Commands

```bash
python src/kbo_loader.py data/KboOpenData_*_Full.zip    # Bootstrap KBO data
python src/kbo_updater.py data/KboOpenData_*_Update.zip  # Apply KBO updates
python src/nbb_loader.py --cbe 0403101811               # Load single company financials
python src/pipeline.py                                    # Run daily pipeline
python scripts/screen.py                                  # Run screening queries
streamlit run app/app.py                                  # Launch UI
```

## Build Phases — Execute in Order

### Phase 1: KBO loader
Parse the KBO full ZIP into SQLite. The ZIP contains CSVs: enterprise.csv, denomination.csv, address.csv, activity.csv, establishment.csv, contact.csv, code.csv, branch.csv. See `@docs/kbo-schema.md` for field details.

Key decisions:
- Normalize EnterpriseNumber to 10 digits without dots (strip dots on load)
- Convert dates from dd-mm-yyyy to ISO YYYY-MM-DD
- Create a `company_master` view joining enterprise + name + address + NACE code
- Index on: enterprise_number, nace_code, zipcode, juridical_form

### Phase 2: KBO updater
Process KBO update ZIPs. They contain `*_delete.csv` and `*_insert.csv` pairs. For each: DELETE rows matching entity numbers in delete file, then INSERT from insert file. Track applied ExtractNumbers to avoid reprocessing.

### Phase 3: NBB API client
REST client for NBB CBSO. See `@docs/nbb-api.md` for endpoints.

Key decisions:
- Load API key from .env (`NBB_API_KEY`)
- Generate UUID for X-Request-Id per request
- Add 1-2 second delay between requests (no published rate limits)
- Base URL configurable: test (`ws.uat2.cbso.nbb.be`) vs production (`ws.cbso.nbb.be`)

### Phase 4: NBB financial data loader
Parse JSON filings into financial_data table. See `@docs/belgian-gaap.md` for rubric code mapping.

EBITDA = rubric 9901 (operating profit) + rubric 630 (depreciation & amortization)

### Phase 5: Screening views
SQL views combining KBO + NBB data for PE screening: revenue, EBITDA, margins, leverage, FTE. Filterable by NACE code, region, size.

### Phase 6: Daily pipeline
Orchestrator that runs KBO update + NBB daily extract ingestion. Designed for cron.

### Phase 7: Streamlit UI
Browser-based interface for deal sourcing. Three pages:

**Screener** (`1_screener.py`):
- Sidebar filters: NACE sector (dropdown with search), province/zipcode, legal form, revenue range, EBITDA range, FTE range, founding year
- Results as sortable/downloadable table: company name, CBE, sector, municipality, revenue, EBITDA, margin, FTE
- Click a row → navigate to company deep-dive
- Export filtered results to Excel

**Company deep-dive** (`2_company.py`):
- Search by name or CBE number
- Company header: name, CBE, legal form, address, NACE, founding date
- Financial history table: revenue, EBITDA, margin, net profit, equity, debt, FTE across available years
- Simple line charts: revenue and EBITDA trend
- Link to NBB filing PDF

**Sector benchmarking** (`3_sector.py`):
- Select NACE code → show sector stats: median revenue, EBITDA margin, FTE, company count
- Distribution charts (revenue histogram, margin boxplot)
- Top companies in sector by revenue

Key decisions:
- Use `st.cache_data` for database queries (avoid re-reading SQLite on every interaction)
- DB path from .env so it works regardless of where the project folder sits
- All data handling via pandas DataFrames
- Keep the UI clean — no clutter, fast to load

## Environment Setup

This project is designed to live on OneDrive for multi-device access.

```bash
# First time setup — run from the project folder
python -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows
pip install -r requirements.txt
cp .env.example .env               # then edit with your API keys
```

The `.venv/` folder should be in `.gitignore` — create it locally on each device, don't sync it via OneDrive. Virtual environments contain device-specific paths and break when synced.

The SQLite database (`db/belgian_companies.db`) DOES sync via OneDrive. This is fine for single-user access. Do not open the app on two devices simultaneously — SQLite uses file locking that conflicts with OneDrive sync.

## Conventions

- All scripts runnable standalone with `python src/script.py`
- Use argparse for CLI arguments
- Log to stdout with timestamps
- .env for secrets, never hardcode API keys
- SQLite database at `db/belgian_companies.db`
- File naming: snake_case for Python, kebab-case for docs
- Error handling: log and continue (don't crash the pipeline on one bad filing)

## Important

- NEVER commit .env or database files
- KBO data license prohibits using personal data for direct marketing
- NBB JSON format only available for XBRL filings since April 2022
- The KBO ZIP is ~300MB — don't try to load it into memory; stream/iterate
- CBE numbers have format 0xxx.xxx.xxx in KBO but must be sent as 0xxxxxxxxx (no dots) to NBB API
