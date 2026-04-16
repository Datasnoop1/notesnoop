"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Users, Scale, Loader2, Sparkles } from "lucide-react";
import { fmtEur, fmtNumber } from "@/lib/format";
import { useRouter } from "next/navigation";
import type { SimilarCompany } from "@/lib/api";

/* ---------- Types ---------- */

type SortKey = "name" | "revenue" | "ebitda" | "fte_total" | "ebit" | "net_profit" | "equity" | "total_assets" | "personnel_costs" | "ebitda_margin" | "equity_ratio";

interface SimilarTabProps {
  sortedSimilar: SimilarCompany[] | null;
  similarSort: { key: SortKey; direction: "asc" | "desc" };
  setSimilarSort: (sort: { key: SortKey; direction: "asc" | "desc" }) => void;
  cbe: string;
  financials: { summary: { fiscal_year: number; revenue: number | null }[] } | null;
  similarCompanies: unknown[] | null;
}

/* ---------- Helpers ---------- */

function fmtPct(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "\u2014";
  return `${v.toFixed(1)}%`;
}

function computeMargin(ebitda: number | null, revenue: number | null): number | null {
  if (ebitda == null || !revenue) return null;
  return (ebitda / revenue) * 100;
}

function computeEquityRatio(equity: number | null, totalAssets: number | null): number | null {
  if (equity == null || !totalAssets) return null;
  return (equity / totalAssets) * 100;
}

/* ---------- Component ---------- */

