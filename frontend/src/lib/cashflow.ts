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
 * Primary display is the **indirect method** — start from net profit,
 * add back non-cash items, strip exceptional P&L items, bridge working
 * capital. The **direct method** (cash receipts / payments) is computed
 * silently as an internal audit; `cfoAuditPasses` flips false if the two
 * methods disagree by more than 1% of |CFO|. That catches decomposition
 * bugs.
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

  /* ====== INDIRECT METHOD — OPERATING (UI-visible) ====== */

  /** Rubric 9904 — post-tax, post-interest. Starting point. */
  netProfit: number | null;

  /** Rubric 630. Non-cash add-back. Kept as raw signed value so that a
   *  reversal (rare) correctly reduces the CFO add-back rather than being
   *  silently zeroed out. */
  da: number;
  /** Rubric 631/4. Non-cash write-downs on receivables/inventory. */
  writedowns: number;
  /** Rubric 635/8. Movement in provisions. Non-cash. */
  provisions: number;

  /** Rubric 76. Booked in P&L below the operating line; subtracted from
   *  CFO because cash sits in CFI (for asset disposals) or is non-cash
   *  (for revaluations). */
  exceptionalIncome: number;
  /** Rubric 66. Added back to CFO (usually operating). */
  exceptionalCharges: number;

  /** Increase in inventories (rubric 3) → cash use → negative. */
  deltaInventories: number | null;
  /** Increase in trade receivables (rubric 40/41) → cash use → negative. */
  deltaTradeReceivables: number | null;
  /** Increase in trade payables (rubric 44) → cash source → positive. */
  deltaTradePayables: number | null;
  /** Increase in tax + social payables (rubric 45) → source → positive. */
  deltaTaxSocialPayables: number | null;
  /** Increase in other short-term payables (47/48) → source → positive. */
  deltaOtherPayables: number | null;
  /** Sum of the WC lines, signed as cash impact. */
  wcChange: number | null;

  /** Indirect-method operating cash flow. Primary CFO number. */
  cashFromOps: number | null;

  /* ====== INVESTING ====== */

  /** Operating CapEx = −[Δ(21) + Δ(22/27) + 630]. Excludes Δ(28) =
   *  financial fixed assets (those movements are M&A / participations,
   *  shown separately). Negative = investment outflow. */
  capex: number | null;

  /** Δ(28) flipped sign. Shown as a separate CFI line so the reader can
   *  see CapEx vs M&A distinctly. */
  changeInFinancialAssets: number | null;

  cashFromInvesting: number | null;

  /* ====== FINANCING ====== */

  /** Rubric 170/4. */
  deltaLtDebt: number | null;
  /** Rubric 43. */
  deltaStDebt: number | null;

  /** Cash-raised equity = Δ(10) + Δ(11). Excludes retained earnings and
   *  reserves (13, 14) because they reclassify net profit, which is
   *  already captured in CFO. Falls back to Δ(10/15) − NP + Dividends
   *  when 10/11 aren't filed individually. */
  newCapital: number | null;

  /** Always negative when reported; 0 when rubric 694 not filed. */
  dividendsPaid: number;

  cashFromFinancing: number | null;

  /* ====== RECONCILIATION ====== */

  /** CFO + CFI + CFF. */
  impliedCashChange: number | null;
  /** Δ(54/58 + 50/53) observed on the balance sheet. */
  observedCashChange: number | null;
  /** observed − implied. Small = good. Large = filing anomaly or item
   *  not modelled. */
  unreconciledGap: number | null;

  /* ====== AUDIT (silent cross-check via direct method) ====== */

  /** Direct-method CFO — cash receipts from customers + cash paid
   *  operating + cash paid interest + cash paid tax. Computed internally
   *  to catch decomposition bugs; not displayed. */
  cfoDirect: number | null;
  /** True when |CFO_indirect − CFO_direct| / max(|CFO|, 1) < 0.01. */
  cfoAuditPasses: boolean;

  /* ====== CASH BALANCE LEVELS ====== */
  cashStart: number | null;
  cashEnd: number | null;

  /** True when net profit is unavailable. */
  insufficientData: boolean;
}

