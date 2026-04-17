"use client";

import React, { useState, useEffect, useCallback } from "react";
import { getCompanyValuation } from "@/lib/api";
import type { ValuationData, MultipleSourceKey } from "@/lib/api";
import { fmtEur, fmtCbe } from "@/lib/format";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { ExternalLink, Loader2, FileSpreadsheet, FileText } from "lucide-react";

interface ValuationTabProps {
  cbe: string;
  companyName?: string | null;
}

function fmtMultiple(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v.toFixed(1)}×`;
}

type Unit = "auto" | "full" | "k" | "m";

function fmtEurUnit(v: number | null | undefined, unit: Unit): string {
  if (v == null || isNaN(v)) return "—";
  if (unit === "auto") return fmtEur(v);
  const neg = v < 0;
  const a = Math.abs(v);
  let s: string;
  if (unit === "m") s = `€${(a / 1e6).toFixed(2)}M`;
  else if (unit === "k") s = `€${Math.round(a / 1e3).toLocaleString("en-US")}K`;
  else s = `€${Math.round(a).toLocaleString("en-US")}`;
  return neg ? `-${s}` : s;
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

export function ValuationTab({ cbe, companyName }: ValuationTabProps) {
  const [data, setData] = useState<ValuationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"size" | "sector">("sector");
  const [sectorOverride, setSectorOverride] = useState<string | null>(null);
  const [unit, setUnit] = useState<Unit>("auto");
  const [sourceKey, setSourceKey] = useState<MultipleSourceKey>("vlerick");
  const [exporting, setExporting] = useState(false);
  const fmt = (v: number | null | undefined) => fmtEurUnit(v, unit);

  const handleExportExcel = async () => {
    console.log("[valuation] Excel export clicked, data:", !!data);
    if (!data) {
      alert("No valuation data loaded yet — wait for the table to render.");
      return;
    }
    setExporting(true);
    try {
      const { generateValuationExcel } = await import("@/lib/export/valuation");
      await generateValuationExcel(data, companyName || fmtCbe(cbe), cbe, view);
    } catch (err) {
      console.error("[valuation] Excel export failed:", err);
      alert("Excel export failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setExporting(false);
    }
  };

  const handleExportPdf = () => {
    // "Exact copy of the current webpage": use the browser's native print
    // dialog. The site's @media print CSS hides nav/footer/ads; the no-print
    // class on the controls row hides the toggles. User picks "Save as PDF"
    // in the print dialog to download.
    window.print();
  };

  const load = useCallback(
    async (override?: string | null, src?: MultipleSourceKey) => {
      setLoading(true);
      setError(null);
      try {
        const result = await getCompanyValuation(cbe, override ?? undefined, src ?? sourceKey);
        setData(result);
        // If the selected source doesn't support the current view, auto-switch.
        if (result?.source) {
          if (view === "size" && !result.source.has_size) setView("sector");
          if (view === "sector" && !result.source.has_sector) setView("size");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load valuation");
      } finally {
        setLoading(false);
      }
    },
    [cbe, sourceKey, view]
  );

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cbe]);

  const handleSectorChange = (newSector: string) => {
    const override = newSector === "" ? null : newSector;
    setSectorOverride(override);
    load(override);
  };

  const handleSourceChange = (next: MultipleSourceKey) => {
    if (next === sourceKey) return;
    setSourceKey(next);
    setSectorOverride(null); // source change resets any manual sector override
    load(null, next);
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

  const srcMeta = data.source;
  const sources = data.available_sources ?? [];
  const srcHasSize = srcMeta?.has_size ?? true;
  const srcHasSector = srcMeta?.has_sector ?? true;

  const sourceTag =
    profile.vlerick_sector_source === "user_override"
      ? "Manual override"
      : profile.vlerick_sector_source === "ai_classification"
      ? `AI-classified${profile.ai_sector_confidence ? ` · confidence: ${profile.ai_sector_confidence}` : ""}${profile.ai_sector_reasoning ? ` · ${profile.ai_sector_reasoning}` : ""}`
      : profile.vlerick_sector_source === "nace_mapping"
      ? `Auto-detected from NACE ${profile.nace_code ?? ""}`
      : "Default (no NACE match)";

  return (
    <div className="space-y-4 valuation-print-root">
      {/* Compact header strip — title, source, view toggle, sector picker, unit toggle */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 pb-3 border-b border-slate-200">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Indicative valuation
          </div>
          <div className="mt-0.5 text-[11px] text-slate-600">
            Based on the{" "}
            <a
              href={vlerick_reference.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 font-semibold text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:decoration-indigo-500"
            >
              {vlerick_reference.report}
              <ExternalLink className="h-3 w-3" />
            </a>
            {srcMeta?.scope && (
              <span className="ml-1 text-slate-400">· {srcMeta.scope}</span>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 no-print">
          {/* Source toggle — pick which reference dataset's multiples to use */}
          {sources.length > 1 && (
            <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5" title="Multiple source">
              {sources.map((s) => (
                <button
                  key={s.key}
                  onClick={() => handleSourceChange(s.key)}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition ${
                    sourceKey === s.key
                      ? "bg-indigo-600 text-white"
                      : "text-slate-500 hover:text-slate-700"
                  }`}
                  title={s.label}
                >
                  {s.key === "vlerick" ? "Vlerick" : s.key === "damodaran" ? "Damodaran" : "Argos"}
                </button>
              ))}
            </div>
          )}

          {/* Single combined basis selector — view + sector grouped in one
              dropdown so the layout doesn't shift when switching modes. */}
          <select
            value={view === "sector" ? `sector:${sectorOverride ?? profile.vlerick_sector}` : "size:auto"}
            onChange={(e) => {
              const [kind, key] = e.target.value.split(":");
              if (kind === "sector") {
                setView("sector");
                handleSectorChange(key);
              } else {
                setView("size");
              }
            }}
            className="rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-indigo-400 focus:outline-none min-w-[180px]"
            title={sourceTag}
          >
            {srcHasSector && (
              <optgroup label="By sector">
                {profile.available_sectors.map((s) => (
                  <option key={s.key} value={`sector:${s.key}`}>
                    By sector — {s.label}
                  </option>
                ))}
              </optgroup>
            )}
            {srcHasSize && (
              <optgroup label="By size">
                <option value="size:auto">
                  By size — {profile.size_bracket_label} (auto)
                </option>
              </optgroup>
            )}
          </select>

          {/* Unit toggle */}
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5" title="Display unit">
            {([
              { key: "auto", label: "Auto" },
              { key: "m",    label: "€M"   },
              { key: "k",    label: "€k"   },
              { key: "full", label: "€"    },
            ] as { key: Unit; label: string }[]).map((opt) => (
              <button
                key={opt.key}
                onClick={() => setUnit(opt.key)}
                className={`rounded-md px-2 py-1 text-[11px] font-medium transition ${
                  unit === opt.key
                    ? "bg-slate-800 text-white"
                    : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* Export buttons */}
          <div className="inline-flex items-center gap-1 no-print">
            <button
              onClick={handleExportExcel}
              disabled={exporting}
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 hover:border-emerald-300 hover:text-emerald-700 disabled:opacity-50 transition"
              title="Export to Excel"
            >
              {exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileSpreadsheet className="h-3 w-3 text-emerald-600" />}
              Excel
            </button>
            <button
              onClick={handleExportPdf}
              disabled={exporting}
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 hover:border-rose-300 hover:text-rose-600 disabled:opacity-50 transition"
              title="Export to PDF"
            >
              {exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileText className="h-3 w-3 text-rose-500" />}
              PDF
            </button>
          </div>
        </div>
      </div>

      {/* Headline snapshot — horizontal 4-column summary for the latest year */}
      {(() => {
        const latest = years[years.length - 1];
        const latestEv = view === "size" ? latest?.by_size.enterprise_value : latest?.by_sector.enterprise_value;
        const latestEquity = view === "size" ? latest?.by_size.equity_value : latest?.by_sector.equity_value;
        const fyLabel = latest?.fiscal_year ? `FY${latest.fiscal_year}` : "latest";
        return (
          <div className="relative rounded-lg border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-4">
            {loading && (
              <Loader2 className="absolute top-3 right-3 h-4 w-4 animate-spin text-slate-400" />
            )}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Applied multiple
                </div>
                <div className="mt-0.5 text-2xl font-bold text-indigo-600">
                  {fmtMultiple(activeMultiple)}
                </div>
                <div className="mt-0.5 text-[10px] text-slate-500 truncate" title={activeLabel}>
                  {activeLabel}
                </div>
              </div>
              <div className="sm:border-l sm:border-slate-200 sm:pl-4">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  EBITDA ({fyLabel})
                </div>
                <div className="mt-0.5 text-2xl font-bold text-slate-800">
                  {fmt(latest?.ebitda ?? null)}
                </div>
                <div className="mt-0.5 text-[10px] text-slate-400">
                  Profit before int., tax &amp; D&amp;A
                </div>
              </div>
              <div className="sm:border-l sm:border-slate-200 sm:pl-4">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Enterprise value
                </div>
                <div className="mt-0.5 text-2xl font-bold text-slate-800">
                  {fmt(latestEv ?? null)}
                </div>
                <div className="mt-0.5 text-[10px] text-slate-400">
                  What a buyer pays
                </div>
              </div>
              <div className="sm:border-l sm:border-slate-200 sm:pl-4">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">
                  Equity value
                </div>
                <div className="mt-0.5 text-2xl font-bold text-emerald-800">
                  {fmt(latestEquity ?? null)}
                </div>
                <div className="mt-0.5 text-[10px] text-emerald-700/70">
                  Shareholders receive
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Valuation ladder — per-year + 3-year average column */}
      {(() => {
        const validEbitdas = years.map((y) => y.ebitda).filter((v): v is number => v != null);
        const hasAvg = validEbitdas.length >= 2;
        const avgEbitda = hasAvg ? validEbitdas.reduce((s, v) => s + v, 0) / validEbitdas.length : null;
        const avgEv = avgEbitda != null ? avgEbitda * activeMultiple : null;
        const latestRow = years[years.length - 1];
        const latestNd = latestRow?.net_debt ?? null;
        const latestFd = latestRow?.financial_debt ?? null;
        const latestCe = latestRow?.cash_and_equivalents ?? null;
        const avgEquity = avgEv != null && latestNd != null ? avgEv - latestNd : null;

        const avgHeadCls = "text-right text-xs min-w-[120px] bg-indigo-50/70 border-l border-indigo-200";
        const avgCellCls = "text-right font-mono text-xs py-1.5 bg-indigo-50/40 border-l border-indigo-200";

        return (
          <div>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-emerald-500 pl-2">
              Valuation ladder
            </h3>
            <div className="overflow-x-auto rounded-lg border bg-white">
              <Table>
                <TableHeader>
                  <TableRow className="bg-slate-50">
                    <TableHead className="text-xs min-w-[220px]">Step</TableHead>
                    {years.map((y) => (
                      <TableHead key={y.fiscal_year ?? Math.random()} className="text-right text-xs min-w-[110px]">
                        FY{y.fiscal_year ?? "—"}
                      </TableHead>
                    ))}
                    {hasAvg && (
                      <TableHead className={avgHeadCls} title="3-year average EBITDA, multiplied by the Vlerick multiple, minus the LATEST year's net debt">
                        <span className="text-indigo-700 font-semibold">Avg ({validEbitdas.length}y)</span>
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell className="text-xs py-1.5 text-slate-700 font-medium">
                      EBITDA
                      <div className="text-[10px] text-slate-400 font-normal">Profit before interest, tax &amp; D&amp;A</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5">{fmt(y.ebitda)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " font-semibold text-slate-800"}>{fmt(avgEbitda)}</TableCell>}
                  </TableRow>
                  <TableRow className="bg-indigo-50/30">
                    <TableCell className="text-xs py-1.5 text-indigo-700 font-medium">
                      × Vlerick multiple
                      <div className="text-[10px] text-slate-400 font-normal">Applied: {activeLabel}</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-indigo-700">{fmtMultiple(activeMultiple)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " text-indigo-700 font-semibold"}>{fmtMultiple(activeMultiple)}</TableCell>}
                  </TableRow>
                  <TableRow className="border-t-2 border-slate-200">
                    <TableCell className="text-xs py-1.5 text-slate-800 font-semibold">
                      = Enterprise Value
                      <div className="text-[10px] text-slate-400 font-normal">What a buyer pays for the business</div>
                    </TableCell>
                    {years.map((y, i) => {
                      const ev = view === "size" ? y.by_size.enterprise_value : y.by_sector.enterprise_value;
                      return (
                        <TableCell key={i} className="text-right font-mono text-xs py-1.5 font-semibold text-slate-800">{fmt(ev || null)}</TableCell>
                      );
                    })}
                    {hasAvg && <TableCell className={avgCellCls + " font-semibold text-slate-800"}>{fmt(avgEv)}</TableCell>}
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-xs py-1.5 text-slate-600">
                      − Financial debt
                      <div className="text-[10px] text-slate-400">Long-term + short-term bank debt</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-slate-600">{fmt(y.financial_debt || null)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " text-slate-600 italic"} title="Latest-year figure — avg-EBITDA valuation uses latest balance sheet">{fmt(latestFd)}</TableCell>}
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-xs py-1.5 text-slate-600">
                      + Cash &amp; equivalents
                      <div className="text-[10px] text-slate-400">Cash + short-term investments</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-slate-600">{fmt(y.cash_and_equivalents || null)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " text-slate-600 italic"} title="Latest-year figure">{fmt(latestCe)}</TableCell>}
                  </TableRow>
                  <TableRow className="bg-slate-50/50">
                    <TableCell className="text-xs py-1.5 text-slate-700 font-medium">
                      = Net debt
                      <div className="text-[10px] text-slate-400 font-normal">Debt minus cash</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5 font-medium text-slate-700">{fmt(y.net_debt || null)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " font-medium text-slate-700 italic"} title="Latest-year net debt is used for the avg-EBITDA valuation">{fmt(latestNd)}</TableCell>}
                  </TableRow>
                  <TableRow className="border-t-2 border-slate-300 bg-emerald-50/40">
                    <TableCell className="text-xs py-2 text-emerald-900 font-bold">
                      = Equity Value
                      <div className="text-[10px] text-emerald-700/70 font-normal">What shareholders receive</div>
                    </TableCell>
                    {years.map((y, i) => {
                      const eq = view === "size" ? y.by_size.equity_value : y.by_sector.equity_value;
                      return (
                        <TableCell key={i} className="text-right font-mono text-sm py-2 font-bold text-emerald-800">{fmt(eq)}</TableCell>
                      );
                    })}
                    {hasAvg && <TableCell className="text-right font-mono text-sm py-2 font-bold text-emerald-800 bg-emerald-100/60 border-l border-emerald-300">{fmt(avgEquity)}</TableCell>}
                  </TableRow>
                </TableBody>
              </Table>
            </div>
            {hasAvg && (
              <p className="mt-1.5 text-[10px] italic text-slate-500 px-1">
                Avg column: {validEbitdas.length}-year average EBITDA × multiple, using the latest year&apos;s net debt.
              </p>
            )}
          </div>
        );
      })()}

      {/* Pro memoria — compact italic footnote, sits with the ladder */}
      {pro_memoria_note && (
        <p className="text-[10px] italic leading-relaxed text-slate-500 px-1 -mt-2">
          <span className="font-semibold not-italic text-slate-600">Pro memoria — </span>
          {pro_memoria_note}
        </p>
      )}

      {/* Combined explainer + source block */}
      <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-4 space-y-4">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
            How this valuation works
          </div>
          <p className="text-[12px] leading-relaxed text-slate-700">
            We take the company&apos;s <b>EBITDA</b> (profit before interest, tax, depreciation
            and amortisation) and multiply it by what similar Belgian companies were sold
            for in {vlerick_reference.data_year}, according to the{" "}
            <a
              href={vlerick_reference.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-indigo-600 underline decoration-indigo-300 underline-offset-2 hover:decoration-indigo-500"
            >
              {vlerick_reference.report}
            </a>
            . That gives us the <b>Enterprise Value</b> — what a buyer would pay for the
            whole business. We then subtract what the company owes to banks (minus its cash)
            to get the <b>Equity Value</b> — roughly what the shareholders would walk away
            with in a sale.
          </p>
        </div>

        <div className="border-t border-slate-200 pt-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1.5">
            About the source
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
    </div>
  );
}
