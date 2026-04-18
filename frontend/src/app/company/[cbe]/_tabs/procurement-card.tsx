"use client";

import React, { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { fmtEur } from "@/lib/format";

/* Procurement card — shows TED public-tender awards won by this CBE.
 * Hidden entirely when the company has no awards (most SMEs). */

interface AwardRow {
  ted_notice_id: string;
  buyer_name: string | null;
  award_date: string | null;
  contract_value: number | null;
  currency: string | null;
  cpv_code: string | null;
  title: string | null;
}

interface ProcurementData {
  awards: AwardRow[];
  total_3y_eur: number;
  count_3y: number;
}

export function CompanyProcurementCard({ cbe }: { cbe: string }) {
  const [data, setData] = useState<ProcurementData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch<ProcurementData>(`/api/open-data/companies/${cbe}/procurement`);
        if (!cancelled) setData(r);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [cbe]);

  if (loading) {
    return <div className="rounded-lg border bg-white p-3 animate-pulse h-[220px]" />;
  }
  // Hide the card when the company has no public procurement footprint — most SMEs.
  if (!data || !data.awards.length) return null;

  return (
    <div className="rounded-lg border bg-white p-3">
      <div className="flex items-start justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-amber-500 pl-2">
          Public tenders (last 3y)
        </h3>
        <div className="text-right">
          <div className="text-sm font-bold text-amber-700 font-mono">{fmtEur(data.total_3y_eur)}</div>
          <div className="text-[10px] text-slate-400">{data.count_3y} award{data.count_3y === 1 ? "" : "s"}</div>
        </div>
      </div>
      <div className="max-h-[170px] overflow-y-auto">
        <ul className="space-y-1">
          {data.awards.slice(0, 10).map((a) => (
            <li key={a.ted_notice_id} className="flex justify-between gap-2 text-[11px] border-b border-slate-100 pb-1">
              <div className="min-w-0 flex-1">
                <div className="font-medium text-slate-700 truncate" title={a.title ?? undefined}>
                  {a.title || "(untitled tender)"}
                </div>
                <div className="text-[10px] text-slate-400 truncate">
                  {a.buyer_name ?? "—"} · {a.award_date ?? "—"}
                </div>
              </div>
              <div className="text-right font-mono text-slate-700 shrink-0">
                {a.contract_value != null ? fmtEur(a.contract_value) : "—"}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
