# DataSnoop Public API v1

A small read-only HTTP API that returns financial data for a single
Belgian company by its VAT/CBE number. Designed to be called from a
webshop or back-office system that wants a quick credit picture before
shipping or invoicing a B2B customer.

> **Status (2026-04-25):** invite-only test. Free for the duration of
> the test. Reach out if you'd like a key.

---

## Authentication

Every request must carry a Bearer token in the `Authorization` header.
Keys look like `dsk_live_…` and are issued by the operator.

```
Authorization: Bearer dsk_live_K9pq2xW3vLm4nB8rT5vY6wZ1aS9dF8gH
```

**Treat the key like a password.** It identifies your account, counts
against your daily cap, and shows up in our audit log.

If the key leaks, email us and we'll revoke it. Reissue is instant.

---

## Limits

| Limit              | Value         | Notes                                            |
|--------------------|---------------|--------------------------------------------------|
| Per-minute rate    | 60 req/min    | Per key, not per IP. Returns `429`.             |
| Daily cap          | 10 000 / 24h  | Default. Configurable per key. Returns `429`.   |
| Concurrent calls   | (no limit)    | Be sensible.                                     |

The daily cap is a circuit breaker, not a paid quota — it's free for the
duration of the test. We monitor usage to size pricing later.

---

## Endpoints

### `GET /api/v1/health`

Unauthenticated liveness probe. Returns `200` with a tiny JSON body.
Use it for uptime monitors. No data is returned.

```bash
curl https://datasnoop.be/api/v1/health
```

```json
{ "status": "ok", "service": "datasnoop-public-api", "version": "v1" }
```

---

### `GET /api/v1/company/{vat}/financials`

Returns the last N years of financial figures + derived ratios for one
company.

#### Path parameter

- `vat` — Belgian VAT or CBE number. Accepts any of:
  - `BE0752984076`
  - `0752984076`
  - `0752.984.076`
  - `0752 984 076`

#### Query parameters

| Name    | Type | Default | Notes                              |
|---------|------|---------|------------------------------------|
| `years` | int  | `2`     | How many fiscal years to return. Min 1, max 20. |

#### Example

```bash
curl https://datasnoop.be/api/v1/company/BE0752984076/financials?years=2 \
  -H "Authorization: Bearer dsk_live_…"
```

#### Response (200)

```json
{
  "company": {
    "vat": "0752984076",
    "name": "COOVER",
    "legalForm": "BV"
  },
  "financials": {
    "columns": [
      "fiscalYear",
      "revenue", "ebitda", "ebit", "netProfit",
      "equity", "totalAssets", "cash", "currentInvestments",
      "ltFinancialDebt", "stFinancialDebt", "financialCharges",
      "tradeReceivables", "tradePayables",
      "grossDebt", "netDebt",
      "netDebtEbitda", "debtEquity", "equityRatio",
      "interestCoverage", "cashStDebt", "dscr",
      "roe", "ebitdaMargin", "dso", "dpo", "cashConversion"
    ],
    "data": [
      [2024, 1234000, 99000, 80000, -58000, 412000, 800000, 120000, 0,
        300000, 50000, -3500, 95000, 60000,
        350000, 230000,
        2.32, 0.85, 51.5, 22.86, 2.4, 1.85,
        -14.08, 8.02, 28.1, 17.7, 10.4],
      [2023, 1100000, 167000, 140000, 116000, 470000, 820000, 90000, 0,
        310000, 40000, -2800, 88000, 55000,
        350000, 260000,
        1.56, 0.74, 57.32, 50.0, 2.25, 3.9,
        24.68, 15.18, 29.2, 18.3, 10.9]
    ]
  },
  "meta": {
    "currency": "EUR",
    "source": "NBB",
    "lastUpdated": "2025-08-14",
    "schemaVersion": "1.0",
    "yearsReturned": 2,
    "yearsRequested": 2,
    "filingModel": "VOL",
    "filingModelLabel": "full",
    "units": {
      "fiscalYear": "year",
      "equityRatio": "percent",
      "roe": "percent",
      "ebitdaMargin": "percent",
      "dso": "days",
      "dpo": "days",
      "cashConversion": "days",
      "netDebtEbitda": "ratio",
      "debtEquity": "ratio",
      "interestCoverage": "ratio",
      "cashStDebt": "ratio",
      "dscr": "ratio"
    }
  }
}
```

