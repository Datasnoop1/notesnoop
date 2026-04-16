"use client";

import React, { useState, useEffect, useCallback } from "react";
import { getCompanyValuation } from "@/lib/api";
import type { ValuationData } from "@/lib/api";
import { fmtEur } from "@/lib/format";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { ExternalLink, Loader2 } from "lucide-react";

interface ValuationTabProps {
  cbe: string;
}

function fmtMultiple(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v.toFixed(1)}×`;
}

function VlerickBanner({ url }: { url: string }) {
  return (
    <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-3 py-2.5 text-[11px] text-indigo-900">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-semibold uppercase tracking-wider text-[10px]">Source</span>
        <span className="text-indigo-400">|</span>
        <span>
          Multiples sourced from the{" "}
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 font-semibold text-indigo-700 underline decoration-indigo-300 underline-offset-2 hover:decoration-indigo-500"
          >
            Vlerick M&amp;A Monitor
            <ExternalLink className="h-3 w-3" />
          </a>
          , an annual survey of Belgian M&amp;A transactions published by Vlerick Business School.
        </span>
      </div>
    </div>
  );
}

export function ValuationTab({ cbe }: ValuationTabProps) {
  const [data, setData] = useState<ValuationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"size" | "sector">("sector");
  const [sectorOverride, setSectorOverride] = useState<string | null>(null);

  const load = useCallback(
    async (override?: string | null) => {
      setLoading(true);
      setError(null);
      try {
        const result = await getCompanyValuation(cbe, override ?? undefined);
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load valuation");
      } finally {
        setLoading(false);
      }
    },
    [cbe]
  );

  useEffect(() => {
    load();
  }, [load]);

  const handleSectorChange = (newSector: string) => {
    const override = newSector === "" ? null : newSector;
    setSectorOverride(override);
    load(override);
  };

  if (loading && !data) {
    return (
      <div className="py-12 text-center">
        <Loader2 className="inline h-5 w-5 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        Could not load valuation: {error}
      </p>
    );
  }

  if (!data || data.status === "no_financial_data" || !data.profile) {
    return (
      <div className="space-y-4">
        <VlerickBanner url={data?.vlerick_reference?.url ?? "https://www.vlerick.com"} />
        <p className="py-8 text-center text-sm text-slate-500">
          No financial data available yet. Load the company&apos;s NBB filings to compute a valuation.
        </p>
      </div>
    );
  }

  const { profile, years, vlerick_reference, pro_memoria_note } = data;
  const activeMultiple = view === "size" ? profile.size_multiple : profile.sector_multiple;
  const activeLabel =
    view === "size"
      ? `${profile.size_bracket_label} size bracket`
      : profile.vlerick_sector_label;

  const sourceTag =
    profile.vlerick_sector_source === "user_override"
      ? "Manual override"
      : profile.vlerick_sector_source === "nace_mapping"
      ? `Auto-detected from NACE ${profile.nace_code ?? ""}`
      : "Default (no NACE match)";

  return (
    <div className="space-y-5">
      {/* Vlerick source banner — prominent at the top */}
      <VlerickBanner url={vlerick_reference.url} />

      {/* Plain-English explainer */}
      <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700">
        <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
          How this valuation works
        </h3>
        <p className="text-[13px] leading-relaxed">
          We take the company&apos;s <b>EBITDA</b> (profit before interest, tax, depreciation and amortisation)
          and multiply it by what similar Belgian companies were sold for in {vlerick_reference.data_year},
          according to the{" "}
          <a
            href={vlerick_reference.url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-semibold text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:decoration-indigo-500"
          >
            {vlerick_reference.report}
          </a>
          . That gives us the <b>Enterprise Value</b> — what a buyer would pay for the whole business.
          We then subtract what the company owes to banks (minus its cash) to get the{" "}
          <b>Equity Value</b> — roughly what the shareholders would walk away with in a sale.
        </p>
      </div>

      {/* Toggle + sector picker */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
          <button
            onClick={() => setView("sector")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
              view === "sector"
                ? "bg-indigo-600 text-white"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            By sector
          </button>
          <button
            onClick={() => setView("size")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
              view === "size"
                ? "bg-indigo-600 text-white"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            By size
          </button>
        </div>

        {view === "sector" && (
          <div className="flex items-center gap-2">
            <label className="text-[11px] uppercase tracking-wider text-slate-500">
              Sector
            </label>
            <select
              value={sectorOverride ?? profile.vlerick_sector}
              onChange={(e) => handleSectorChange(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 focus:border-indigo-400 focus:outline-none"
            >
              {profile.available_sectors.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
            <span className="text-[10px] text-slate-400 italic">{sourceTag}</span>
          </div>
        )}
      </div>

      {/* Headline summary card */}
      <div className="rounded-lg border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Applied multiple
            </div>
            <div className="mt-0.5 text-3xl font-bold text-indigo-600">
              {fmtMultiple(activeMultiple)}
            </div>
            <div className="mt-1 text-[11px] text-slate-500">
              EV/EBITDA for <b>{activeLabel}</b>
              <br />
              <span className="text-slate-400">
                Vlerick M&amp;A Monitor {vlerick_reference.data_year + 1} (data for {vlerick_reference.data_year})
              </span>
            </div>
          </div>
          {loading && (
            <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
          )}
        </div>
      </div>

      {/* Three-year ladder */}
      <div>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-emerald-500 pl-2">
          Three-year valuation ladder
        </h3>
        <div className="overflow-x-auto rounded-lg border bg-white">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs min-w-[220px]">Step</TableHead>
                {years.map((y) => (
                  <TableHead key={y.fiscal_year ?? Math.random()} className="text-right text-xs min-w-[120px]">
                    FY{y.fiscal_year ?? "—"}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="text-xs py-1.5 text-slate-700 font-medium">
                  EBITDA
                  <div className="text-[10px] text-slate-400 font-normal">Profit before interest, tax &amp; D&amp;A</div>
                </TableCell>
                {years.map((y, i) => (
                  <TableCell key={i} className="text-right font-mono text-xs py-1.5">
                    {fmtEur(y.ebitda)}
                  </TableCell>
                ))}
              </TableRow>
              <TableRow className="bg-indigo-50/30">
                <TableCell className="text-xs py-1.5 text-indigo-700 font-medium">
                  × Vlerick multiple
                  <div className="text-[10px] text-slate-400 font-normal">
                    Applied: {activeLabel}
                  </div>
                </TableCell>
                {years.map((y, i) => (
                  <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-indigo-700">
                    {fmtMultiple(activeMultiple)}
                  </TableCell>
                ))}
              </TableRow>
              <TableRow className="border-t-2 border-slate-200">
                <TableCell className="text-xs py-1.5 text-slate-800 font-semibold">
                  = Enterprise Value
                  <div className="text-[10px] text-slate-400 font-normal">What a buyer pays for the business</div>
                </TableCell>
                {years.map((y, i) => {
                  const ev = view === "size" ? y.by_size.enterprise_value : y.by_sector.enterprise_value;
                  return (
                    <TableCell key={i} className="text-right font-mono text-xs py-1.5 font-semibold text-slate-800">
                      {fmtEur(ev || null)}
                    </TableCell>
                  );
                })}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs py-1.5 text-slate-600">
                  − Financial debt
                  <div className="text-[10px] text-slate-400">Long-term + short-term bank debt</div>
                </TableCell>
                {years.map((y, i) => (
                  <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-slate-600">
                    {fmtEur(y.financial_debt || null)}
                  </TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs py-1.5 text-slate-600">
                  + Cash &amp; equivalents
                  <div className="text-[10px] text-slate-400">Cash + short-term investments</div>
                </TableCell>
                {years.map((y, i) => (
                  <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-slate-600">
                    {fmtEur(y.cash_and_equivalents || null)}
                  </TableCell>
                ))}
              </TableRow>
              <TableRow className="bg-slate-50/50">
                <TableCell className="text-xs py-1.5 text-slate-700 font-medium">
                  = Net debt
                  <div className="text-[10px] text-slate-400 font-normal">Debt minus cash</div>
                </TableCell>
                {years.map((y, i) => (
                  <TableCell key={i} className="text-right font-mono text-xs py-1.5 font-medium text-slate-700">
                    {fmtEur(y.net_debt || null)}
                  </TableCell>
                ))}
              </TableRow>
              <TableRow className="border-t-2 border-slate-300 bg-emerald-50/40">
                <TableCell className="text-xs py-2 text-emerald-900 font-bold">
                  = Equity Value
                  <div className="text-[10px] text-emerald-700/70 font-normal">What shareholders receive</div>
                </TableCell>
                {years.map((y, i) => {
                  const eq = view === "size" ? y.by_size.equity_value : y.by_sector.equity_value;
                  return (
                    <TableCell key={i} className="text-right font-mono text-sm py-2 font-bold text-emerald-800">
                      {fmtEur(eq)}
                    </TableCell>
                  );
                })}
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Pro memoria note */}
      {pro_memoria_note && (
        <div className="rounded-lg border border-amber-100 bg-amber-50/40 p-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-amber-700 mb-1">
            Pro memoria
          </div>
          <p className="text-[11px] leading-relaxed text-amber-900">
            {pro_memoria_note}
          </p>
        </div>
      )}

      {/* Source footer — prominent */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
          About this data
        </div>
        <p className="text-[11px] leading-relaxed text-slate-600">
          Valuation multiples come from the{" "}
          <a
            href={vlerick_reference.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 font-semibold text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:decoration-indigo-500"
          >
            {vlerick_reference.report}
            <ExternalLink className="h-3 w-3" />
          </a>
          , published annually by {vlerick_reference.publisher}. The report surveys
          dealmakers active on the Belgian M&amp;A market and reports median
          EV/EBITDA multiples by deal size and industry. {vlerick_reference.note}
        </p>
        <p className="mt-2 text-[10px] italic text-slate-400">
          This is a reference estimate based on market medians. Actual deal value depends on
          growth, margins, customer concentration, synergies, and negotiation. Not investment advice.
        </p>
      </div>
    </div>
  );
}
