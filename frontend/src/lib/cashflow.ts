/**
 * Cash-flow derivation — single source of truth for the cash-flow tab + the
 * waterfall bridge. Both views must agree on what CFO, CFI, CFF, and the
 * reconciliation gap are; that's what this file guarantees.
 *
 * Why derive instead of using NBB's "audited" cashflow?
 * Belgian GAAP (national, non-IFRS) does NOT mandate a cashflow statement.
 * VOL / VKT / MIC filings do not include CFO/CFI/CFF as XBRL rubrics
 * (verified empirically against Colruyt, CBE 0400378485). So the only
 * way to surface a cash-flow view is to derive one from net profit +
 * balance-sheet deltas.
 *
 * Primary display is the **direct method** — cash receipts from customers,
 * cash paid to operating activities, cash paid for interest, cash paid for
 * taxes. The **indirect method** is computed silently in parallel as an
 * internal audit; `cfoAuditPasses` flips false if the two methods
 * disagree by more than 1% of |CFO|. That catches decomposition bugs.
 *
 * Sign convention throughout: **positive = cash source, negative = cash use**.
 *
 * A reconciliation row surfaces the gap between the implied Δcash
 * (`cfo + cfi + cff`) and the observed Δcash (`Δ(rubric 54/58 + 50/53)`).
 * For well-behaved companies the gap is small (<5% of observed Δcash). A
 * large gap signals either a filing anomaly or an item we're not
 * modelling (M&A consolidation, FX, minority interests, revaluation).
 */

export type RubricData = Record<string, Record<string, number | null>>;

export interface CashFlowYear {
  fiscalYear: number;

  /* ====== DIRECT METHOD — OPERATING (UI-visible) ====== */

  /** Rubric 70/76A (full operating-income aggregate — includes 70 revenue,
   *  71 inventory variation, 72 own-construction, 74 other op. income,
   *  76A exceptional op. income) minus Δ(40/41). Falls back to 70 + 74
   *  for filers without the aggregate rubric. */
  cashFromCustomers: number | null;

  /** Negative. −(Operating cash costs) − Δ(3) + Δ(44) + Δ(47/48).
   *  Operating cash costs = (60/66A) − 630 − 631/4 − 635/8 (strip non-cash).
   *  Includes payments to suppliers AND employees combined — rubric 62 is
   *  a subset of 60/66A; we don't split it out because VKT filings often
   *  collapse them. */
  cashPaidOperating: number | null;

  /** Negative. −(65 − 75). Interest paid net of financial income. */
  cashForInterestNet: number | null;

  /** Negative (usually). −(67/77) + Δ(45). Tax expense net of change in
   *  tax + social payables (simplification: treats all of Δ(45) as
   *  tax-related). Rubric 67/77 can be filed negative (tax credit) — we
   *  honour the sign. */
  cashForTaxes: number | null;

  /** Sum of the four lines above. Direct-method operating cash flow. */
  cashFromOps: number | null;

  /* ====== INVESTING ====== */

  /** Operating CapEx = −(Δ(21) + Δ(22/27) + D&A). Excludes Δ(28) =
   *  financial fixed assets (those movements are M&A / participations). */
  capex: number | null;

  /** Δ(28) flipped sign. Negative = cash spent acquiring subsidiaries,
   *  positive = proceeds from divesting them. Shown as a separate line
   *  so the reader can see CapEx vs M&A distinctly — both land in CFI. */
  changeInFinancialAssets: number | null;

  cashFromInvesting: number | null;

  /* ====== FINANCING ====== */

  /** Rubric 170/4. */
  deltaLtDebt: number | null;
  /** Rubric 43. */
  deltaStDebt: number | null;

  /** Cash-raised equity = Δ(10) + Δ(11). Retained earnings and reserves
   *  (13, 14) are excluded because they reclassify net profit (already
   *  in CFO); including them would double-count. */
  newCapital: number | null;

  /** Always negative (outflow) when reported; 0 when rubric 694 not filed.
   *  Approximation: we use the current year's rubric 694 as cash dividends
   *  paid. Strictly, 694 is the *appropriation proposal* for the
   *  just-closed year (paid the following year); the lag usually doesn't
   *  matter much for screening and the reconciliation row catches larger
   *  distortions. */
  dividendsPaid: number;

