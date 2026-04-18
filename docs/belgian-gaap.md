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

## Cash-flow statement

**Belgian GAAP (national, non-IFRS) does NOT mandate a cash-flow
statement.** VOL (full), VKT (abbreviated), and MIC filings contain no
cash-flow rubrics in the XBRL taxonomy. Verified empirically against
`financial_data` on a representative VOL filer (Colruyt, CBE
0400378485): the 8xxx and 9xxx series carry notes and social-balance
data, not CFO/CFI/CFF.

The platform therefore **derives** the cash-flow statement from the
balance-sheet deltas and P&L line items. Single source of truth:
[`frontend/src/lib/cashflow.ts`](../frontend/src/lib/cashflow.ts).
Both the cash-flow tab and the waterfall read from the same helper.

### Direct method (user-facing)

The cashflow is presented in **direct-method** form — cash receipts,
cash payments — because that's closer to how a PE analyst mentally
thinks about cash generation. The equivalent indirect-method derivation
runs silently in parallel as an audit cross-check.

```
Operating
  Cash from customers         = 70/76A − Δ(40/41)
  Cash paid operating         = −(60/66A − 630 − 631/4 − 635/8)  (strip non-cash)
                                 − Δ(3)                          (inventory build)
                                 + Δ(44) + Δ(47/48)              (trade & other AP)
  Cash paid interest (net)    = −(65 − 75)
  Cash paid income tax        = −(67/77) + Δ(45)                 (approx: all Δ45 = tax)
  = Cash from Operations  (= "CFO")

Investing
  CapEx                       = −[Δ(21) + Δ(22/27) + 630]         (tangible + intangible)
  Δ financial fixed assets    = −Δ(28)                            (M&A / participations)
  = Cash from Investing

Financing
  Δ LT financial debt         = Δ(170/4)
  Δ ST financial debt         = Δ(43)
  New capital                 = Δ(10) + Δ(11)                     (capital + share premium)
                                  (NOT Δ(10/15) — that includes
                                   retained earnings, already in CFO)
  Dividends                   = −694                              (always outflow)
  = Cash from Financing

Reconciliation
  Implied ΔCash  = CFO + CFI + CFF
  Observed ΔCash = Δ(54/58) + Δ(50/53)
  Unexplained gap
```

**70/76A not 70 + 74.** Rubric 70/76A is the full operating income
aggregate and includes rubric 71 (inventory variation), rubric 72 (own
construction capitalised), and 76A (exceptional operating income). On
Colruyt FY25, 72 alone was €75M — using just 70 + 74 misses it and the
direct vs indirect audit fails by the same amount. Always prefer
70/76A; fall back to 70 + 74 only for filers that don't publish the
aggregate.

**CapEx uses 21 + 22/27, not 21/28.** Rubric 28 is financial fixed
assets — participations in subsidiaries. For a holding, Δ(28) is
dominated by M&A and consolidation effects, not operating CapEx. A
naive CapEx = Δ(21/28) + D&A reported €2.3B of "CapEx" for Colruyt
FY25 when actual tangible + intangible CapEx was ~€88M. Δ(28) gets its
own line ("Δ financial fixed assets") under CFI so the distinction is
visible.

**New capital uses 10 + 11, not 10/15.** Total equity (10/15) includes
retained earnings (14) and legal reserves (13) — both move when net
profit is retained. Using Δ(10/15) in CFF double-counts net profit
(once in CFO, once in CFF). The correct cash-raised-equity figure is
Δ(10) + Δ(11) (nominal capital + share premium). Fall back to
Δ(10/15) − NetProfit + Dividends when 10/11 aren't individually filed.

**Dividends — rubric 694 lag.** Rubric 694 is the proposed appropriation
of the closing year's result, technically paid the following year. For
a screening cash-flow this 1-year lag is an acceptable simplification;
a large discrepancy would surface in the reconciliation gap.

### Indirect method (internal audit)

Computed silently to verify the direct-method decomposition:

```
CFO_indirect = 9904                      (net profit)
             + 630 + 631/4 + 635/8       (non-cash add-backs)
             − 76 + 66                   (strip exceptional)
             + ΔWC (cash impact)
```

Where `ΔWC cash impact = −Δ(3) − Δ(40/41) + Δ(44) + Δ(45) + Δ(47/48)`.

The helper flips `cfoAuditPasses` to false if the two methods differ by
more than 1% of CFO. In practice both methods are algebraically
equivalent and agree within rounding (0.24% gap on Colruyt FY25). A
failed audit points to missing rubrics or a taxonomy version drift.

### Reconciliation gap

The delta between implied ΔCash (the derivation) and observed ΔCash
(the balance sheet) is surfaced as a dedicated row in both the table
and the waterfall. Tolerances:

- `<2%` — muted (slate). Derivation explains the cash movement well.
- `2–5%` — amber. Small unmodelled item.
- `>5%` — red. M&A consolidation effect, FX, minority interest,
  revaluation reserve, or a dividend-lag mismatch.

### Filing-model coverage

| Model | Net profit | D&A | Exceptional (66/76) | Full WC rubrics | Fit for derivation |
|---|---|---|---|---|---|
| VOL | ✓ | ✓ | ✓ | ✓ | Full — gap usually <2% |
| VKT | ✓ | sometimes | rare | partial | Degraded — WC bridge incomplete, gap can be large |
| MIC | minimal | ✗ | ✗ | ✗ | Insufficient — banner shown |

Companies without a second year of data cannot be bridged at all — the
first-year row renders with null deltas.
