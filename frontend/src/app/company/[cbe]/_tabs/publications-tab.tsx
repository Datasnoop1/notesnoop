"use client";

import React, { useState } from "react";
import ExportButtons from "@/components/export-buttons";
import { FileText, Download, Loader2, Sparkles, AlertTriangle } from "lucide-react";
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
  nbbResult: "success" | "error" | "no-data" | null;
  setNbbResult: (v: "success" | "error" | "no-data" | null) => void;
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
  if (!structure || structure.staatsblad_publications.length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-slate-500 mb-4">No Staatsblad publications available.</p>
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
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-medium text-indigo-600 border border-indigo-300 rounded-lg hover:bg-indigo-50 disabled:opacity-50 transition-colors"
        >
          {nbbLoading ? (
            <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading publications...</>
          ) : (
            <><Download className="w-3.5 h-3.5" /> Load from Staatsblad</>
          )}
        </button>
        {nbbResult === "no-data" && (
          <p className="text-xs text-slate-400 mt-2">No publications found for this company.</p>
        )}
      </div>
    );
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [pubSummary, setPubSummary] = useState<any>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const generateSummary = async () => {
    setSummaryLoading(true);
    try {
      const data = await summarizePublications(cbe);
      if (data.summary) setPubSummary(data.summary);
    } catch {
      /* ignore */
    } finally {
      setSummaryLoading(false);
    }
  };

  const importanceBadge = (imp: string) => {
    if (imp === "significant") return <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold bg-rose-100 text-rose-700">Significant</span>;
    if (imp === "notable") return <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold bg-amber-100 text-amber-700">Notable</span>;
    return <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold bg-slate-100 text-slate-500">Routine</span>;
  };

  return (
    <div>
      {/* AI Publication Summary */}
      {pubSummary && pubSummary.events ? (
        <div className="mb-4 space-y-2">
          {/* Pattern alert banner */}
          {pubSummary.risk_flag && pubSummary.pattern_alert && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 flex items-start gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-600 mt-0.5 shrink-0" />
              <p className="text-xs text-amber-800 font-medium">{pubSummary.pattern_alert}</p>
            </div>
          )}
          {!pubSummary.risk_flag && pubSummary.pattern_alert && (
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-3 py-2 flex items-start gap-2">
              <Sparkles className="w-3.5 h-3.5 text-indigo-500 mt-0.5 shrink-0" />
              <p className="text-xs text-slate-700">{pubSummary.pattern_alert}</p>
            </div>
          )}
          {/* Events table */}
          <div className="rounded-lg border overflow-hidden bg-white">
            <div className="px-3 py-1.5 bg-slate-50 border-b flex items-center gap-1.5">
              <Sparkles className="w-3 h-3 text-indigo-500" />
              <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500">AI Analysis</span>
            </div>
            <table className="w-full">
              <tbody>
                {pubSummary.events.map((ev: { date: string; summary: string; takeaway: string; importance: string }, i: number) => (
                  <tr key={i} className="border-t border-slate-50 first:border-t-0">
                    <td className="px-3 py-2 text-xs font-mono text-slate-500 w-[80px] align-top">{ev.date}</td>
                    <td className="px-2 py-2 w-[80px] align-top">{importanceBadge(ev.importance)}</td>
                    <td className="px-3 py-2 align-top">
                      <div className="text-xs text-slate-700">{ev.summary}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5">{ev.takeaway}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : pubSummary && pubSummary.parse_error ? (
        <div className="mb-4 rounded-lg border border-indigo-100 bg-indigo-50/50 p-3">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500">AI Summary</span>
          </div>
          <p className="text-xs text-slate-700 leading-relaxed">{pubSummary.raw_text}</p>
        </div>
      ) : pubSummary && typeof pubSummary === "string" ? (
        <div className="mb-4 rounded-lg border border-indigo-100 bg-indigo-50/50 p-3">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500">AI Summary</span>
          </div>
          <p className="text-xs text-slate-700 leading-relaxed">{pubSummary}</p>
        </div>
      ) : structure.staatsblad_publications.length >= 2 && (
        <div className="mb-4 flex justify-end">
          <button
            onClick={generateSummary}
            disabled={summaryLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50 disabled:opacity-50 transition-colors"
          >
            {summaryLoading ? (
              <><Loader2 className="w-3 h-3 animate-spin" /> Analyzing...</>
            ) : (
              <><Sparkles className="w-3 h-3" /> Analyze publications</>
            )}
          </button>
        </div>
      )}

      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-slate-400 pl-2">
          Staatsblad Publications ({structure.staatsblad_publications.length})
        </h3>
        <ExportButtons onExportCSV={() => {
          const headers = ["Date", "Type", "Reference", "PDF URL"];
          const rows = structure.staatsblad_publications.map(p => [p.pub_date, p.pub_type || "", p.reference || "", p.pdf_url ? `https://www.ejustice.just.fgov.be${p.pdf_url}` : ""]);
          downloadCsv(`${detail?.name || cbe}_publications.csv`, headers, rows);
        }} onPrint={() => window.print()} />
      </div>
      <div className="rounded-lg border overflow-x-auto scrollbar-none bg-white">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-3 py-1.5 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[90px]">Date</th>
              <th className="px-3 py-1.5 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[90px]">Type</th>
              <th className="px-3 py-1.5 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider">Summary</th>
              <th className="px-3 py-1.5 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[100px]">Reference</th>
              <th className="px-3 py-1.5 text-center text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[40px]">PDF</th>
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
                      <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${typeInfo.color}`}>
                        {typeInfo.label}
                      </span>
                    ) : pub.pub_type ? (
                      <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold bg-slate-100 text-slate-500">
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
                        className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-indigo-50 text-indigo-500 hover:text-indigo-700 transition-colors"
                        title="View PDF"
                      >
                        <FileText className="h-3.5 w-3.5" />
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
        <p className="mt-1 text-[10px] text-slate-400 italic">
          Showing 50 of {structure.staatsblad_publications.length} publications.
        </p>
      )}
    </div>
  );
}
