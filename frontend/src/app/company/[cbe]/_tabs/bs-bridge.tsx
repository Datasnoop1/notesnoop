"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { fmtEur } from "@/lib/format";

/* Balance-sheet bridge: Assets bar (top) and Equity + Liabilities bar
 * (bottom), each broken into segments that add up to total assets.
 *
 * Pure CSS flex-based rendering — each segment is a child div with width
 * calculated from % of total assets. Guaranteed to sum exactly to 100%
 * because residual segments absorb any rounding / data gaps.
 *
 * Year picker + collapsible + softer palette, consistent with PnlWaterfall.
 */

export interface BsYearRow {
  fiscal_year: number;
  totalAssets: number | null;
  totalNonCurrentAssets: number | null;   // fixed_assets rubric 20/28
  inventories: number | null;
  tradeReceivables: number | null;
  cash: number | null;
  currentInvestments: number | null;
  equity: number | null;
  ltDebt: number | null;
  stFinDebt: number | null;
  tradePayables: number | null;
}

interface Segment {
  label: string;
  value: number;
  color: string;     // bg-xxx class
  text?: string;     // tailwind text class; default slate-700 for light bgs
}

interface Props {
  bsRows: BsYearRow[];
  defaultCollapsed?: boolean;
}

export function BalanceSheetBridge({ bsRows, defaultCollapsed = false }: Props) {
  const years = useMemo(
    () => bsRows.map((r) => r.fiscal_year).filter((y) => typeof y === "number").sort((a, b) => b - a),
    [bsRows],
  );

  const [open, setOpen] = useState(!defaultCollapsed);
  const [fy, setFy] = useState<number | null>(years[0] ?? null);

  const row = useMemo(
    () => bsRows.find((r) => r.fiscal_year === fy) ?? bsRows[0],
    [bsRows, fy],
  );

  if (!row || !row.totalAssets || row.totalAssets <= 0) return null;
  const target = row.totalAssets;

  // Assets side — each component clamped to ≥0; residual fills the gap.
  const fa = Math.max(row.totalNonCurrentAssets ?? 0, 0);
  const inv = Math.max(row.inventories ?? 0, 0);
  const rec = Math.max(row.tradeReceivables ?? 0, 0);
  const cash = Math.max((row.cash ?? 0) + (row.currentInvestments ?? 0), 0);
  const otherA = Math.max(target - fa - inv - rec - cash, 0);

  // Expanded gray scale so neighbouring segments are visually distinguishable.
  // Asset side: fixed assets (anchor) darkest; liquidity (cash) also dark; mid
  // working-capital items split between slate-300 and slate-200; residual
  // slate-100. Gives five distinct tones across the bar.
  const assetSegs: Segment[] = [
    { label: "Fixed assets",  value: fa,     color: "bg-slate-500", text: "text-white" },
    { label: "Inventories",   value: inv,    color: "bg-slate-300" },
    { label: "Receivables",   value: rec,    color: "bg-slate-200" },
    { label: "Cash",          value: cash,   color: "bg-slate-400", text: "text-white" },
    { label: "Other",         value: otherA, color: "bg-slate-100" },
  ];

  // Equity + Liabilities side.
  const rawEq = row.equity ?? 0;
  const negEq = rawEq < 0 ? -rawEq : 0;
  const eq = Math.max(rawEq, 0);
  const ltd = Math.max(row.ltDebt ?? 0, 0);
  const std = Math.max(row.stFinDebt ?? 0, 0);
  const tp = Math.max(row.tradePayables ?? 0, 0);
  const otherL = Math.max(target - eq - ltd - std - tp, 0);

  // Liability side: equity (anchor) darkest; LT debt next; ST debt and trade
  // payables mid tones; residual lightest. Each bucket has its own shade so
  // the bar reads left-to-right as a continuous gradient.
  const liabSegs: Segment[] = [
    { label: "Equity",           value: eq,     color: "bg-slate-600", text: "text-white" },
    { label: "LT debt",          value: ltd,    color: "bg-slate-400", text: "text-white" },
    { label: "ST fin. debt",     value: std,    color: "bg-slate-300" },
    { label: "Trade payables",   value: tp,     color: "bg-slate-200" },
    { label: "Other",            value: otherL, color: "bg-slate-100" },
  ];

  const renderBar = (segs: Segment[], label: string) => (
    <div className="flex items-center gap-3">
      <div className="w-[120px] md:w-[150px] shrink-0 text-right text-[11px] font-semibold text-slate-600">
        {label}
      </div>
      <div className="flex-1 flex h-8 md:h-9 bg-slate-50 rounded overflow-hidden border border-slate-100">
        {segs.map((s) => {
          const pct = target > 0 ? (s.value / target) * 100 : 0;
          if (pct < 0.1) return null;
          return (
            <div
              key={s.label}
              className={`${s.color} h-full flex items-center justify-center text-[10px] ${s.text ?? "text-slate-700"} font-medium overflow-hidden transition-all`}
              style={{ width: `${pct}%` }}
              title={`${s.label}: ${fmtEur(s.value)} (${pct.toFixed(1)}%)`}
            >
              {pct >= 10 ? s.label : ""}
            </div>
          );
        })}
      </div>
      <div className="w-[100px] md:w-[120px] shrink-0 text-right font-mono text-[11px] font-semibold text-slate-700">
        {fmtEur(target)}
      </div>
    </div>
  );

  const renderLegend = (segs: Segment[]) => (
    <div className="flex flex-wrap gap-2 ml-[135px] md:ml-[165px] mt-1">
      {segs.filter((s) => s.value > 0).map((s) => {
        const pct = target > 0 ? (s.value / target) * 100 : 0;
        return (
          <span key={s.label} className="inline-flex items-center gap-1 text-[10px] text-slate-500">
            <span className={`inline-block w-2 h-2 rounded-sm ${s.color}`} />
            {s.label} <span className="font-mono text-slate-400">{fmtEur(s.value)} ({pct.toFixed(0)}%)</span>
          </span>
        );
      })}
    </div>
  );

  return (
    <div className="rounded-lg border bg-white mb-4">
      <div className="flex items-center justify-between px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 hover:bg-slate-50 -mx-1 px-1 py-0.5 rounded transition-colors"
          aria-expanded={open}
        >
          {open ? <ChevronDown className="h-3.5 w-3.5 text-slate-400" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-400" />}
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Balance-sheet bridge
          </h3>
          <span className="text-[10px] text-slate-400">— FY{row.fiscal_year}</span>
        </button>
        {years.length > 1 && (
          <select
            value={fy ?? row.fiscal_year}
            onChange={(e) => setFy(Number(e.target.value))}
            className="h-10 md:h-7 text-base md:text-[11px] border border-slate-200 rounded px-2 md:px-1.5 bg-white text-slate-600 hover:border-slate-300"
            aria-label="Fiscal year"
          >
            {years.map((y) => <option key={y} value={y}>FY{y}</option>)}
          </select>
        )}
      </div>
      {open && (
        <div className="px-3 pb-3 pt-2 border-t border-slate-100 space-y-3">
          <div>
            {renderBar(assetSegs, "Assets")}
            {renderLegend(assetSegs)}
          </div>
          <div>
            {renderBar(liabSegs, "Equity + Liab.")}
            {renderLegend(liabSegs)}
          </div>
          {negEq > 0 && (
            <p className="text-[10px] text-rose-600">
              ⚠ Negative equity ({fmtEur(negEq)}): liabilities exceed assets by this
              amount. Equity bucket above is clamped to 0 so both bars visually
              match the total-assets target.
            </p>
          )}
          <p className="text-[10px] text-slate-400 italic">
            Both bars scaled to total assets — segment widths show the relative
            composition. Any data-quality gap lands in &quot;Other&quot; so the two bars
            always balance.
          </p>
        </div>
      )}
    </div>
  );
}
