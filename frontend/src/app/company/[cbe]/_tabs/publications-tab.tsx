"use client";

import React, { useState } from "react";
import ExportButtons from "@/components/export-buttons";
import { useTranslation } from "@/components/language-provider";
import { FileText, Download, Loader2, Sparkles, AlertTriangle, RefreshCw } from "lucide-react";
import { getCompanyStructure, summarizePublications } from "@/lib/api";
import type { StructureData, CompanyDetail } from "../types";
import { downloadCsv } from "../helpers";

/* ---------- Publication type mapping ---------- */

const PUB_TYPE_MAP: Record<string, { label: string; color: string; summary: string }> = {
  "ONTSLAGEN - BENOEMINGEN": {
    label: "Board",
    color: "bg-blue-100 text-blue-700",
    summary: "Board changes: resignations and appointments",
  },
  "OPRICHTING": {
    label: "Formation",
    color: "bg-green-100 text-green-700",
    summary: "Company formation / incorporation",
  },
  "STATUTENWIJZIGING": {
    label: "Statutes",
    color: "bg-purple-100 text-purple-700",
    summary: "Amendment of articles of association",
  },
  "ONTBINDING": {
    label: "Dissolution",
    color: "bg-rose-50 text-rose-500",
    summary: "Dissolution",
  },
  "VEREFFENING": {
    label: "Liquidation",
    color: "bg-rose-50 text-rose-500",
    summary: "Liquidation",
  },
  "FUSIE": {
    label: "Merger",
    color: "bg-amber-100 text-amber-700",
    summary: "Merger",
  },
  "SPLITSING": {
    label: "Demerger",
    color: "bg-amber-100 text-amber-700",
    summary: "Demerger / split",
  },
  "ZETELVERPLAATSING": {
    label: "Relocation",
    color: "bg-cyan-100 text-cyan-700",
    summary: "Registered office relocation",
  },
  "KAPITAALVERHOGING": {
    label: "Cap. increase",
    color: "bg-emerald-100 text-emerald-700",
    summary: "Capital increase",
  },
  "KAPITAALVERMINDERING": {
    label: "Cap. decrease",
    color: "bg-orange-100 text-orange-700",
    summary: "Capital decrease",
  },
  "JAARREKENING": {
    label: "Accounts",
    color: "bg-slate-100 text-slate-600",
    summary: "Annual accounts filing",
  },
};

/* ---------- Component ---------- */

interface PublicationsTabProps {
  structure: StructureData | null;
  cbe: string;
  detail: CompanyDetail | null;
  nbbLoading: boolean;
  setNbbLoading: (v: boolean) => void;
  nbbResult: "success" | "error" | "no-data" | "pdf-only" | null;
  setNbbResult: (v: "success" | "error" | "no-data" | "pdf-only" | null) => void;
  setStructure: (s: StructureData) => void;
}

