"use client";

import React from "react";
import Link from "next/link";
import ExportButtons from "@/components/export-buttons";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import {
  ChevronDown,
} from "lucide-react";
import type { CompanyDetail, StructureData } from "../types";
import { cleanCbe, downloadCsv } from "../helpers";

/* ---------- props ---------- */

export interface StructureTabProps {
  detail: CompanyDetail;
  structure: StructureData | null;
  cbe: string;
  collapsedSections: Record<string, boolean>;
  toggleSection: (key: string) => void;
}

/* ---------- component ---------- */

export function StructureTab({
  detail,
  structure,
  cbe,
}: StructureTabProps) {
  const parentCompanies = structure?.parent_companies ?? [];

  if (
    !structure ||
    (structure.shareholders.length === 0 &&
      structure.participating_interests.length === 0 &&
      parentCompanies.length === 0)
  ) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        No structure data available for this company.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end">
        <ExportButtons onExportCSV={() => {
          const headers = ["Type", "Name", "Ownership %", "Country/Type", "Identifier", "Fiscal Year"];
          const rows = [
            ...parentCompanies.map(p => ["Parent", p.name, p.ownership_pct != null ? p.ownership_pct.toFixed(1) : "", p.country || "", p.enterprise_number, p.fiscal_year || ""]),
            ...structure.shareholders.map(s => ["Shareholder", s.name, s.ownership_pct != null ? s.ownership_pct.toFixed(1) : "", s.shareholder_type || "", s.identifier || "", s.fiscal_year || ""]),
            ...structure.participating_interests.map(p => ["Subsidiary", p.name, p.ownership_pct != null ? p.ownership_pct.toFixed(1) : "", p.country || "", p.identifier || "", p.fiscal_year || ""]),
          ];
          downloadCsv(`${detail?.name || cbe}_structure.csv`, headers, rows);
        }} onPrint={() => window.print()} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
      {/* Left column: collapsible cards */}
      <div className="space-y-3">
          {/* Parent companies (reverse PI lookup) — surfaces parents that
              declare this CBE in their own filings, even when this entity
              has no shareholder schedule of its own. */}
          {parentCompanies.length > 0 && (
            <Card>
              <CardContent>
                <button
                  type="button"
                  onClick={(e) => {
                    const content = (e.currentTarget as HTMLElement).nextElementSibling;
                    const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                    if (content) content.classList.toggle("hidden");
                    if (chevron) chevron.classList.toggle("rotate-180");
                  }}
                  className="w-full flex items-center justify-between mb-2 py-2 md:py-0 min-h-[44px] md:min-h-0"
                >
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-blue-500 pl-2">
                    Parent companies ({parentCompanies.length})
                  </h3>
                  <ChevronDown data-chevron className="h-4 w-4 text-slate-400 transition-transform" />
                </button>
                <div className="space-y-1.5">
                  <p className="text-[11px] text-slate-400 italic mb-1">
                    Disclosed by the parent's own filing.
                  </p>
                  {parentCompanies.map((p, i) => {
                    const pCbe = cleanCbe(p.enterprise_number);
                    return (
                      <div
                        key={`${p.enterprise_number}-${i}`}
                        className="rounded-md border px-3 py-3 md:py-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          {pCbe ? (
                            <Link
                              href={`/company/${pCbe}`}
                              className="font-semibold text-sm text-brand hover:underline"
                            >
                              {p.name}
                            </Link>
                          ) : (
                            <span className="font-semibold text-sm text-slate-700">{p.name}</span>
                          )}
                          <div className="flex items-center gap-2 shrink-0">
                            {p.ownership_pct != null && (
                              <span className="font-mono text-xs font-medium text-slate-700">
                                {p.ownership_pct.toFixed(1)}%
                              </span>
                            )}
                            {p.fiscal_year && (
                              <Badge
                                variant="secondary"
                                className="text-[11px]"
                              >
                                {p.fiscal_year}
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Shareholders (collapsible) */}
          {structure.shareholders.length > 0 && (
            <Card>
              <CardContent>
                <button
                  type="button"
                  onClick={(e) => {
                    const content = (e.currentTarget as HTMLElement).nextElementSibling;
                    const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                    if (content) content.classList.toggle("hidden");
                    if (chevron) chevron.classList.toggle("rotate-180");
                  }}
                  className="w-full flex items-center justify-between mb-2 py-2 md:py-0 min-h-[44px] md:min-h-0"
                >
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
                    Shareholders ({structure.shareholders.length})
                  </h3>
                  <ChevronDown data-chevron className="h-4 w-4 text-slate-400 transition-transform" />
                </button>
                <div className="space-y-1.5">
                  {structure.shareholders.map((sh, i) => {
                    const shCbe = cleanCbe(sh.identifier);
                    return (
                      <div
                        key={`${sh.name}-${i}`}
                        className="rounded-md border px-3 py-3 md:py-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          {shCbe ? (
                            <Link
                              href={`/company/${shCbe}`}
                              className="font-semibold text-sm text-brand hover:underline"
                            >
                              {sh.name}
                            </Link>
                          ) : (
                            <Link
                              href={`/people?q=${encodeURIComponent(sh.name)}`}
                              className="font-semibold text-sm text-brand hover:underline"
                            >
                              {sh.name}
                            </Link>
                          )}
                          <div className="flex items-center gap-2 shrink-0">
                            {sh.ownership_pct != null && (
                              <span className="font-mono text-xs font-medium text-slate-700">
                                {sh.ownership_pct.toFixed(1)}%
                              </span>
                            )}
                            {sh.shareholder_type && (
                              <Badge
                                variant="secondary"
                                className="text-[11px]"
                              >
                                {sh.shareholder_type}
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Participating Interests (collapsible) */}
          {structure.participating_interests.length > 0 && (
            <Card>
              <CardContent>
                <button
                  type="button"
                  onClick={(e) => {
                    const content = (e.currentTarget as HTMLElement).nextElementSibling;
                    const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                    if (content) content.classList.toggle("hidden");
                    if (chevron) chevron.classList.toggle("rotate-180");
                  }}
                  className="w-full flex items-center justify-between mb-2 py-2 md:py-0 min-h-[44px] md:min-h-0"
                >
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-orange-500 pl-2">
                    Participating Interests ({structure.participating_interests.length})
                  </h3>
                  <ChevronDown data-chevron className="h-4 w-4 text-slate-400 transition-transform" />
                </button>
                <div className="space-y-1.5">
                  {structure.participating_interests.map((pi, i) => {
                    const piCbe = cleanCbe(pi.identifier);
                    return (
                      <div
                        key={`${pi.name}-${i}`}
                        className="rounded-md border px-3 py-3 md:py-2"
                      >
                        <div className="flex items-center justify-between gap-2">
                          {piCbe ? (
                            <Link
                              href={`/company/${piCbe}`}
                              className="font-semibold text-sm text-brand hover:underline"
                            >
                              {pi.name}
                            </Link>
                          ) : (
                            <Link
                              href={`/people?q=${encodeURIComponent(pi.name)}`}
                              className="font-semibold text-sm text-brand hover:underline"
                            >
                              {pi.name}
                            </Link>
                          )}
                          <div className="flex items-center gap-2 shrink-0">
                            {pi.ownership_pct != null && (
                              <span className="font-mono text-xs font-medium text-slate-700">
                                {pi.ownership_pct.toFixed(1)}%
                              </span>
                            )}
                            {pi.country && (
                              <Badge
                                variant="secondary"
                                className="text-[11px]"
                              >
                                {pi.country}
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}
      </div>

      {/* Right column: visual timelines */}
      <div className="space-y-3">
        {/* Shareholder Timeline */}
        {structure.shareholders.filter(sh => sh.fiscal_year).length > 0 && (
          <Card>
            <CardContent className="pt-3 pb-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2 mb-3">
                Shareholder Timeline
              </h3>
              <div className="relative pl-6">
                <div className="absolute left-2 top-0 bottom-0 w-px bg-green-200" />
                {structure.shareholders
                  .filter(sh => sh.fiscal_year)
                  .sort((a, b) => String(b.fiscal_year).localeCompare(String(a.fiscal_year)))
                  .map((sh, i) => (
                    <div key={i} className="relative mb-3 last:mb-0">
                      <div className="absolute -left-4 top-1 w-2.5 h-2.5 rounded-full bg-green-500 border-2 border-white" />
                      <div className="text-xs font-mono text-slate-400 mb-0.5">{sh.fiscal_year}</div>
                      <div className="text-sm font-medium text-slate-900">{sh.name}</div>
                      {sh.ownership_pct != null && (
                        <div className="text-xs text-slate-500">{sh.ownership_pct}% ownership</div>
                      )}
                    </div>
                  ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Subsidiary Timeline */}
        {structure.participating_interests.filter(pi => pi.fiscal_year).length > 0 && (
          <Card>
            <CardContent className="pt-3 pb-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-orange-500 pl-2 mb-3">
                Subsidiary Timeline
              </h3>
              <div className="relative pl-6">
                <div className="absolute left-2 top-0 bottom-0 w-px bg-orange-200" />
                {structure.participating_interests
                  .filter(pi => pi.fiscal_year)
                  .sort((a, b) => String(b.fiscal_year).localeCompare(String(a.fiscal_year)))
                  .map((pi, i) => (
                    <div key={i} className="relative mb-3 last:mb-0">
                      <div className="absolute -left-4 top-1 w-2.5 h-2.5 rounded-full bg-orange-500 border-2 border-white" />
                      <div className="text-xs font-mono text-slate-400 mb-0.5">{pi.fiscal_year}</div>
                      <div className="text-sm font-medium text-slate-900">{pi.name}</div>
                      {pi.ownership_pct != null && (
                        <div className="text-xs text-slate-500">{pi.ownership_pct}% ownership</div>
                      )}
                    </div>
                  ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
    </div>
  );
}