export function SimilarTab({
  sortedSimilar,
  similarSort,
  setSimilarSort,
  cbe,
  financials,
  similarCompanies,
}: SimilarTabProps) {
  const router = useRouter();
  const [aiReasons, setAiReasons] = useState<Record<string, string>>({});
  const [aiLoading, setAiLoading] = useState(false);
  const [aiEnhanced, setAiEnhanced] = useState(false);

  const enhanceWithAi = async () => {
    setAiLoading(true);
    try {
      const res = await fetch(`/api/companies/${cbe}/similar/ai`);
      const data = await res.json();
      const reasons: Record<string, string> = {};
      for (const item of data) {
        if (item.ai_reason) reasons[item.enterprise_number] = item.ai_reason;
      }
      setAiReasons(reasons);
      setAiEnhanced(true);
    } catch { /* ignore */ }
    finally { setAiLoading(false); }
  };

  if (similarCompanies === null) {
    return (
      <div className="py-6 text-center">
        <Loader2 className="w-5 h-5 animate-spin text-indigo-400 mx-auto mb-1" />
        <p className="text-xs text-slate-400">Loading similar companies...</p>
      </div>
    );
  }

  if (!sortedSimilar || sortedSimilar.length === 0) {
    return (
      <div className="py-12 text-center">
        <Users className="w-8 h-8 text-slate-300 mx-auto mb-2" />
        <p className="text-sm font-medium text-slate-400">No similar companies found in this sector</p>
        <p className="text-xs text-slate-300 mt-1">This company may have a unique NACE code or no peers with comparable revenue</p>
      </div>
    );
  }

  const maxRevenue = Math.max(...sortedSimilar.map((sc) => sc.revenue ?? 0), 1);
  const thisRevenue = financials?.summary?.length
    ? [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year)[0]?.revenue ?? 0
    : 0;
  const barMax = Math.max(maxRevenue, thisRevenue, 1);

  const handleSort = (key: SortKey) => {
    setSimilarSort(
      similarSort.key === key
        ? { key, direction: similarSort.direction === "asc" ? "desc" : "asc" }
        : { key, direction: key === "name" ? "asc" : "desc" }
    );
  };

  const sortArrow = (key: SortKey) =>
    similarSort.key === key ? (similarSort.direction === "asc" ? " \u25B2" : " \u25BC") : "";

  const sortHeaderCls = (key: SortKey) =>
    `text-[10px] uppercase tracking-wider py-2 cursor-pointer hover:text-indigo-600 select-none whitespace-nowrap ${similarSort.key === key ? "text-indigo-600 font-bold" : "font-semibold text-slate-500"}`;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2">
          Similar Companies
          <span className="ml-2 text-[10px] font-normal text-slate-400">({sortedSimilar.length})</span>
        </h3>
        <div className="flex items-center gap-2">
          {!aiEnhanced && (
            <button
              onClick={enhanceWithAi}
              disabled={aiLoading}
              className="inline-flex items-center gap-1 h-7 px-3 text-[11px] font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50 transition-colors"
            >
              {aiLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
              {aiLoading ? "Ranking..." : "AI Rank"}
            </button>
          )}
          {aiEnhanced && (
            <span className="inline-flex items-center gap-1 text-[10px] text-indigo-500 font-medium">
              <Sparkles className="w-3 h-3" /> AI-enhanced
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-[11px] text-indigo-600 border-indigo-200 hover:bg-indigo-50 px-3"
            onClick={() => {
              const cbes = sortedSimilar.map((sc) => sc.enterprise_number);
              if (!cbes.includes(cbe)) cbes.unshift(cbe);
              sessionStorage.setItem("compare_companies", JSON.stringify(cbes));
              router.push("/compare");
            }}
          >
            <Scale className="w-3 h-3 mr-1" />
            Compare all
          </Button>
        </div>
      </div>
      <div className="rounded-xl border border-slate-200 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50/80">
              <TableHead className={`${sortHeaderCls("name")} sticky left-0 bg-slate-50/80 z-10`} onClick={() => handleSort("name")}>Company{sortArrow("name")}</TableHead>
              <TableHead className={`${sortHeaderCls("revenue")} min-w-[180px]`} onClick={() => handleSort("revenue")}>Revenue{sortArrow("revenue")}</TableHead>
              <TableHead className={`${sortHeaderCls("ebitda")} text-right`} onClick={() => handleSort("ebitda")}>EBITDA{sortArrow("ebitda")}</TableHead>
              <TableHead className={`${sortHeaderCls("ebitda_margin")} text-right`} onClick={() => handleSort("ebitda_margin")}>Margin %{sortArrow("ebitda_margin")}</TableHead>
              <TableHead className={`${sortHeaderCls("ebit")} text-right`} onClick={() => handleSort("ebit")}>EBIT{sortArrow("ebit")}</TableHead>
              <TableHead className={`${sortHeaderCls("net_profit")} text-right`} onClick={() => handleSort("net_profit")}>Net Profit{sortArrow("net_profit")}</TableHead>
              <TableHead className={`${sortHeaderCls("equity")} text-right`} onClick={() => handleSort("equity")}>Equity{sortArrow("equity")}</TableHead>
              <TableHead className={`${sortHeaderCls("total_assets")} text-right`} onClick={() => handleSort("total_assets")}>Total Assets{sortArrow("total_assets")}</TableHead>
              <TableHead className={`${sortHeaderCls("equity_ratio")} text-right`} onClick={() => handleSort("equity_ratio")}>Equity %{sortArrow("equity_ratio")}</TableHead>
              <TableHead className={`${sortHeaderCls("fte_total")} text-right`} onClick={() => handleSort("fte_total")}>FTE{sortArrow("fte_total")}</TableHead>
              <TableHead className={`${sortHeaderCls("personnel_costs")} text-right`} onClick={() => handleSort("personnel_costs")}>Staff Costs{sortArrow("personnel_costs")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedSimilar.map((sc) => {
              const revPct = sc.revenue != null ? Math.max(0, (sc.revenue / barMax) * 100) : 0;
              const margin = computeMargin(sc.ebitda, sc.revenue);
              const eqRatio = computeEquityRatio(sc.equity, sc.total_assets);
              return (
              <TableRow key={sc.enterprise_number} className="hover:bg-slate-50/50">
                <TableCell className="py-2 sticky left-0 bg-white z-10">
                  <Link href={`/company/${sc.enterprise_number}`} className="text-xs font-medium text-indigo-600 hover:text-indigo-800 hover:underline whitespace-nowrap">
                    {sc.name}
                  </Link>
                  <div className="text-[10px] text-slate-400">{sc.city || "\u2014"}</div>
                  {aiReasons[sc.enterprise_number] && (
                    <div className="text-[10px] text-indigo-500 mt-0.5 italic max-w-[250px] truncate" title={aiReasons[sc.enterprise_number]}>
                      {aiReasons[sc.enterprise_number]}
                    </div>
                  )}
                </TableCell>
                <TableCell className="py-2">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-4 bg-slate-50 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-indigo-100 rounded-full transition-all duration-500"
                        style={{ width: `${revPct}%` }}
                      />
                    </div>
                    <span className="text-xs text-slate-700 font-mono shrink-0 min-w-[60px] text-right">
                      {fmtEur(sc.revenue)}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{fmtEur(sc.ebitda)}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{fmtPct(margin)}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{fmtEur(sc.ebit)}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{fmtEur(sc.net_profit)}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{fmtEur(sc.equity)}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{fmtEur(sc.total_assets)}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{fmtPct(eqRatio)}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{sc.fte_total != null ? fmtNumber(sc.fte_total) : "\u2014"}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{fmtEur(sc.personnel_costs)}</TableCell>
              </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