  cashFromFinancing: number | null;

  /* ====== RECONCILIATION ====== */

  /** CFO (direct) + CFI + CFF. */
  impliedCashChange: number | null;
  /** Δ(54/58 + 50/53) from the balance sheet. Null when no cash rubrics
   *  are filed at all (some MIC filings). */
  observedCashChange: number | null;
  /** observed − implied. Small = derivation is tight. Large = filing
   *  anomaly or item not modelled. */
  unreconciledGap: number | null;

  /* ====== AUDIT (silent cross-check against indirect method) ====== */

  /** Indirect-method CFO: 9904 + 630 + 631/4 + 635/8 − 76 + 66 + ΔWC.
   *  Internal — not displayed. Kept for tests and debug. */
  cfoIndirect: number | null;
  /** True when |CFO_direct − CFO_indirect| / max(|CFO_direct|, 1) < 0.01.
   *  A false here flags a decomposition mismatch — investigate. */
  cfoAuditPasses: boolean;

  /* ====== CASH BALANCE LEVELS ====== */
  cashStart: number | null;
  cashEnd: number | null;

  /** True when even net profit / revenue is unavailable. */
  insufficientData: boolean;
}

const rub = (r: RubricData, code: string, fy: number | null): number | null => {
  if (fy == null) return null;
  const v = r?.[code]?.[String(fy)];
  return typeof v === "number" ? v : null;
};

/** Pick first non-null — for rubrics that drift across taxonomy versions
 *  (e.g. 20/28 → 21/28). Caller passes candidates in preference order. */
const rubAny = (r: RubricData, codes: string[], fy: number | null): number | null => {
  for (const code of codes) {
    const v = rub(r, code, fy);
    if (v != null) return v;
  }
  return null;
};

const delta = (cur: number | null, prev: number | null): number | null => {
  if (cur == null && prev == null) return null;
  return (cur ?? 0) - (prev ?? 0);
};

/** Sum, treating nulls as unusable — returns null if EVERY input is null,
 *  treats null as 0 otherwise. This prevents the helper from silently
 *  reporting a number that's a mix of real values and null-as-zero. */
const sumOrNull = (...xs: (number | null)[]): number | null => {
  if (xs.every((x) => x == null)) return null;
  return xs.reduce<number>((a, x) => a + (x ?? 0), 0);
};

/**
 * Derive a cash-flow timeline from rubric data.
 *
 * @param rubrics  Rubric pivot from `/api/companies/{cbe}/financials`
 * @param years    Fiscal years (order doesn't matter; sorted internally).
 *                 First year returns with null CFO/CFI/CFF deltas.
 */
