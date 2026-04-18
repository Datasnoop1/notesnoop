"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { apiFetch } from "@/lib/api";

/* Red insolvency banner shown at the top of the summary tab if Regsol has
 * any case for this CBE. Hidden when clean. */

interface CaseRow {
  docket_number: string;
  case_type: string | null;
  court: string | null;
  opened_at: string | null;
  closed_at: string | null;
  status: string | null;
  curator_name: string | null;
}

export function CompanyInsolvencyBadge({ cbe }: { cbe: string }) {
  const [cases, setCases] = useState<CaseRow[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch<{ cases: CaseRow[] }>(`/api/open-data/companies/${cbe}/insolvency`);
        if (!cancelled) setCases(r.cases ?? []);
      } catch {
        if (!cancelled) setCases([]);
      }
    })();
    return () => { cancelled = true; };
  }, [cbe]);

  if (!cases.length) return null;
  const openCase = cases.find((c) => c.status === "open") ?? cases[0];
  const isOpen = openCase.status === "open";

  return (
    <div className={`rounded-lg border-l-4 p-3 flex items-start gap-3 ${
      isOpen ? "border-rose-500 bg-rose-50" : "border-slate-400 bg-slate-50"
    }`}>
      <AlertTriangle className={`h-5 w-5 shrink-0 ${isOpen ? "text-rose-600" : "text-slate-500"}`} />
      <div className="text-xs">
        <div className={`font-semibold ${isOpen ? "text-rose-800" : "text-slate-700"}`}>
          {isOpen ? "Active insolvency proceeding" : "Historical insolvency record"}
        </div>
        <div className={`mt-0.5 ${isOpen ? "text-rose-700" : "text-slate-600"}`}>
          {openCase.case_type ?? "case"}
          {openCase.court && <> · {openCase.court}</>}
          {openCase.opened_at && <> · opened {openCase.opened_at}</>}
          {openCase.curator_name && <> · curator {openCase.curator_name}</>}
        </div>
      </div>
    </div>
  );
}
