# Belgian GAAP — Rubric Code Mapping for PE Screening

Belgian annual accounts use standardized rubric codes defined by the Central Balance Sheet Office. These codes are consistent across all filings, making them ideal for database querying.

Full code list: https://www.nbb.be/doc/ba/cbso2022/cbso_webservices_codes%20lists1000820250901.xlsx

## Key Rubric Codes for PE Screening

### Income Statement

| Rubric | Label (EN) | Label (NL) | Investment Use |
|--------|-----------|------------|----------------|
| 70 | Turnover | Omzet | Revenue / top line |
| 70/76A | Total operating income | Totaal bedrijfsopbrengsten | Gross income |
| 60/66A | Total operating charges | Totaal bedrijfskosten | Cost base |
| 9901 | Operating profit/loss | Bedrijfswinst/verlies | EBIT proxy |
| 75 | Financial income | Financiële opbrengsten | |
| 65 | Financial charges | Financiële kosten | Interest cost indicator |
| 9902 | Profit/loss on ordinary activities | Winst/verlies gewone bedrijfsuitoefening | |
| 76 | Extraordinary income | Uitzonderlijke opbrengsten | One-off items |
| 66 | Extraordinary charges | Uitzonderlijke kosten | One-off items |
| 9903 | Profit/loss before taxes | Winst/verlies vóór belasting | PBT |
| 67/77 | Income taxes | Belastingen | Tax charge |
| 9904 | Profit/loss for the period | Winst/verlies van het boekjaar | Net income |
| 630 | Depreciation & amortization | Afschrijvingen en waardeverminderingen | D&A (add-back for EBITDA) |
| 631/4 | Write-downs | Waardeverminderingen | Potential add-back |
| 635/8 | Provisions for risks | Voorzieningen voor risico's | Potential add-back |

### Balance Sheet — Assets

| Rubric | Label (EN) | Investment Use |
|--------|-----------|----------------|
| 20/28 | Fixed assets | Asset base, capital intensity |
| 21 | Intangible assets | IP, goodwill indicator |
| 22/27 | Tangible assets | PP&E |
| 28 | Financial fixed assets | Participations, group structure |
| 29/58 | Current assets | Working capital component |
| 29 | Amounts receivable > 1 year | |
| 3 | Inventories | Working capital |
| 40/41 | Trade receivables | Working capital |
| 50/53 | Current investments | Cash proxy |
| 54/58 | Cash at bank | Cash |
| 20/58 | Total assets | Balance sheet size |

### Balance Sheet — Liabilities

| Rubric | Label (EN) | Investment Use |
|--------|-----------|----------------|
| 10/15 | Equity | Balance sheet strength |
| 10 | Capital | Share capital |
| 13 | Reserves | Retained earnings |
| 14 | Accumulated profits/losses | Historical profitability |
| 15 | Investment grants | |
| 16 | Provisions | Contingent liabilities |
| 17 | Amounts payable > 1 year | Long-term debt |
| 170/4 | Financial debt > 1 year | LT financial leverage |
| 42/48 | Amounts payable ≤ 1 year | Short-term liabilities |
| 43 | Financial debt ≤ 1 year | ST financial leverage |
| 44 | Trade payables | Working capital |
| 45 | Tax & social security payables | |
| 10/49 | Total liabilities | Must equal total assets |

### Employment & Social Data

| Rubric | Label (EN) | Investment Use |
|--------|-----------|----------------|
| 9087 | Average FTE (total) | Company size, scale |
| 9097 | Average FTE (Belgium) | Domestic workforce |
| 1023 | Personnel costs | Labour cost base |
| 62 | Remuneration, social security | Wage bill |

## Derived Metrics — Calculation Logic

```
EBITDA          = rubric_9901 + rubric_630
EBITDA margin   = EBITDA / rubric_70 * 100
Net debt        = (rubric_170/4 + rubric_43) - (rubric_54/58 + rubric_50/53)
Leverage        = Net debt / EBITDA
Equity ratio    = rubric_10/15 / rubric_20/58 * 100
Revenue/FTE     = rubric_70 / rubric_9087
Personnel cost% = rubric_62 / rubric_70 * 100
Working capital = rubric_3 + rubric_40/41 - rubric_44
WC days         = Working capital / rubric_70 * 365
ROE             = rubric_9904 / rubric_10/15 * 100
```

## Filing Models

Belgian companies file under different models depending on size:

| Model | Who files | Data richness |
|-------|-----------|---------------|
| Full (VOL/COM) | Large companies | Complete P&L, balance sheet, notes, social balance |
| Abbreviated (VKT/ABR) | SMEs | Reduced P&L, simplified balance sheet |
| Micro (MIC) | Micro-entities | Minimal balance sheet, very limited P&L |

**PE relevance:** Micro filings often lack revenue (rubric 70) and have no P&L detail. For screening, filter on model = full or abbreviated to ensure data availability.

## Notes on Data Quality

- Revenue (70) is NOT always disclosed in abbreviated filings — some companies report only "gross margin" (9900)
- Rubric 9901 (operating profit) is the most reliably reported metric across filing types
- Depreciation (630) may be embedded in cost rubrics in abbreviated filings
- Historical comparability issues when taxonomy versions changed (2007, 2016, 2020)
- Euro conversion: pre-2002 filings were in BEF; the "Improved Data" product converts these
