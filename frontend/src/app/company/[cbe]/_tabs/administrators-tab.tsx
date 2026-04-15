"use client";

import React from "react";
import Link from "next/link";
import ExportButtons from "@/components/export-buttons";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { fmtCbe } from "@/lib/format";
import {
  Star,
  Sparkles,
  Loader2,
  ChevronDown,
} from "lucide-react";
import { GoogleSearchLink } from "@/components/google-search-link";
import type { CompanyDetail, StructureData } from "../types";
import { cleanCbe, downloadCsv } from "../helpers";

/* ---------- props ---------- */

export interface AdministratorsTabProps {
  detail: CompanyDetail;
  structure: StructureData | null;
  cbe: string;
  // Person enrichment
  personEnrichments: Record<string, { summary: string; loading: boolean }>;
  onEnrichPerson: (name: string) => void;
  onAddPeopleFavourite: (name: string) => void;
}

/* ---------- component ---------- */

export function AdministratorsTab({
  detail,
  structure,
  cbe,
  personEnrichments,
  onEnrichPerson,
  onAddPeopleFavourite,
}: AdministratorsTabProps) {
  const currentAdmins = (structure?.administrators || []).filter(
    (a) => !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > new Date()
  );
  const pastAdmins = (structure?.administrators || []).filter(
    (a) => a.mandate_end && a.mandate_end !== "" && new Date(a.mandate_end) <= new Date()
  );

  if (currentAdmins.length === 0 && pastAdmins.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        No administrator data available for this company.
      </p>
    );
  }

  function exportAdminsCsv() {
    const all = [...currentAdmins, ...pastAdmins];
    const headers = ["Name", "Role", "Status", "Start", "End", "Identifier"];
    const now = new Date();
    const rows = all.map(a => {
      const active = !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > now;
      return [a.name, a.role_label || a.role, active ? "Active" : "Ended", a.mandate_start || "", a.mandate_end || "", a.identifier || ""];
    });
    downloadCsv(`${detail?.name || cbe}_administrators.csv`, headers, rows);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <ExportButtons onExportCSV={exportAdminsCsv} onPrint={() => window.print()} />
      </div>
      {/* Current Administrators */}
      {currentAdmins.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
            Current Administrators ({currentAdmins.length})
          </h3>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {currentAdmins.map((admin, i) => {
              const adminCbe = cleanCbe(admin.identifier);
              const pe = personEnrichments[admin.name];
              return (
                <Card key={`current-${admin.name}-${admin.role}-${i}`}>
                  <CardContent className="p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-green-500" />
                          {adminCbe ? (
                            <GoogleSearchLink query={admin.name}>
                              <Link
                                href={`/company/${adminCbe}`}
                                className="font-bold text-sm text-indigo-600 hover:underline truncate"
                              >
                                {admin.name}
                              </Link>
                            </GoogleSearchLink>
                          ) : (
                            <GoogleSearchLink query={admin.name}>
                              <Link
                                href={`/people?q=${encodeURIComponent(admin.name)}`}
                                className="font-bold text-sm text-indigo-600 hover:underline truncate"
                              >
                                {admin.name}
                              </Link>
                            </GoogleSearchLink>
                          )}
                        </div>
                        <p className="mt-1 text-sm font-medium text-slate-700">
                          {admin.role_label}
                        </p>
                        {admin.mandate_start && (
                          <p className="mt-1 text-xs text-slate-500">
                            Since {admin.mandate_start}
                          </p>
                        )}
                        {adminCbe && (
                          <p className="mt-1 text-xs text-slate-400 font-mono">
                            {fmtCbe(adminCbe)}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (pe?.summary || pe?.loading) return;
                            onEnrichPerson(admin.name);
                          }}
                          title="Enrich with AI"
                          className={`h-6 w-6 flex items-center justify-center rounded transition-colors ${
                            pe?.summary
                              ? "text-indigo-500"
                              : "text-slate-300 hover:text-indigo-500"
                          }`}
                        >
                          {pe?.loading ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Sparkles className="h-3.5 w-3.5" />
                          )}
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onAddPeopleFavourite(admin.name);
                            const btn = e.currentTarget;
                            btn.classList.add("text-yellow-500");
                            btn.title = "Saved!";
                          }}
                          title="Save person to favourites"
                          className="h-6 w-6 flex items-center justify-center rounded text-slate-300 hover:text-yellow-500 transition-colors"
                        >
                          <Star className="h-3.5 w-3.5" />
                        </button>
                        <Badge
                          variant="secondary"
                          className="text-[10px] bg-green-50 text-green-700 border-green-200"
                        >
                          Active
                        </Badge>
                      </div>
                    </div>
                    {pe?.summary && (
                      <div className="mt-2 pt-2 border-t border-indigo-100">
                        <div className="flex items-start gap-1.5">
                          <Sparkles className="h-3 w-3 text-indigo-400 mt-0.5 shrink-0" />
                          <p className="text-xs text-slate-600 leading-relaxed">{pe.summary}</p>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {/* Past Administrators */}
      {pastAdmins.length > 0 && (
        <div>
          <button
            type="button"
            className="mb-3 flex items-center gap-1 text-xs font-bold uppercase tracking-wider text-slate-400 border-l-[3px] border-slate-300 pl-2 hover:text-slate-600 transition-colors"
            onClick={(e) => {
              const content = (e.currentTarget as HTMLElement).nextElementSibling;
              const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
              if (content) {
                content.classList.toggle("hidden");
              }
              if (chevron) {
                chevron.classList.toggle("rotate-180");
              }
            }}
          >
            Past Administrators ({pastAdmins.length})
            <ChevronDown data-chevron className="h-3.5 w-3.5 transition-transform" />
          </button>
          <div className="hidden">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {pastAdmins.map((admin, i) => {
                const adminCbe = cleanCbe(admin.identifier);
                const pe = personEnrichments[admin.name];
                return (
                  <Card key={`past-${admin.name}-${admin.role}-${i}`} className="opacity-75">
                    <CardContent className="p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-slate-300" />
                            {adminCbe ? (
                              <Link
                                href={`/company/${adminCbe}`}
                                className="font-bold text-sm text-slate-500 hover:underline truncate"
                              >
                                {admin.name}
                              </Link>
                            ) : (
                              <Link
                                href={`/people?q=${encodeURIComponent(admin.name)}`}
                                className="font-bold text-sm text-slate-500 hover:underline truncate"
                              >
                                {admin.name}
                              </Link>
                            )}
                          </div>
                          <p className="mt-1 text-sm text-slate-500">
                            {admin.role_label}
                          </p>
                          <p className="mt-1 text-xs text-slate-400">
                            {admin.mandate_start ?? "?"} - {admin.mandate_end}
                          </p>
                          {adminCbe && (
                            <p className="mt-1 text-xs text-slate-400 font-mono">
                              {fmtCbe(adminCbe)}
                            </p>
                          )}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              if (pe?.summary || pe?.loading) return;
                              onEnrichPerson(admin.name);
                            }}
                            title="Enrich with AI"
                            className={`h-6 w-6 flex items-center justify-center rounded transition-colors ${
                              pe?.summary
                                ? "text-indigo-500"
                                : "text-slate-300 hover:text-indigo-500"
                            }`}
                          >
                            {pe?.loading ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Sparkles className="h-3.5 w-3.5" />
                            )}
                          </button>
                          <Badge
                            variant="secondary"
                            className="text-[10px] shrink-0 bg-slate-50 text-slate-400 border-slate-200"
                          >
                            Ended
                          </Badge>
                        </div>
                      </div>
                      {pe?.summary && (
                        <div className="mt-2 pt-2 border-t border-indigo-100">
                          <div className="flex items-start gap-1.5">
                            <Sparkles className="h-3 w-3 text-indigo-400 mt-0.5 shrink-0" />
                            <p className="text-xs text-slate-600 leading-relaxed">{pe.summary}</p>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
