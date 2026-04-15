"use client";

import React from "react";
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
import { Users, Scale, Loader2 } from "lucide-react";
import { fmtEur, fmtNumber } from "@/lib/format";
import { useRouter } from "next/navigation";

/* ---------- Component ---------- */

interface SimilarTabProps {
  sortedSimilar: { enterprise_number: string; name: string; city: string; revenue: number | null; ebitda: number | null; fte_total: number | null; fiscal_year: number }[] | null;
  similarSort: { key: "name" | "revenue" | "ebitda" | "fte_total"; direction: "asc" | "desc" };
  setSimilarSort: (sort: { key: "name" | "revenue" | "ebitda" | "fte_total"; direction: "asc" | "desc" }) => void;
  cbe: string;
  financials: { summary: { fiscal_year: number; revenue: number | null }[] } | null;
  similarCompanies: unknown[] | null;
}

export function SimilarTab({
  sortedSimilar,
  similarSort,
  setSimilarSort,
  cbe,
  financials,
  similarCompanies,
}: SimilarTabProps) {
  const router = useRouter();

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

  const handleSort = (key: "name" | "revenue" | "ebitda" | "fte_total") => {
    setSimilarSort(
      similarSort.key === key
        ? { key, direction: similarSort.direction === "asc" ? "desc" : "asc" }
        : { key, direction: key === "name" ? "asc" : "desc" }
    );
  };

  const sortArrow = (key: "name" | "revenue" | "ebitda" | "fte_total") =>
    similarSort.key === key ? (similarSort.direction === "asc" ? " \u25B2" : " \u25BC") : "";

  const sortHeaderCls = (key: "name" | "revenue" | "ebitda" | "fte_total") =>
    `text-[10px] uppercase tracking-wider py-2 cursor-pointer hover:text-indigo-600 select-none ${similarSort.key === key ? "text-indigo-600 font-bold" : "font-semibold text-slate-500"}`;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2">Similar Companies</h3>
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
      <div className="rounded-xl border border-slate-200 overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50/80">
              <TableHead className={sortHeaderCls("name")} onClick={() => handleSort("name")}>Company{sortArrow("name")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 py-2">City</TableHead>
              <TableHead className={`${sortHeaderCls("revenue")} min-w-[180px]`} onClick={() => handleSort("revenue")}>Revenue{sortArrow("revenue")}</TableHead>
              <TableHead className={`${sortHeaderCls("ebitda")} text-right`} onClick={() => handleSort("ebitda")}>EBITDA{sortArrow("ebitda")}</TableHead>
              <TableHead className={`${sortHeaderCls("fte_total")} text-right`} onClick={() => handleSort("fte_total")}>FTE{sortArrow("fte_total")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedSimilar.map((sc) => {
              const revPct = sc.revenue != null ? Math.max(0, (sc.revenue / barMax) * 100) : 0;
              return (
              <TableRow key={sc.enterprise_number} className="hover:bg-slate-50/50">
                <TableCell className="py-2">
                  <Link href={`/company/${sc.enterprise_number}`} className="text-xs font-medium text-indigo-600 hover:text-indigo-800 hover:underline">
                    {sc.name}
                  </Link>
                </TableCell>
                <TableCell className="text-xs text-slate-500 py-2">{sc.city || "\u2014"}</TableCell>
                <TableCell className="py-2">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-4 bg-slate-50 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-indigo-100 rounded-full transition-all duration-500"
                        style={{ width: `${revPct}%` }}
                      />
                    </div>
                    <span className="text-xs text-slate-700 font-mono shrink-0 min-w-[60px] text-right">
                      {sc.revenue != null ? fmtEur(sc.revenue) : "\u2014"}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{sc.ebitda != null ? fmtEur(sc.ebitda) : "\u2014"}</TableCell>
                <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{sc.fte_total != null ? fmtNumber(sc.fte_total) : "\u2014"}</TableCell>
              </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
