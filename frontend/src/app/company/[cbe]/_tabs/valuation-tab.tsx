"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { getCompanyValuation, getValuationAiCommentary, searchCompanies, getCompanyStructure } from "@/lib/api";
import type { ValuationData, MultipleSourceKey, SearchResult } from "@/lib/api";
import { fmtEur, fmtCbe } from "@/lib/format";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { ExternalLink, Loader2, FileSpreadsheet, FileText, Sparkles, Plus, X, Users } from "lucide-react";
import { useTranslation } from "@/components/language-provider";

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
  const { locale } = useTranslation();
  const [data, setData] = useState<ValuationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"size" | "sector">("sector");
  const [sectorOverride, setSectorOverride] = useState<string | null>(null);
  const [unit, setUnit] = useState<Unit>("auto");
  const [sourceKey, setSourceKey] = useState<MultipleSourceKey>("vlerick");
  const [exporting, setExporting] = useState(false);
  const [mobileOptionsOpen, setMobileOptionsOpen] = useState(false);

  /* Group-aggregation state. Empty list = solo company; non-empty = consolidated. */
  const [includeMembers, setIncludeMembers] = useState<{ cbe: string; name: string }[]>([]);
  const [groupSearchOpen, setGroupSearchOpen] = useState(false);
  const [groupSearchQuery, setGroupSearchQuery] = useState("");
  const [groupSearchResults, setGroupSearchResults] = useState<SearchResult[]>([]);
  const [groupSearchLoading, setGroupSearchLoading] = useState(false);
  const groupSearchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  /* Pre-suggested candidates pulled from the company's known
     subsidiaries / participating-interest links. Loaded lazily when the
     picker opens; light touch — purely a hint, user can ignore. */
  const [groupSuggestions, setGroupSuggestions] = useState<{ cbe: string; name: string }[]>([]);
  const groupSuggestionsLoaded = useRef(false);

  /* AI commentary state. */
  const [aiCommentary, setAiCommentary] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const fmt = (v: number | null | undefined) => fmtEurUnit(v, unit);

  const handleExportExcel = async () => {
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
    async (
      override?: string | null,
      src?: MultipleSourceKey,
      members?: { cbe: string; name: string }[],
    ) => {
      setLoading(true);
      setError(null);
      try {
        const memberList = members ?? includeMembers;
        const includeCbes = memberList.map((m) => m.cbe);
        const result = await getCompanyValuation(
          cbe,
          override ?? undefined,
          src ?? sourceKey,
          includeCbes.length > 0 ? includeCbes : undefined,
        );
        setData(result);
        // Group changes invalidate any prior commentary.
        setAiCommentary(null);
        setAiError(null);
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
    [cbe, sourceKey, view, includeMembers]
  );

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cbe]);

  /* ---------- Group: lazy-load suggestion candidates ----------
     Pull subsidiaries (participating_interest) once when the picker
     first opens. Light touch: failure is silent, user can still type. */
  useEffect(() => {
    if (!groupSearchOpen || groupSuggestionsLoaded.current) return;
    groupSuggestionsLoaded.current = true;
    (async () => {
      try {
        const struct = await getCompanyStructure(cbe);
        const seen = new Set<string>();
        const items: { cbe: string; name: string }[] = [];
        for (const pi of struct.participating_interests ?? []) {
          // identifier may be a CBE (10-digit) or a foreign reg number; only keep CBEs
          const candidateCbe = (pi as any).identifier?.replace?.(/\D/g, "");
          if (candidateCbe && candidateCbe.length === 10 && !seen.has(candidateCbe)) {
            seen.add(candidateCbe);
            items.push({ cbe: candidateCbe, name: (pi as any).name || candidateCbe });
          }
          if (items.length >= 6) break;
        }
        setGroupSuggestions(items);
      } catch {
        // Non-critical — picker still works without suggestions
      }
    })();
  }, [groupSearchOpen, cbe]);

  /* ---------- Group: search-and-add company picker ---------- */
  useEffect(() => {
    if (!groupSearchOpen) return;
    if (groupSearchDebounce.current) clearTimeout(groupSearchDebounce.current);
    const q = groupSearchQuery.trim();
    if (q.length < 2) {
      setGroupSearchResults([]);
      return;
    }
    groupSearchDebounce.current = setTimeout(async () => {
      setGroupSearchLoading(true);
      try {
        const r = await searchCompanies(q);
        setGroupSearchResults(r.slice(0, 8));
      } catch {
        setGroupSearchResults([]);
      } finally {
        setGroupSearchLoading(false);
      }
    }, 250);
    return () => {
      if (groupSearchDebounce.current) clearTimeout(groupSearchDebounce.current);
    };
  }, [groupSearchQuery, groupSearchOpen]);

  const addGroupMember = useCallback(
    (member: { cbe: string; name: string }) => {
      if (member.cbe === cbe) return; // can't add primary to itself
      setIncludeMembers((prev) => {
        if (prev.some((m) => m.cbe === member.cbe)) return prev;
        if (prev.length >= 9) return prev; // backend caps at 9
        const next = [...prev, member];
        load(sectorOverride, sourceKey, next);
        return next;
      });
      setGroupSearchQuery("");
      setGroupSearchResults([]);
      setGroupSearchOpen(false);
    },
    [cbe, load, sectorOverride, sourceKey]
  );

  const removeGroupMember = useCallback(
    (memberCbe: string) => {
      setIncludeMembers((prev) => {
        const next = prev.filter((m) => m.cbe !== memberCbe);
        load(sectorOverride, sourceKey, next);
        return next;
      });
    },
    [load, sectorOverride, sourceKey]
  );

  /* ---------- AI commentary ---------- */
  const fetchAiCommentary = useCallback(async () => {
    setAiLoading(true);
    setAiError(null);
    try {
      const res = await getValuationAiCommentary(
        cbe,
        sectorOverride ?? undefined,
        sourceKey,
        includeMembers.length > 0 ? includeMembers.map((m) => m.cbe) : undefined,
      );
      setAiCommentary(res.commentary || null);
      if (!res.commentary) {
        setAiError(res.reason === "no_data" ? "No financial data to comment on." : "AI returned no commentary.");
      }
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "AI request failed");
    } finally {
      setAiLoading(false);
    }
  }, [cbe, sectorOverride, sourceKey, includeMembers]);

  /* Auto re-fetch the AI commentary when the user switches site
     language — otherwise the commentary stays in the language it was
     first rendered in even though the surrounding chrome has flipped.
     Only refires if the commentary is already on screen so we don't
     surprise users with a fresh LLM call they didn't ask for. */
  useEffect(() => {
    if (aiCommentary) {
      fetchAiCommentary();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

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
      {/* Compact header strip — title + source on 2 rows left; right-side
          controls on ONE row aligned to the source line (bottom of left col).
          On mobile the controls row collapses behind an "Options" toggle so
          the header doesn't blow up into 5-6 rows of tiny buttons. */}
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 pb-3 border-b border-slate-200">
        <div className="flex items-end justify-between gap-2 w-full md:w-auto md:min-w-0">
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-2">
              Indicative valuation
              {includeMembers.length > 0 && (
                /* Visible cue that the headline numbers reflect the
                   consolidated group, not the primary alone. The Group
                   panel itself sits below the table now (per operator
                   preference), so this chip is the only above-the-fold
                   indication that the group toggle is active. */
                <a
                  href="#valuation-group"
                  className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-700 hover:bg-indigo-100 normal-case tracking-normal"
                  title="Headline reflects this primary plus the listed group companies"
                >
                  <Users className="h-3 w-3" />
                  Consolidated &middot; {includeMembers.length + 1} cos.
                </a>
              )}
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
          {/* Mobile-only options toggle. Keeps the control row hidden until
              the user actually wants to tweak source/view/unit/export. */}
          <button
            onClick={() => setMobileOptionsOpen((v) => !v)}
            aria-expanded={mobileOptionsOpen}
            className="md:hidden shrink-0 inline-flex items-center gap-1 h-9 px-3 text-[11px] font-medium text-slate-600 border border-slate-200 rounded-md bg-white hover:border-slate-300"
          >
            {mobileOptionsOpen ? "Hide options" : "Options"}
          </button>
        </div>

        <div className={`${mobileOptionsOpen ? "flex" : "hidden"} md:flex flex-wrap items-center gap-3 no-print w-full md:w-auto`}>
          {/* Source toggle — pick which reference dataset's multiples to use */}
          {sources.length > 1 && (
            <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5" title="Multiple source">
              {sources.map((s) => (
                <button
                  key={s.key}
                  onClick={() => handleSourceChange(s.key)}
                  className={`rounded-md px-2.5 py-2 md:py-1 text-[11px] font-medium transition ${
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

          {/* View toggle: By sector / By size. */}
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
            <button
              onClick={() => srcHasSector && setView("sector")}
              disabled={!srcHasSector}
              className={`rounded-md px-3 py-2 md:py-1.5 text-xs font-medium transition ${
                view === "sector"
                  ? "bg-indigo-600 text-white"
                  : srcHasSector
                  ? "text-slate-500 hover:text-slate-700"
                  : "text-slate-300 cursor-not-allowed"
              }`}
              title={srcHasSector ? "" : "This source has no sector breakdown"}
            >
              By sector
            </button>
            <button
              onClick={() => srcHasSize && setView("size")}
              disabled={!srcHasSize}
              className={`rounded-md px-3 py-2 md:py-1.5 text-xs font-medium transition ${
                view === "size"
                  ? "bg-indigo-600 text-white"
                  : srcHasSize
                  ? "text-slate-500 hover:text-slate-700"
                  : "text-slate-300 cursor-not-allowed"
              }`}
              title={srcHasSize ? "" : "This source has no size breakdown"}
            >
              By size
            </button>
          </div>

          {/* Sector picker — between the view toggle and unit toggle.
              Always rendered so its space is reserved; made invisible in
              size view so nothing horizontally jumps when switching modes. */}
          <select
            value={sectorOverride ?? profile.vlerick_sector}
            onChange={(e) => handleSectorChange(e.target.value)}
            className={`rounded-md border border-slate-200 bg-white px-2 py-2 md:py-1 text-xs text-slate-700 focus:border-indigo-400 focus:outline-none ${view === "sector" ? "" : "invisible"}`}
            title={sourceTag}
            aria-hidden={view !== "sector"}
          >
            {profile.available_sectors.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
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
                className={`rounded-md px-2 py-2 md:py-1 text-[11px] font-medium transition ${
                  unit === opt.key
                    ? "bg-slate-800 text-white"
                    : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* AI commentary trigger */}
          <button
            onClick={fetchAiCommentary}
            disabled={aiLoading || loading}
            className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-2 md:py-1 text-[11px] font-medium text-indigo-700 hover:border-indigo-400 hover:bg-indigo-100 disabled:opacity-50 transition"
            title="Get an AI commentary on this valuation"
          >
            {aiLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
            AI commentary
          </button>

          {/* Export buttons */}
          <div className="inline-flex items-center gap-1 no-print">
            <button
              onClick={handleExportExcel}
              disabled={exporting}
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-2 md:py-1 text-[11px] font-medium text-slate-600 hover:border-emerald-300 hover:text-emerald-700 disabled:opacity-50 transition"
              title="Export to Excel"
            >
              {exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileSpreadsheet className="h-3 w-3 text-emerald-600" />}
              Excel
            </button>
            <button
              onClick={handleExportPdf}
              disabled={exporting}
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-2 md:py-1 text-[11px] font-medium text-slate-600 hover:border-rose-300 hover:text-rose-600 disabled:opacity-50 transition"
              title="Export to PDF"
            >
              {exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileText className="h-3 w-3 text-rose-500" />}
              PDF
            </button>
          </div>
        </div>
      </div>

      {/* AI commentary card */}
      {(aiCommentary || aiError) && (
        <div className="rounded-lg border border-indigo-100 bg-indigo-50/40 p-3 no-print">
          <div className="flex items-center gap-1.5 mb-1">
            <Sparkles className="h-3.5 w-3.5 text-indigo-600" />
            <span className="text-[11px] font-semibold uppercase tracking-wider text-indigo-700">
              AI commentary
            </span>
          </div>
          {aiCommentary ? (
            <p className="text-[12px] leading-relaxed text-slate-700 whitespace-pre-wrap">{aiCommentary}</p>
          ) : (
            <p className="text-[12px] text-amber-700">{aiError}</p>
          )}
        </div>
      )}

      {/* Headline snapshot — horizontal 4-column summary for the latest year.
          When the latest reported EBITDA is negative (loss-making year)
          the EV / Equity columns show "—" with a subtle "loss-making"
          subtitle, because EBITDA × multiple is meaningless on a loss. */}
      {(() => {
        const latest = years[years.length - 1];
        const latestEbitda = latest?.ebitda ?? null;
        const ebitdaIsPositive = latestEbitda != null && latestEbitda > 0;
        const latestEv = ebitdaIsPositive
          ? (view === "size" ? latest?.by_size.enterprise_value : latest?.by_sector.enterprise_value)
          : null;
        const latestEquity = ebitdaIsPositive
          ? (view === "size" ? latest?.by_size.equity_value : latest?.by_sector.equity_value)
          : null;
        const fyLabel = latest?.fiscal_year ? `FY${latest.fiscal_year}` : "latest";
        const lossSubtitle = latestEbitda != null && latestEbitda <= 0
          ? "Loss-making year — EV/Equity not meaningful"
          : null;
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
                <div className={`mt-0.5 text-2xl font-bold ${latestEbitda != null && latestEbitda < 0 ? "text-rose-700" : "text-slate-800"}`}>
                  {fmt(latestEbitda)}
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
                  {lossSubtitle ?? "What a buyer pays"}
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
                  {lossSubtitle ?? "Shareholders receive"}
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Valuation ladder — per-year + N-year average column.
          Negative-EBITDA years are EXCLUDED from the average (multiplying
          a loss by a positive multiple yields a meaningless negative EV).
          The header reads "Avg (Xy)" where X = number of POSITIVE years
          actually included. The backend already returns EV=0 for negative
          years, so per-year EV cells render as "—" via fmt(0 || null). */}
      {(() => {
        const positiveEbitdas = years.map((y) => y.ebitda).filter((v): v is number => v != null && v > 0);
        const totalReportedYears = years.filter((y) => y.ebitda != null).length;
        const hasAvg = positiveEbitdas.length >= 2;
        const avgEbitda = hasAvg ? positiveEbitdas.reduce((s, v) => s + v, 0) / positiveEbitdas.length : null;
        const avgEv = avgEbitda != null ? avgEbitda * activeMultiple : null;
        const latestRow = years[years.length - 1];
        const latestNd = latestRow?.net_debt ?? null;
        const latestFd = latestRow?.financial_debt ?? null;
        const latestCe = latestRow?.cash_and_equivalents ?? null;
        const avgEquity = avgEv != null && latestNd != null ? avgEv - latestNd : null;
        const avgYearsLabel = positiveEbitdas.length;
        const someNegativeExcluded = positiveEbitdas.length < totalReportedYears;

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
                    <TableHead className="text-[11px] md:text-xs w-[130px] md:w-auto md:min-w-[200px] sticky left-0 z-10 bg-slate-50 shadow-[1px_0_0_rgba(226,232,240,1)]">Step</TableHead>
                    {years.map((y) => (
                      <TableHead key={y.fiscal_year ?? Math.random()} className="text-right text-[11px] md:text-xs min-w-[90px] md:min-w-[110px]">
                        FY{y.fiscal_year ?? "—"}
                      </TableHead>
                    ))}
                    {hasAvg && (
                      <TableHead
                        className={avgHeadCls}
                        title={`Average across ${avgYearsLabel} positive-EBITDA year${avgYearsLabel === 1 ? "" : "s"}, multiplied by the Vlerick M&A Monitor multiple, minus the LATEST year's net debt${someNegativeExcluded ? " — loss-making years excluded" : ""}`}
                      >
                        <span className="text-indigo-700 font-semibold">Avg ({avgYearsLabel}y)</span>
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell className="text-xs py-1.5 text-slate-700 font-medium sticky left-0 z-[5] bg-white whitespace-normal break-words w-[130px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)]">
                      EBITDA
                      <div className="text-[11px] text-slate-500 font-normal">Profit before interest, tax &amp; D&amp;A</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-[11px] md:text-xs py-1.5">{fmt(y.ebitda)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " font-semibold text-slate-800"}>{fmt(avgEbitda)}</TableCell>}
                  </TableRow>
                  <TableRow className="bg-indigo-50/30">
                    <TableCell className="text-xs py-1.5 text-indigo-700 font-medium sticky left-0 z-[5] bg-indigo-50/30 whitespace-normal break-words w-[130px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)]">
                      × Vlerick M&amp;A Monitor multiple
                      <div className="text-[11px] text-slate-500 font-normal">Applied: {activeLabel}</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-indigo-700">{fmtMultiple(activeMultiple)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " text-indigo-700 font-semibold"}>{fmtMultiple(activeMultiple)}</TableCell>}
                  </TableRow>
                  <TableRow className="border-t-2 border-slate-200">
                    <TableCell className="text-xs py-1.5 text-slate-800 font-semibold sticky left-0 z-[5] bg-white whitespace-normal break-words w-[130px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)]">
                      = Enterprise Value
                      <div className="text-[11px] text-slate-500 font-normal">What a buyer pays for the business</div>
                    </TableCell>
                    {years.map((y, i) => {
                      const ev = view === "size" ? y.by_size.enterprise_value : y.by_sector.enterprise_value;
                      return (
                        <TableCell key={i} className="text-right font-mono text-[11px] md:text-xs py-1.5 font-semibold text-slate-800">{fmt(ev || null)}</TableCell>
                      );
                    })}
                    {hasAvg && <TableCell className={avgCellCls + " font-semibold text-slate-800"}>{fmt(avgEv)}</TableCell>}
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-xs py-1.5 text-slate-600 sticky left-0 z-[5] bg-white whitespace-normal break-words w-[130px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)]">
                      − Financial debt
                      <div className="text-[11px] text-slate-500">Long-term + short-term bank debt</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-slate-600">{fmt(y.financial_debt || null)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " text-slate-600 italic"} title="Latest-year figure — avg-EBITDA valuation uses latest balance sheet">{fmt(latestFd)}</TableCell>}
                  </TableRow>
                  <TableRow>
                    <TableCell className="text-xs py-1.5 text-slate-600 sticky left-0 z-[5] bg-white whitespace-normal break-words w-[130px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)]">
                      + Cash &amp; equivalents
                      <div className="text-[11px] text-slate-500">Cash + short-term investments</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5 text-slate-600">{fmt(y.cash_and_equivalents || null)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " text-slate-600 italic"} title="Latest-year figure">{fmt(latestCe)}</TableCell>}
                  </TableRow>
                  <TableRow className="bg-slate-50/50">
                    <TableCell className="text-xs py-1.5 text-slate-700 font-medium sticky left-0 z-[5] bg-slate-50/50 whitespace-normal break-words w-[130px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)]">
                      = Net debt
                      <div className="text-[11px] text-slate-500 font-normal">Debt minus cash</div>
                    </TableCell>
                    {years.map((y, i) => (
                      <TableCell key={i} className="text-right font-mono text-xs py-1.5 font-medium text-slate-700">{fmt(y.net_debt || null)}</TableCell>
                    ))}
                    {hasAvg && <TableCell className={avgCellCls + " font-medium text-slate-700 italic"} title="Latest-year net debt is used for the avg-EBITDA valuation">{fmt(latestNd)}</TableCell>}
                  </TableRow>
                  <TableRow className="border-t-2 border-slate-300 bg-emerald-50/40">
                    <TableCell className="text-xs py-2 text-emerald-900 font-bold sticky left-0 z-[5] bg-emerald-50/40 whitespace-normal break-words w-[130px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)]">
                      = Equity Value
                      <div className="text-[11px] text-emerald-700/80 font-normal">What shareholders receive</div>
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
                Avg column: {avgYearsLabel}-year average EBITDA &times; multiple, using the latest year&apos;s net debt.
                {someNegativeExcluded && " Loss-making years are excluded — multiplying a loss by a positive multiple is not meaningful."}
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

      {/* Group consolidation — sits BELOW pro memoria per operator preference,
          so the headline valuation reads cleanly first and the "add other group
          companies" affordance appears once the user is ready to drill in. */}
      <div id="valuation-group" className="rounded-lg border border-slate-200 bg-white p-3 no-print">
        <div className="flex flex-wrap items-center gap-2">
          <Users className="h-3.5 w-3.5 text-slate-500" />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Group valuation
          </span>
          <span className="text-[11px] text-slate-400">
            Add companies in the same group to consolidate EBITDA / net debt.
          </span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-medium text-indigo-700">
            {companyName || fmtCbe(cbe)}
            <span className="text-indigo-400">(primary)</span>
          </span>
          {includeMembers.map((m) => (
            <span
              key={m.cbe}
              className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700"
            >
              {m.name}
              <button
                onClick={() => removeGroupMember(m.cbe)}
                className="ml-1 inline-flex items-center justify-center text-slate-400 hover:text-rose-500"
                aria-label={`Remove ${m.name}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <button
            onClick={() => setGroupSearchOpen((v) => !v)}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-slate-300 px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:border-indigo-400 hover:text-indigo-700"
            disabled={includeMembers.length >= 9}
          >
            <Plus className="h-3 w-3" />
            Add company
          </button>
        </div>
        {groupSearchOpen && (
          <div className="mt-2 max-w-md">
            <Input
              autoFocus
              placeholder="Search by name or CBE..."
              value={groupSearchQuery}
              onChange={(e) => setGroupSearchQuery(e.target.value)}
              className="h-9 text-sm"
            />
            {/* Pre-suggestions from KBO group links — only when the user
                hasn't started typing, so it's a light hint, not a default. */}
            {!groupSearchQuery.trim() && groupSuggestions.length > 0 && (
              <div className="mt-1 rounded-md border border-slate-200 bg-white">
                <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400 bg-slate-50/60 border-b border-slate-100">
                  Suggested (from group links)
                </div>
                <ul className="max-h-48 overflow-y-auto">
                  {groupSuggestions
                    .filter((s) => !includeMembers.some((m) => m.cbe === s.cbe))
                    .map((s) => (
                      <li key={s.cbe}>
                        <button
                          onClick={() => addGroupMember(s)}
                          className="block w-full px-3 py-2 text-left text-[12px] hover:bg-indigo-50"
                        >
                          <div className="font-medium text-slate-800">{s.name}</div>
                          <div className="text-[10px] text-slate-400">{fmtCbe(s.cbe)}</div>
                        </button>
                      </li>
                    ))}
                </ul>
              </div>
            )}
            {groupSearchLoading && (
              <div className="mt-1 text-[11px] text-slate-400">Searching...</div>
            )}
            {!groupSearchLoading && groupSearchResults.length > 0 && (
              <ul className="mt-1 max-h-48 overflow-y-auto rounded-md border border-slate-200 bg-white">
                {groupSearchResults
                  .filter((r) => r.enterprise_number !== cbe)
                  .map((r) => (
                  <li key={r.enterprise_number}>
                    <button
                      onClick={() => addGroupMember({ cbe: r.enterprise_number, name: r.name || r.enterprise_number })}
                      className="block w-full px-3 py-2 text-left text-[12px] hover:bg-indigo-50"
                    >
                      <div className="font-medium text-slate-800">{r.name || r.enterprise_number}</div>
                      <div className="text-[10px] text-slate-400">{fmtCbe(r.enterprise_number)}</div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {data?.group?.partial_years && data.group.partial_years.length > 0 && (
          <div className="mt-2 text-[11px] text-amber-700">
            Note: years {data.group.partial_years.join(", ")} have partial coverage{" \u2014 "}not all selected companies filed.
          </div>
        )}
      </div>

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
