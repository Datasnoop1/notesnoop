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
 * Primary display is the **indirect method starting from EBITDA** —
 * the PE / deal-sourcing convention. Starting from EBITDA has a nice
 * property: exceptional items (rubric 66 + 76) and D&A (630) never
 * enter EBITDA, so the statement has fewer "add-back / strip" lines
 * than a net-profit start.
 *
 *   CFO = EBITDA                          (9901 + 630)
 *       + Financial income (75)
 *       − Interest expense (65)
 *       − Income tax (67/77)
 *       + Write-downs (631/4)              (non-cash)
 *       + Provisions (635/8)               (non-cash)
 *       + ΔWorking capital
 *
 * The **direct method** (cash receipts / payments) is computed silently
 * as an internal audit; `cfoAuditPasses` flips false if the two methods
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

  /* ====== INDIRECT METHOD — OPERATING (UI-visible, EBITDA-start) ====== */

  /** Rubric 9904 — net profit after tax. Kept for internal audits and
   *  for filers that don't disclose 9901/630 separately. Not shown in
   *  the primary bridge. */
  netProfit: number | null;

  /** EBITDA = 9901 + 630. Starting milestone of the cashflow bridge. */
  ebitda: number | null;

  /** Rubric 75 — financial income (interest received, dividends from
   *  subs). Positive = cash source. Same sign as raw rubric. */
  financialIncome: number;
  /** Rubric 65 — financial charges (interest paid), **stored as cash
   *  impact**: negative = outflow. Display-ready (no sign flip at render
   *  time). */
  interestExpense: number;
  /** Rubric 67/77 — income tax, stored as cash impact. Negative =
   *  outflow (tax paid). Positive = tax credit (refund / deferred
   *  tax release). */
  incomeTax: number;

  /** Rubric 630 — kept for reference (part of EBITDA on the add-back
   *  side) and for the CapEx formula below. Not shown as a separate
   *  CFO line when starting from EBITDA. */
  da: number;
  /** True when rubric 630 wasn't filed and we imputed D&A from the
   *  balance-sheet NetFA delta (VKT abbreviated filings often bury
   *  D&A in the aggregate 60/66A cost without a line-item rubric). */
  daImputed: boolean;
  /** Rubric 631/4. Non-cash write-downs; added back. */
  writedowns: number;
  /** Rubric 635/8. Movement in provisions; non-cash, added back. */
  provisions: number;

  /** Rubric 76. Kept for internal audit only — starting from EBITDA
   *  means exceptional items never enter the bridge, so no display line. */
  exceptionalIncome: number;
  /** Rubric 66. Same as above — internal audit only. */
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
    const operatingProfit = rub(rubrics, "9901", fy);  // EBIT proxy

    // D&A (rubric 630) is often NOT filed in VKT abbreviated submissions —
    // the cost is embedded in total operating charges (60/66A) without a
    // line-item breakdown. Treating da = 0 in that case is load-bearing
    // wrong: EBITDA collapses to EBIT, and CapEx (derived from ΔNetFA +
    // D&A) flips sign whenever NetFA decreased through depreciation,
    // showing up as a phantom cash source roughly equal to D&A. Result:
    // an unreconciled gap of magnitude ≈ D&A ≈ EBITDA for asset-heavy SMEs.
    //
    // Impute D&A from the balance sheet when 630 is missing: D&A ≈
    // max(0, -Δ(NetFA)). Assumes gross CapEx ≈ 0 and disposals ≈ 0.
    // Wrong in growth-capex years (under-imputes D&A) but always better
    // than da = 0, because it zeroes out the phantom CapEx source.
    const daFiled = rub(rubrics, "630", fy);
    let da = daFiled ?? 0;
    let daImputed = false;
    if (daFiled == null && prev != null) {
      const dTangForDa = delta(rub(rubrics, "22/27", fy), rub(rubrics, "22/27", prev));
      const dIntangForDa = delta(rub(rubrics, "21", fy), rub(rubrics, "21", prev));
      if (dTangForDa != null || dIntangForDa != null) {
        const faDelta = (dTangForDa ?? 0) + (dIntangForDa ?? 0);
        const imputed = Math.max(0, -faDelta);
        if (imputed > 0) {
          da = imputed;
          daImputed = true;
        }
      }
    }

    // EBITDA per CLAUDE.md: 9901 + 630. Starting milestone for the
    // indirect bridge; null if operating profit isn't filed (very rare
    // — 9901 is the most reliably-reported rubric across filing types).
    const ebitda = operatingProfit != null ? operatingProfit + da : null;

    const financialIncome = rub(rubrics, "75", fy) ?? 0;
    // Store as cash impact so the UI can render the raw value without
    // an extra sign flip and so the CFO formula is all additive.
    const interestExpense = -(rub(rubrics, "65", fy) ?? 0);
    const incomeTax = -(rub(rubrics, "67/77", fy) ?? 0);

    // Need at least operating profit or net profit to build anything.
    const insufficientData = ebitda == null && netProfit == null;

    const writedowns = rub(rubrics, "631/4", fy) ?? 0;
    const provisions = rub(rubrics, "635/8", fy) ?? 0;

    // Exceptional — kept for direct-method audit only; no display line
    // when starting from EBITDA.
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

      // Fallback when per-bucket ST payables aren't filed: VKT
      // abbreviated submissions often report only the aggregate
      // 42/48 ("Amounts payable ≤ 1 year"). Derive the non-financial
      // part as Δ(42/48) − Δ(43). Still misses split between
      // trade/tax/social/other but captures the WC movement, which
      // otherwise drops out of the bridge entirely (silently creating
      // a gap equal to the missing payables movement).
      if (dApRaw == null && dTaxSocRaw == null && dOtherRaw == null) {
        const dAllStPay = delta(rub(rubrics, "42/48", fy), rub(rubrics, "42/48", prev));
        const dStDebtForPay = delta(rub(rubrics, "43", fy), rub(rubrics, "43", prev));
        if (dAllStPay != null) {
          const nonFinPayDelta = dAllStPay - (dStDebtForPay ?? 0);
          // Spread into the "other payables" bucket so it surfaces
          // in the WC detail rows rather than being invisible.
          deltaOtherPayables = nonFinPayDelta;
        }
      }

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
        // Back out cash-raised equity from the total-equity roll-forward:
        //   Δ(10/15) = net_profit − dividends_proposed + new_capital
        //              + Δ(12) revaluation  + Δ(15) grants received
        // Rearranging:
        //   new_capital = Δ(10/15) − net_profit + 694(fy) − Δ(12) − Δ(15)
        // Without the Δ(12) correction a material revaluation lands in
        // CFF as "new capital", creating a phantom financing inflow
        // whose magnitude equals the revaluation amount — a well-known
        // driver of large reconciliation gaps on asset-heavy SMEs.
        const dTotalEquity = delta(rub(rubrics, "10/15", fy), rub(rubrics, "10/15", prev));
        const divCurrent = rub(rubrics, "694", fy) ?? 0;
        const dRevalReserve = delta(rub(rubrics, "12", fy), rub(rubrics, "12", prev)) ?? 0;
        const dGrants = delta(rub(rubrics, "15", fy), rub(rubrics, "15", prev)) ?? 0;
        if (dTotalEquity != null && netProfit != null) {
          newCapital = dTotalEquity - netProfit + divCurrent - dRevalReserve - dGrants;
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

    // Rubric 694 is the dividend PROPOSED at year-end Y (paid in Y+1).
    // We deliberately use 694(fy), NOT 694(prev), because the bridge
    // relies on a "split treatment" that reconciles cleanly for filers
    // where 47/48 captures the dividend liability:
    //   (a) The cash paid in year Y (= 694(Y-1)) flows through ΔWC as
    //       the drop in rubric 47/48.
    //   (b) The new accrual (694(Y)) is non-cash at year-end Y but it
    //       reduces retained earnings, which the equity roll-forward
    //       subtracts. Showing -694(Y) in CFF closes the loop.
    // Switching to 694(prev) double-counted on VOL filers whose WC
    // bridge already captured the cash payment. An earlier version of
    // this fix attempted the lag shift and was reverted after the
    // correctness review flagged the regression on Colruyt-class data.
    const dividendsFiled = rub(rubrics, "694", fy) ?? 0;
    const dividendsPaid = dividendsFiled > 0 ? -dividendsFiled : 0;

    /* ========== INDIRECT METHOD CFO — EBITDA-start (primary) ========== */

    // CFO = EBITDA + 75 − 65 − 67/77 + 631/4 + 635/8 + ΔWC
    // Exceptional items (66, 76) drop out algebraically — they never
    // entered EBITDA. D&A (630) is inside EBITDA on the revenue side
    // already, so no separate add-back either.
    //
    // If EBITDA isn't computable (no 9901 filed), fall back to the
    // net-profit-start formula so we still produce a number rather
    // than a null on abbreviated/micro filings.
    let cashFromOps: number | null;
    if (prev == null) {
      cashFromOps = null;
    } else if (ebitda != null) {
      // interestExpense and incomeTax are already signed as cash impact
      // (negative for outflow), so the formula is all additive.
      cashFromOps =
        ebitda
        + financialIncome
        + interestExpense
        + incomeTax
        + writedowns
        + provisions
        + (wcChange ?? 0);
    } else if (netProfit != null) {
      cashFromOps =
        netProfit
        + da
        + writedowns
        + provisions
        - exceptionalIncome
        + exceptionalCharges
        + (wcChange ?? 0);
    } else {
      cashFromOps = null;
    }

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
      ebitda,
      financialIncome,
      interestExpense,
      incomeTax,
      da,
      daImputed,
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
