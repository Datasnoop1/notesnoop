"use client";

import React from "react";
import { BarChart3, Shield, Loader2 } from "lucide-react";
import type { SectorBenchmark } from "@/lib/api";
import type { CompanyDetail } from "../types";

/* ---------- Component ---------- */

interface BenchmarkTabProps {
  benchmark: SectorBenchmark | null;
  detail: CompanyDetail;
}

export function BenchmarkTab({ benchmark, detail }: BenchmarkTabProps) {
  if (!benchmark) {
    return (
      <div className="py-8 text-center">
        <Loader2 className="w-6 h-6 animate-spin text-indigo-500 mx-auto mb-2" />
        <p className="text-sm text-slate-400">Loading sector benchmarks...</p>
      </div>
    );
  }

  if (benchmark.error) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        {benchmark.error === "no_nace" ? "No NACE code assigned to this company." : "No financial data available for benchmarking."}
      </p>
    );
  }

  const fmtBenchVal = (v: number | null, format: string) => {
    if (v == null) return "\u2014";
    if (format === "pct") return `${v.toFixed(1)}%`;
    if (format === "num") return v.toLocaleString("en-GB", { maximumFractionDigits: 0 });
    if (Math.abs(v) >= 1_000_000) return `\u20AC${(v / 1_000_000).toFixed(1)}M`;
    if (Math.abs(v) >= 1_000) return `\u20AC${(v / 1_000).toFixed(0)}K`;
    return `\u20AC${v.toFixed(0)}`;
  };

  const getQuartileLabel = (pct: number) => {
    if (pct >= 75) return { label: "Top quartile", color: "text-emerald-600 bg-emerald-50 border-emerald-200", dot: "bg-emerald-500" };
    if (pct >= 50) return { label: "Above median", color: "text-indigo-600 bg-indigo-50 border-indigo-200", dot: "bg-indigo-500" };
    if (pct >= 25) return { label: "Below median", color: "text-amber-600 bg-amber-50 border-amber-200", dot: "bg-amber-500" };
    return { label: "Bottom quartile", color: "text-rose-500 bg-rose-50 border-rose-200", dot: "bg-rose-400" };
  };

  // Score: average percentile across all metrics
  const avgPercentile = benchmark.benchmarks.length > 0
    ? benchmark.benchmarks.reduce((sum, b) => sum + (b.percentile ?? 0), 0) / benchmark.benchmarks.length
    : 0;
  const overallQuartile = getQuartileLabel(avgPercentile);

  return (
    <div className="space-y-5">
      {/* Header card */}
      <div className="rounded-xl border border-slate-200 bg-gradient-to-r from-slate-50 to-white p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <BarChart3 className="h-4 w-4 text-amber-500" />
              <h3 className="text-sm font-semibold text-slate-800">Sector Performance</h3>
            </div>
            <p className="text-xs text-slate-500">
              vs. <span className="font-medium text-slate-700">{benchmark.peer_count.toLocaleString()}</span> companies in{" "}
              <span className="font-medium text-slate-700">{benchmark.nace_label}</span>
            </p>
            <p className="text-[10px] text-slate-400 mt-0.5">NACE {benchmark.nace_code} · FY{benchmark.fiscal_year}</p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-slate-800 font-mono">P{avgPercentile.toFixed(0)}</div>
            <span className={`inline-flex items-center gap-1.5 text-[10px] font-medium rounded-full border px-2 py-0.5 mt-1 ${overallQuartile.color}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${overallQuartile.dot}`} />
              {overallQuartile.label} overall
            </span>
          </div>
        </div>
      </div>

      {/* Metric cards -- 2-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {benchmark.benchmarks.map((b) => {
          const pct = b.percentile ?? 0;
          const q = getQuartileLabel(pct);
          const barColor = pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-indigo-500" : pct >= 25 ? "bg-amber-500" : "bg-rose-400";

          return (
            <div key={b.metric} className="rounded-xl border border-slate-100 bg-white p-4 hover:shadow-sm transition-shadow">
              {/* Metric header */}
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold text-slate-700">{b.metric}</span>
                <span className={`inline-flex items-center gap-1 text-[10px] font-semibold rounded-full border px-2 py-0.5 ${q.color}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${q.dot}`} />
                  P{pct.toFixed(0)}
                </span>
              </div>

              {/* Company value -- prominent */}
              <div className="text-lg font-bold text-slate-900 font-mono mb-3">
                {fmtBenchVal(b.value, b.format)}
              </div>

              {/* Percentile bar */}
              <div className="relative h-2.5 bg-slate-100 rounded-full overflow-hidden mb-2">
                <div className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${pct}%` }} />
                {/* Quartile markers */}
                <div className="absolute top-0 bottom-0 left-1/4 w-px bg-slate-200" />
                <div className="absolute top-0 bottom-0 left-1/2 w-px bg-slate-300" />
                <div className="absolute top-0 bottom-0 left-3/4 w-px bg-slate-200" />
                {/* Company marker */}
                <div className="absolute top-[-3px] bottom-[-3px] w-0.5 bg-slate-800 rounded-full" style={{ left: `${pct}%` }} />
              </div>

              {/* Peer distribution */}
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded-md bg-slate-50 py-1.5 px-1">
                  <div className="text-[9px] text-slate-400 uppercase tracking-wider">P25</div>
                  <div className="text-[11px] font-mono font-medium text-slate-600">{fmtBenchVal(b.p25, b.format)}</div>
                </div>
                <div className="rounded-md bg-slate-50 py-1.5 px-1">
                  <div className="text-[9px] text-slate-400 uppercase tracking-wider">Median</div>
                  <div className="text-[11px] font-mono font-medium text-slate-600">{fmtBenchVal(b.median, b.format)}</div>
                </div>
                <div className="rounded-md bg-slate-50 py-1.5 px-1">
                  <div className="text-[9px] text-slate-400 uppercase tracking-wider">P75</div>
                  <div className="text-[11px] font-mono font-medium text-slate-600">{fmtBenchVal(b.p75, b.format)}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-[10px] text-slate-400 italic flex items-center gap-1.5">
        <Shield className="h-3 w-3" />
        Percentile rankings within NACE {benchmark.nace_code}. P75 means outperforming 75% of peers. Overall score is the average percentile across all metrics.
      </p>
    </div>
  );
}