export function PublicationsTab({
  structure,
  cbe,
  detail,
  nbbLoading,
  setNbbLoading,
  nbbResult,
  setNbbResult,
  setStructure,
}: PublicationsTabProps) {
  const { t } = useTranslation();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [pubSummary, setPubSummary] = useState<any>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const autoTriggered = React.useRef(false);

  if (!structure || structure.staatsblad_publications.length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-slate-500 mb-4">{t("company.pubNone")}</p>
        <button
          onClick={async () => {
            setNbbLoading(true);
            try {
              const res = await fetch(`/api/staatsblad/${cbe}/load`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
              });
              const data = await res.json();
              if (data.publications_stored > 0) {
                // Refetch structure to get new publications
                getCompanyStructure(cbe).then((s) =>
                  setStructure(s as unknown as StructureData)
                ).catch(() => {});
              }
              setNbbResult(data.publications_stored > 0 ? "success" : "no-data");
            } catch {
              setNbbResult("error");
            } finally {
              setNbbLoading(false);
            }
          }}
          disabled={nbbLoading}
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-medium text-brand border border-brand/40 rounded-lg hover:bg-brand-soft/60 disabled:opacity-50 transition-colors"
        >
          {nbbLoading ? (
            <><Loader2 className="w-3.5 h-3.5 animate-spin" /> {t("company.pubLoading")}</>
          ) : (
            <><Download className="w-3.5 h-3.5" /> {t("company.pubLoadBtn")}</>
          )}
        </button>
        {nbbResult === "no-data" && (
          <p className="text-xs text-slate-400 mt-2">{t("company.pubNoResults")}</p>
        )}
      </div>
    );
  }

  const generateSummary = async (refresh = false) => {
    setSummaryLoading(true);
    try {
      const data = await summarizePublications(cbe, refresh);
      if (data.summary) setPubSummary(data.summary);
    } catch {
      /* ignore */
    } finally {
      setSummaryLoading(false);
    }
  };

  // Auto-trigger on first render if publications exist
  React.useEffect(() => {
    if (!autoTriggered.current && structure && structure.staatsblad_publications.length >= 2) {
      autoTriggered.current = true;
      generateSummary(false);
    }
  }, [structure, cbe]); // eslint-disable-line react-hooks/exhaustive-deps

  const importanceBadge = (imp: string) => {
    if (imp === "significant") return <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold bg-rose-100 text-rose-700">Significant</span>;
    if (imp === "notable") return <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold bg-amber-100 text-amber-700">Notable</span>;
    return <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold bg-slate-100 text-slate-500">Routine</span>;
  };

  return (
    <div>
      {/* AI Publication Analysis */}
      {pubSummary && pubSummary.events ? (
        <div className="mb-4 space-y-2">
          {/* Pattern alert banner */}
          {pubSummary.pattern_note && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 flex items-start gap-2">
              <Sparkles className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
              <p className="text-xs text-slate-600 leading-relaxed">{pubSummary.pattern_note}</p>
            </div>
          )}
          {pubSummary.risk_flag && pubSummary.pattern_alert && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 flex items-start gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-600 mt-0.5 shrink-0" />
              <p className="text-xs text-amber-800 font-medium">{pubSummary.pattern_alert}</p>
            </div>
          )}
          {!pubSummary.risk_flag && pubSummary.pattern_alert && (
            <div className="rounded-lg border border-brand/20 bg-brand-soft/50 px-3 py-2 flex items-start gap-2">
              <Sparkles className="w-3.5 h-3.5 text-brand mt-0.5 shrink-0" />
              <p className="text-xs text-slate-700">{pubSummary.pattern_alert}</p>
            </div>
          )}
          {/* Events table */}
          <div className="rounded-lg border overflow-hidden bg-white">
            <div className="px-3 py-1.5 bg-slate-50 border-b flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Sparkles className="w-3 h-3 text-brand" />
                <span className="text-[10px] font-semibold uppercase tracking-wider text-brand">{t("company.pubAiAnalysis")}</span>
              </div>
              <button
                onClick={() => generateSummary(true)}
                disabled={summaryLoading}
                className="inline-flex items-center gap-1 text-[10px] text-slate-400 hover:text-brand transition-colors disabled:opacity-50"
                title={t("company.pubRefresh")}
              >
                <RefreshCw className={`w-3 h-3 ${summaryLoading ? "animate-spin" : ""}`} />
                {t("company.pubRefresh")}
              </button>
            </div>
            <div className="divide-y divide-slate-100">
              {pubSummary.events.map((ev: { date: string; what?: string; summary?: string; context?: string; takeaway?: string; importance: string }, i: number) => (
                <div key={i} className="px-4 py-3 flex gap-3">
                  <div className="shrink-0 pt-0.5">
                    <div className="text-[11px] font-mono text-slate-400">{ev.date}</div>
                    <div className="mt-1">{importanceBadge(ev.importance)}</div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs text-slate-700 leading-relaxed">{ev.what || ev.summary || ""}</div>
                    <div className="text-[11px] text-slate-400 mt-1 leading-relaxed">{ev.context || ev.takeaway || ""}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : pubSummary && (pubSummary.parse_error || typeof pubSummary === "string") ? (
        <div className="mb-4 rounded-lg border border-brand/20 bg-brand-soft/50 p-3">
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-brand" />
              <span className="text-[10px] font-semibold uppercase tracking-wider text-brand">{t("company.pubAiAnalysis")}</span>
            </div>
            <button
              onClick={() => generateSummary(true)}
              disabled={summaryLoading}
              className="inline-flex items-center gap-1 text-[10px] text-slate-400 hover:text-brand transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${summaryLoading ? "animate-spin" : ""}`} />
              {t("company.pubRefresh")}
            </button>
          </div>
          <p className="text-xs text-slate-700 leading-relaxed">{typeof pubSummary === "string" ? pubSummary : pubSummary.raw_text}</p>
        </div>
      ) : summaryLoading ? (
        <div className="mb-4 rounded-lg border border-brand/20 bg-brand-soft/30 p-4 flex items-center justify-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin text-brand/60" />
          <span className="text-xs text-slate-500">{t("company.pubAnalyzing")}</span>
        </div>
      ) : null}

      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-slate-400 pl-2">
          {t("company.pubTitle")} ({structure.staatsblad_publications.length})
        </h3>
        <ExportButtons onExportCSV={() => {
          const headers = ["Date", "Type", "Reference", "PDF URL"];
          const rows = structure.staatsblad_publications.map(p => [p.pub_date, p.pub_type || "", p.reference || "", p.pdf_url ? `https://www.ejustice.just.fgov.be${p.pdf_url}` : ""]);
          downloadCsv(`${detail?.name || cbe}_publications.csv`, headers, rows);
        }} onPrint={() => window.print()} />
      </div>
      <div className="rounded-lg border overflow-x-auto bg-white">
        <table className="w-full min-w-[640px]">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-3 py-1.5 text-left text-[11px] md:text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[90px]">Date</th>
              <th className="px-3 py-1.5 text-left text-[11px] md:text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[90px]">Type</th>
              <th className="px-3 py-1.5 text-left text-[11px] md:text-[10px] font-medium text-slate-400 uppercase tracking-wider">Summary</th>
              <th className="px-3 py-1.5 text-left text-[11px] md:text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[100px]">Reference</th>
              <th className="px-3 py-1.5 text-center text-[11px] md:text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[44px]">PDF</th>
            </tr>
          </thead>
          <tbody>
            {structure.staatsblad_publications.slice(0, 50).map((pub, i) => {
              const typeInfo = pub.pub_type
                ? PUB_TYPE_MAP[pub.pub_type.toUpperCase()] ??
                  Object.entries(PUB_TYPE_MAP).find(([key]) =>
                    pub.pub_type!.toUpperCase().includes(key)
                  )?.[1] ??
                  null
                : null;

              return (
                <tr key={`${pub.pub_date}-${i}`} className="border-t border-slate-100 hover:bg-slate-50/50">
                  <td className="px-3 py-1 text-xs font-mono text-slate-600">{pub.pub_date}</td>
                  <td className="px-3 py-1">
                    {typeInfo ? (
                      <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[11px] md:text-[10px] font-semibold ${typeInfo.color}`}>
                        {typeInfo.label}
                      </span>
                    ) : pub.pub_type ? (
                      <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[11px] md:text-[10px] font-semibold bg-slate-100 text-slate-500">
                        {pub.pub_type.length > 15 ? pub.pub_type.slice(0, 15) + "..." : pub.pub_type}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-1 text-xs text-slate-600 truncate max-w-[300px]">
                    {typeInfo
                      ? typeInfo.summary
                      : pub.pub_type ?? "Publication in the Belgian Official Gazette"}
                  </td>
                  <td className="px-3 py-1 text-xs font-mono text-slate-400">
                    {pub.reference ? `#${pub.reference}` : "\u2014"}
                  </td>
                  <td className="px-3 py-1 text-center">
                    {pub.pdf_url ? (
                      <a
                        href={
                          pub.pdf_url.startsWith("http")
                            ? pub.pdf_url
                            : `https://www.ejustice.just.fgov.be${pub.pdf_url}`
                        }
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center justify-center h-10 w-10 md:h-6 md:w-6 rounded hover:bg-brand-soft/60 text-brand hover:text-[color:var(--brand-ink)] transition-colors"
                        title="View PDF"
                      >
                        <FileText className="h-4 w-4 md:h-3.5 md:w-3.5" />
                      </a>
                    ) : (
                      <span className="text-slate-200">{"\u2014"}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {structure.staatsblad_publications.length > 50 && (
        <p className="mt-1 text-[11px] text-slate-400 italic">
          {t("company.pubShowing", { count: String(structure.staatsblad_publications.length) })}
        </p>
      )}
    </div>
  );
}