export function deriveCashFlow(rubrics: RubricData, years: number[]): CashFlowYear[] {
  const sorted = [...new Set(years)].sort((a, b) => a - b);
  return sorted.map((fy, idx) => {
    const prev = idx > 0 ? sorted[idx - 1] : null;

    const netProfit = rub(rubrics, "9904", fy);
    const revenue = rubAny(rubrics, ["70", "70/76A"], fy);
    // Total operating income = 70 + 71 (ΔWIP) + 72 (own construction
    // capitalized) + 74 (other op. income) + 76A (exceptional op. income).
    // Using 70/76A directly covers all of them — rubric 72 in particular
    // can be material (€75M on Colruyt FY25) and gets dropped if we just
    // sum 70 + 74. Falling back to 70 + 74 for filers (abbreviated / micro)
    // that don't publish the 70/76A aggregate.
    const totalOperatingIncome = rub(rubrics, "70/76A", fy)
      ?? ((rub(rubrics, "70", fy) ?? 0) + (rub(rubrics, "74", fy) ?? 0) || null);
    const insufficientData = netProfit == null && revenue == null;

    // Non-cash items. D&A is traditionally positive (cost magnitude); we
    // accept whatever sign is filed — a rare negative reversal decreases
    // the add-back rather than being silently zeroed out.
    const da = rub(rubrics, "630", fy) ?? 0;
    const writedowns = rub(rubrics, "631/4", fy) ?? 0;
    const provisions = rub(rubrics, "635/8", fy) ?? 0;

    // Exceptional — for the indirect audit path.
    const exceptionalIncome = rub(rubrics, "76", fy) ?? 0;
    const exceptionalCharges = rub(rubrics, "66", fy) ?? 0;

    const totalOperatingCharges = rub(rubrics, "60/66A", fy);
    const operatingCashCosts = totalOperatingCharges != null
      ? totalOperatingCharges - da - writedowns - provisions
      : null;

    // Working-capital components — all signed as cash impact.
    let dInventory: number | null = null;
    let dReceivables: number | null = null;
    let dTradePayables: number | null = null;
    let dTaxSocialPayables: number | null = null;
    let dOtherPayables: number | null = null;

    let capex: number | null = null;
    let changeInFinancialAssets: number | null = null;

    let deltaLtDebt: number | null = null;
    let deltaStDebt: number | null = null;
    let newCapital: number | null = null;

    let observedCashChange: number | null = null;
    let cashStart: number | null = null;

    if (prev != null) {
      dInventory = delta(rub(rubrics, "3", fy), rub(rubrics, "3", prev));
      dReceivables = delta(rub(rubrics, "40/41", fy), rub(rubrics, "40/41", prev));
      dTradePayables = delta(rub(rubrics, "44", fy), rub(rubrics, "44", prev));
      dTaxSocialPayables = delta(rub(rubrics, "45", fy), rub(rubrics, "45", prev));
      dOtherPayables = delta(rub(rubrics, "47/48", fy), rub(rubrics, "47/48", prev));

      // Operating CapEx (excludes financial fixed assets). Identity:
      //   ΔNetFA = GrossAdditions − Disposals − D&A
      //   GrossAdditions ≈ ΔNetFA + D&A (ignoring disposals we can't split)
      // Use the raw signed `da` so a D&A reversal (rubric 630 filed
      // negative) correctly reduces the reconstructed CapEx rather than
      // inflating it via Math.abs. Sign on CapEx: positive number =
      // investment (outflow → flipped via the leading −), negative = net
      // disposal (inflow).
      const dTang = delta(rub(rubrics, "22/27", fy), rub(rubrics, "22/27", prev));
      const dIntang = delta(rub(rubrics, "21", fy), rub(rubrics, "21", prev));
      const operFaDelta = (dTang ?? 0) + (dIntang ?? 0);
      if (dTang != null || dIntang != null) {
        capex = -(operFaDelta + da);
      }

      // Investments in subsidiaries / financial FA — a separate CFI line.
      const dFinFa = delta(rub(rubrics, "28", fy), rub(rubrics, "28", prev));
      if (dFinFa != null) changeInFinancialAssets = -dFinFa;

      deltaLtDebt = delta(rub(rubrics, "170/4", fy), rub(rubrics, "170/4", prev));
      deltaStDebt = delta(rub(rubrics, "43", fy), rub(rubrics, "43", prev));

      // Cash-raised equity = Δ(10) + Δ(11). Fall back to
      // Δ(10/15) − NP + Dividends if 10/11 aren't filed individually.
      const dCapital = delta(rub(rubrics, "10", fy), rub(rubrics, "10", prev));
      const dSharePremium = delta(rub(rubrics, "11", fy), rub(rubrics, "11", prev));
      if (dCapital != null || dSharePremium != null) {
        newCapital = (dCapital ?? 0) + (dSharePremium ?? 0);
      } else {
        const dTotalEquity = delta(rub(rubrics, "10/15", fy), rub(rubrics, "10/15", prev));
        const divCurrent = rub(rubrics, "694", fy) ?? 0;
        if (dTotalEquity != null && netProfit != null) {
          newCapital = dTotalEquity - netProfit + divCurrent;
        }
      }

      const cashThisFy = sumOrNull(rub(rubrics, "54/58", fy), rub(rubrics, "50/53", fy));
      const cashPrevFy = sumOrNull(rub(rubrics, "54/58", prev), rub(rubrics, "50/53", prev));
      cashStart = cashPrevFy;
      observedCashChange =
        cashThisFy != null && cashPrevFy != null ? cashThisFy - cashPrevFy : null;
    }

    const cashEnd = sumOrNull(rub(rubrics, "54/58", fy), rub(rubrics, "50/53", fy));

    const dividendsFiled = rub(rubrics, "694", fy) ?? 0;
    const dividendsPaid = dividendsFiled > 0 ? -dividendsFiled : 0;

    /* ========== DIRECT METHOD CFO (primary display) ========== */

    // Cash from customers — operating income net of receivables build-up.
    // Uses the full operating income aggregate (70/76A, see above) so rubric
    // 72 (own construction capitalized) and rubric 71 (inventory variation)
    // are captured. Without these the direct method underestimates CFO and
    // the audit check against the indirect method fails.
    let cashFromCustomers: number | null = null;
    if (prev != null && totalOperatingIncome != null) {
      cashFromCustomers = totalOperatingIncome - (dReceivables ?? 0);
    }

    // Cash paid operating — supplier + employee + other ops.
    let cashPaidOperating: number | null = null;
    if (prev != null && operatingCashCosts != null) {
      cashPaidOperating = -(
        operatingCashCosts
        + (dInventory ?? 0)
        - (dTradePayables ?? 0)
        - (dOtherPayables ?? 0)
      );
    }

    // Cash for interest (net of financial income). Interest paid − financial
    // income received. Note: rubric 75 can include dividends received from
    // subs, which would technically be CFI — but the NBB taxonomy doesn't
    // split them, so we include the whole 75 here.
    let cashForInterestNet: number | null = null;
    if (prev != null) {
      const interestExpense = rub(rubrics, "65", fy) ?? 0;
      const financialIncome = rub(rubrics, "75", fy) ?? 0;
      cashForInterestNet = -(interestExpense - financialIncome);
    }

    // Cash for taxes. Tax expense − Δ(tax + social payables). Approximation:
    // treat all of Δ(45) as tax-related.
    let cashForTaxes: number | null = null;
    if (prev != null) {
      const taxExpense = rub(rubrics, "67/77", fy) ?? 0;
      cashForTaxes = -(taxExpense - (dTaxSocialPayables ?? 0));
    }

    // Direct CFO.
    const cashFromOps = prev == null
      ? null
      : sumOrNull(cashFromCustomers, cashPaidOperating, cashForInterestNet, cashForTaxes);

    /* ========== CFI ========== */

    const cashFromInvesting = prev == null
      ? null
      : sumOrNull(capex, changeInFinancialAssets);

    /* ========== CFF ========== */

    const cashFromFinancing = prev == null
      ? null
      : sumOrNull(deltaLtDebt, deltaStDebt, newCapital) == null && dividendsPaid === 0
        ? null
        : (deltaLtDebt ?? 0) + (deltaStDebt ?? 0) + (newCapital ?? 0) + dividendsPaid;

    /* ========== INDIRECT METHOD AUDIT ========== */

    let cfoIndirect: number | null = null;
    if (prev != null && netProfit != null) {
      // ΔWC as cash impact: inventory/AR increase = use; payables increase = source.
      const wcCashImpact =
        -(dInventory ?? 0)
        - (dReceivables ?? 0)
        + (dTradePayables ?? 0)
        + (dTaxSocialPayables ?? 0)
        + (dOtherPayables ?? 0);
      cfoIndirect =
        netProfit
        + da
        + writedowns
        + provisions
        - exceptionalIncome
        + exceptionalCharges
        + wcCashImpact;
    }

    const cfoAuditPasses =
      cashFromOps == null || cfoIndirect == null
        ? true  // can't audit without both — don't flag
        : Math.abs(cashFromOps - cfoIndirect) /
          Math.max(Math.abs(cashFromOps), Math.abs(cfoIndirect), 1) < 0.01;

    /* ========== RECONCILIATION ========== */

    const impliedCashChange = prev == null || cashFromOps == null
      ? null
      : cashFromOps + (cashFromInvesting ?? 0) + (cashFromFinancing ?? 0);

    const unreconciledGap =
      observedCashChange != null && impliedCashChange != null
        ? observedCashChange - impliedCashChange
        : null;

    return {
      fiscalYear: fy,
      cashFromCustomers,
      cashPaidOperating,
      cashForInterestNet,
      cashForTaxes,
      cashFromOps,
      capex,
      changeInFinancialAssets,
      cashFromInvesting,
      deltaLtDebt,
      deltaStDebt,
      newCapital,
      dividendsPaid,
      cashFromFinancing,
      impliedCashChange,
      observedCashChange,
      unreconciledGap,
      cfoIndirect,
      cfoAuditPasses,
      cashStart,
      cashEnd,
      insufficientData,
    };
  });
}