const rub = (r: RubricData, code: string, fy: number | null): number | null => {
  if (fy == null) return null;
  const v = r?.[code]?.[String(fy)];
  return typeof v === "number" ? v : null;
};

const delta = (cur: number | null, prev: number | null): number | null => {
  if (cur == null && prev == null) return null;
  return (cur ?? 0) - (prev ?? 0);
};

/** Sum treating nulls as unusable. If every input is null returns null;
 *  otherwise treats null as 0. Prevents silent mixing of real and null. */
const sumOrNull = (...xs: (number | null)[]): number | null => {
  if (xs.every((x) => x == null)) return null;
  return xs.reduce<number>((a, x) => a + (x ?? 0), 0);
};

/**
 * Derive a cash-flow timeline from rubric data.
 *
 * @param rubrics  Rubric pivot from `/api/companies/{cbe}/financials`
 * @param years    Fiscal years (order doesn't matter; sorted internally).
 *                 First year returns with null deltas (no prior to diff).
 */
export function deriveCashFlow(rubrics: RubricData, years: number[]): CashFlowYear[] {
  const sorted = [...new Set(years)].sort((a, b) => a - b);
  return sorted.map((fy, idx) => {
    const prev = idx > 0 ? sorted[idx - 1] : null;

    const netProfit = rub(rubrics, "9904", fy);
    const insufficientData = netProfit == null;

    // Non-cash items. D&A kept as raw signed value: a rare reversal
    // (rubric 630 filed negative) decreases the add-back rather than
    // being silently zeroed by Math.max / Math.abs.
    const da = rub(rubrics, "630", fy) ?? 0;
    const writedowns = rub(rubrics, "631/4", fy) ?? 0;
    const provisions = rub(rubrics, "635/8", fy) ?? 0;

    const exceptionalIncome = rub(rubrics, "76", fy) ?? 0;
    const exceptionalCharges = rub(rubrics, "66", fy) ?? 0;

    // Working-capital components — all signed as cash impact.
    let deltaInventories: number | null = null;
    let deltaTradeReceivables: number | null = null;
    let deltaTradePayables: number | null = null;
    let deltaTaxSocialPayables: number | null = null;
    let deltaOtherPayables: number | null = null;
    let wcChange: number | null = null;

    let capex: number | null = null;
    let changeInFinancialAssets: number | null = null;

    let deltaLtDebt: number | null = null;
    let deltaStDebt: number | null = null;
    let newCapital: number | null = null;

    let observedCashChange: number | null = null;
    let cashStart: number | null = null;

    // Used by the direct-method audit.
    let operatingCashCosts: number | null = null;
    let totalOperatingIncome: number | null = null;

    if (prev != null) {
      const dInvRaw = delta(rub(rubrics, "3", fy), rub(rubrics, "3", prev));
      const dArRaw  = delta(rub(rubrics, "40/41", fy), rub(rubrics, "40/41", prev));
      const dApRaw  = delta(rub(rubrics, "44", fy), rub(rubrics, "44", prev));
      const dTaxSocRaw = delta(rub(rubrics, "45", fy), rub(rubrics, "45", prev));
      const dOtherRaw = delta(rub(rubrics, "47/48", fy), rub(rubrics, "47/48", prev));

      deltaInventories = dInvRaw == null ? null : -dInvRaw;
      deltaTradeReceivables = dArRaw == null ? null : -dArRaw;
      deltaTradePayables = dApRaw;       // increase = source, raw sign
      deltaTaxSocialPayables = dTaxSocRaw;
      deltaOtherPayables = dOtherRaw;

      wcChange = sumOrNull(
        deltaInventories,
        deltaTradeReceivables,
        deltaTradePayables,
        deltaTaxSocialPayables,
        deltaOtherPayables,
      );

      // Operating CapEx (excludes financial fixed assets). Identity:
      //   GrossAdditions ≈ ΔNetFA + D&A.
      // Raw signed `da` handles reversals correctly.
      const dTang = delta(rub(rubrics, "22/27", fy), rub(rubrics, "22/27", prev));
      const dIntang = delta(rub(rubrics, "21", fy), rub(rubrics, "21", prev));
      if (dTang != null || dIntang != null) {
        const operFaDelta = (dTang ?? 0) + (dIntang ?? 0);
        capex = -(operFaDelta + da);
      }

      const dFinFa = delta(rub(rubrics, "28", fy), rub(rubrics, "28", prev));
      if (dFinFa != null) changeInFinancialAssets = -dFinFa;

      deltaLtDebt = delta(rub(rubrics, "170/4", fy), rub(rubrics, "170/4", prev));
      deltaStDebt = delta(rub(rubrics, "43", fy), rub(rubrics, "43", prev));

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

      const totalOperatingCharges = rub(rubrics, "60/66A", fy);
      if (totalOperatingCharges != null) {
        operatingCashCosts = totalOperatingCharges - da - writedowns - provisions;
      }
      totalOperatingIncome =
        rub(rubrics, "70/76A", fy)
        ?? ((rub(rubrics, "70", fy) ?? 0) + (rub(rubrics, "74", fy) ?? 0) || null);
    }

    const cashEnd = sumOrNull(rub(rubrics, "54/58", fy), rub(rubrics, "50/53", fy));

    const dividendsFiled = rub(rubrics, "694", fy) ?? 0;
    const dividendsPaid = dividendsFiled > 0 ? -dividendsFiled : 0;

    /* ========== INDIRECT METHOD CFO (primary display) ========== */

    const cashFromOps = prev == null || netProfit == null
      ? null
      : netProfit
        + da
        + writedowns
        + provisions
        - exceptionalIncome
        + exceptionalCharges
        + (wcChange ?? 0);

    /* ========== CFI ========== */

    const cashFromInvesting = prev == null
      ? null
      : sumOrNull(capex, changeInFinancialAssets);

    /* ========== CFF ========== */

    const cashFromFinancing = prev == null
      ? null
      : (deltaLtDebt == null && deltaStDebt == null && newCapital == null && dividendsPaid === 0)
        ? null
        : (deltaLtDebt ?? 0) + (deltaStDebt ?? 0) + (newCapital ?? 0) + dividendsPaid;

    /* ========== DIRECT METHOD AUDIT (silent) ========== */

    let cfoDirect: number | null = null;
    if (prev != null && totalOperatingIncome != null) {
      const cashFromCustomers = totalOperatingIncome - (-(deltaTradeReceivables ?? 0));
      const cashPaidOperating = operatingCashCosts != null
        ? -(operatingCashCosts
            + -(deltaInventories ?? 0)   // undo the sign flip to get raw ΔInventory
            - (deltaTradePayables ?? 0)
            - (deltaOtherPayables ?? 0))
        : null;
      const cashForInterestNet = -((rub(rubrics, "65", fy) ?? 0) - (rub(rubrics, "75", fy) ?? 0));
      const cashForTaxes = -((rub(rubrics, "67/77", fy) ?? 0) - (deltaTaxSocialPayables ?? 0));
      cfoDirect = cashPaidOperating != null
        ? cashFromCustomers + cashPaidOperating + cashForInterestNet + cashForTaxes
        : null;
    }

    const cfoAuditPasses =
      cashFromOps == null || cfoDirect == null
        ? true
        : Math.abs(cashFromOps - cfoDirect) /
          Math.max(Math.abs(cashFromOps), Math.abs(cfoDirect), 1) < 0.01;

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
      netProfit,
      da,
      writedowns,
      provisions,
      exceptionalIncome,
      exceptionalCharges,
      deltaInventories,
      deltaTradeReceivables,
      deltaTradePayables,
      deltaTaxSocialPayables,
      deltaOtherPayables,
      wcChange,
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
      cfoDirect,
      cfoAuditPasses,
      cashStart,
      cashEnd,
      insufficientData,
    };
  });
}