#### Column reference

Raw figures (EUR unless otherwise noted, `null` if not filed):

| Column                | Source / formula                                          |
|-----------------------|-----------------------------------------------------------|
| `fiscalYear`          | NBB `fiscal_year`                                          |
| `revenue`             | NBB rubric **70**                                          |
| `ebitda`              | rubric **9901** (operating profit) + rubric **630** (D&A) |
| `ebit`                | rubric **9901**                                            |
| `netProfit`           | rubric **9904**                                            |
| `equity`              | rubric **10/15**                                           |
| `totalAssets`         | rubric **20/58**                                           |
| `cash`                | rubric **54/58**                                           |
| `currentInvestments`  | rubric **50/53**                                           |
| `ltFinancialDebt`     | rubric **170/4**                                           |
| `stFinancialDebt`     | rubric **43**                                              |
| `financialCharges`    | rubric **65** (negative number)                            |
| `tradeReceivables`    | rubric **40/41**                                           |
| `tradePayables`       | rubric **44**                                              |

Derived figures:

| Column              | Formula                                                              | Unit    |
|---------------------|----------------------------------------------------------------------|---------|
| `grossDebt`         | `ltFinancialDebt + stFinancialDebt`                                  | EUR     |
| `netDebt`           | `grossDebt − cash − currentInvestments`                              | EUR     |
| `netDebtEbitda`     | `netDebt / ebitda`                                                   | ratio   |
| `debtEquity`        | `grossDebt / equity`                                                 | ratio   |
| `equityRatio`       | `equity / totalAssets × 100`                                         | percent |
| `interestCoverage`  | `ebit / abs(financialCharges)`                                       | ratio   |
| `cashStDebt`        | `(cash + currentInvestments) / stFinancialDebt`                      | ratio   |
| `dscr`              | `ebitda / (abs(financialCharges) + stFinancialDebt)`                 | ratio   |
| `roe`               | `netProfit / equity × 100`                                           | percent |
| `ebitdaMargin`      | `ebitda / revenue × 100`                                             | percent |
| `dso`               | `tradeReceivables / revenue × 365`                                   | days    |
| `dpo`               | `tradePayables / revenue × 365`                                      | days    |
| `cashConversion`    | `dso − dpo`                                                          | days    |

> **Percentages are returned in the `51.5` style** — `equityRatio: 51.5`
> means 51.5 %. Don't divide by 100 again.
>
> **`null` means undefined** — either the underlying figure wasn't filed
> with the NBB, or the denominator was zero / missing. It does **not**
> mean "zero".

#### `meta.filingModel`

| Code  | `filingModelLabel` | Meaning                              |
|-------|--------------------|--------------------------------------|
| `VOL` | `full`             | Volledig schema — large companies    |
| `VKT` | `abbreviated`      | Verkort schema — SMEs                |
| `MIC` | `micro`            | Micro schema — micro-enterprises     |

---

## Errors

All errors return JSON with the shape:

```json
{ "detail": { "error": "<machine-code>", "message": "<human readable>" } }
```

| HTTP | `error`                | When                                                |
|------|------------------------|-----------------------------------------------------|
| 400  | `invalid_vat`          | VAT couldn't be normalised to 10 digits             |
| 401  | `missing_credentials`  | No `Authorization` header (or empty token)          |
| 401  | `invalid_credentials`  | Token doesn't match a known key                     |
| 403  | `key_disabled`         | Key was revoked                                     |
| 404  | `company_not_found`    | VAT is well-formed but unknown to KBO               |
| 429  | `rate_limited`         | More than 60 calls in the last minute               |
| 429  | `daily_cap_exceeded`   | More than `daily_cap` calls in the last 24h         |
| 500  | `server_error`         | Something we need to look at — please report it     |

A successful call to a company with no NBB filings returns `200` with
`financials.data: []` and `meta.yearsReturned: 0` — not a 404.

---

## Compliance / fair use

The KBO open-data licence prohibits using personal data (director names,
addresses) for direct marketing. This API doesn't expose director PII,
but if you cross-reference with our other surfaces, that restriction
still applies to you.

We log every call (key, VAT, timestamp, status) for monitoring and abuse
detection.
