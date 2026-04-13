# NBB CBSO Web Services — API Reference

Documentation: https://www.nbb.be/en/central-balance-sheet-office/consultation/web-services
Technical guide: https://www.nbb.be/doc/ba/cbso2022/cbso_webservices_technical%20guide_0.94.pdf
Code lists: https://www.nbb.be/doc/ba/cbso2022/cbso_webservices_codes%20lists1000820250901.xlsx
JSON/XBRL schema: https://www.nbb.be/doc/ba/cbso2022/cbso_jsonxbrl%200.94.yaml

## Base URLs

| Environment | URL |
|-------------|-----|
| Production | `https://ws.cbso.nbb.be` |
| Test (UAT2) | `https://ws.uat2.cbso.nbb.be` |

## Authentication

Every request requires these HTTP headers:

```
NBB-CBSO-Subscription-Key: {your_api_key}
X-Request-Id: {uuid4}
Accept: {format_specific_mime_type}
```

API keys are per-product. Get them from the developer portal under your profile → subscriptions → "Show" primary key.

## Products & Endpoints

### Authentic Data Query (free) — API name: `authentic`

Query individual companies by CBE number or filing reference.

| # | Operation | URL | Accept Header |
|---|-----------|-----|---------------|
| 1 | Get filing references for a company | `/authentic/legalEntity/{CBE}/references` | `application/json` |
| 2 | Get PDF for a filing | `/authentic/deposit/{ref}/accountingData` | `application/pdf` |
| 3 | Get XBRL for a filing | `/authentic/deposit/{ref}/accountingData` | `application/x.xbrl` |
| 4 | Get JSON for a filing | `/authentic/deposit/{ref}/accountingData` | `application/x.jsonxbrl` |

- CBE number: 10 digits, no dots (e.g., `0403101811`)
- Filing reference: `YYYY-NNNNNNNN` (e.g., `2021-00000132`)
- Optional query param on operation 1: `?fiscalYear=YYYY`

### Authentic Data Daily Extract (free) — API name: `extract`

Bulk download all filings published on a given date.

| # | Operation | URL | Accept Header |
|---|-----------|-----|---------------|
| 5 | All references for a date (ZIP of JSON) | `/extracts/batch/{YYYY-MM-DD}/references` | `application/x.zip+json` |
| 6 | All PDFs for a date (ZIP of PDFs) | `/extracts/batch/{YYYY-MM-DD}/accountingData` | `application/x.zip+pdf` |
| 7 | All XBRL for a date (ZIP of XBRL) | `/extracts/batch/{YYYY-MM-DD}/accountingData` | `application/x.zip+xbrl` |
| 8 | All JSON for a date (ZIP of JSON) | `/extracts/batch/{YYYY-MM-DD}/accountingData` | `application/x.zip+jsonxbrl` |

### Improved Data (paid) — API name: `improved`

NBB-corrected versions of filings (PDF-extracted values, euro-converted, error-corrected).

| # | Operation | URL | Accept Header |
|---|-----------|-----|---------------|
| 9 | Correction refs for a company | `/improved/legalEntity/{CBE}/references/improved` | `application/json` |
| 10 | Correction refs for a filing | `/improved/deposit/{ref}/references/improved` | `application/json` |
| 11 | PDF-extracted data | `/improved/deposit/{ref}/accountingData/improved/pdf_extracted` | `application/x.jsonxbrl` |
| 12 | Euro-converted data | `/improved/deposit/{ref}/accountingData/improved/euro_converted` | `application/x.jsonxbrl` |
| 13 | Corrected data | `/improved/deposit/{ref}/accountingData/improved/corrected` | `application/x.jsonxbrl` |
| 14 | All correction refs for a date | `/improved/batch/{YYYY-MM-DD}/references/improved` | `application/x.zip+json` |
| 15 | All corrected data for a date | `/improved/batch/{YYYY-MM-DD}/accountingData/improved` | `application/x.zip+jsonxbrl` |

## Data Coverage

| Format | Available since | Notes |
|--------|----------------|-------|
| Filing references | 1978 | Metadata only |
| PDF | 1999 | Image of filed accounts |
| XBRL | 2007 | Structured, Belgian GAAP taxonomy |
| JSON | April 4, 2022 | Derived from XBRL, easiest to parse |

JSON archive for daily extracts goes back ~3 years from current date.

## Test Environment Examples

These URLs work against the UAT2 test environment:

```
# Get references for a test company
GET https://ws.uat2.cbso.nbb.be/authentic/legalEntity/0403101811/references

# Get JSON filing data
GET https://ws.uat2.cbso.nbb.be/authentic/deposit/2021-00000132/accountingData
Accept: application/x.jsonxbrl

# Get daily extract references
GET https://ws.uat2.cbso.nbb.be/extracts/batch/2021-12-14/references
Accept: application/x.zip+json
```

## Error Handling

- 200: Success
- 400: Bad request (invalid CBE number format, etc.)
- 401/403: Invalid or missing API key
- 404: No data found for this entity/reference/date
- 429: Rate limited (back off and retry)
- 500: Server error (retry with exponential backoff)

## Rate Limiting

No published rate limits. Be polite: 1-2 seconds between requests. Aggressive polling will get your key revoked.
