"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Sparkles, Loader2, Scale, RefreshCw } from "lucide-react";
import { fmtEur, fmtNumber } from "@/lib/format";
import { useTranslation } from "@/components/language-provider";
import { useRouter } from "next/navigation";
import { getAiSimilarCompanies } from "@/lib/api";

/* ---------- Types ---------- */

interface AiSimilarCompany {
  enterprise_number: string;
  name: string;
  city: string;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  fiscal_year: number;
  ai_reason?: string;
}

interface SimilarTabProps {
  cbe: string;
}

/* ---------- Helpers ---------- */

function fmtPct(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "\u2014";
  return `${v.toFixed(1)}%`;
}

function computeMargin(ebitda: number | null, revenue: number | null): number | null {
  if (ebitda == null || !revenue) return null;
  return (ebitda / revenue) * 100;
}

/* ---------- Component ---------- */

export function SimilarTab({ cbe }: SimilarTabProps) {
  const router = useRouter();
  const { t } = useTranslation();
  const [companies, setCompanies] = useState<AiSimilarCompany[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const triggered = useRef(false);

  const loadSimilar = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAiSimilarCompanies(cbe);
      setCompanies(data.map((d) => ({ ...d, ai_reason: (d as Record<string, unknown>).ai_reason as string | undefined })));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("401") || msg.includes("403")) {
        setError("Sign in to use AI Similar Companies.");
      } else {
        setError("Could not load similar companies.");
      }
    } finally {
      setLoading(false);
    }
  };

  // Auto-trigger on mount
  useEffect(() => {
    if (!triggered.current) {
      triggered.current = true;
      loadSimilar();
    }
  }, [cbe]); // eslint-disable-line react-hooks/exhaustive-deps

  // Loading state
  if (loading && companies.length === 0) {
    return (
      <div className="py-12 text-center">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-indigo-50 border border-indigo-100">
          <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
          <span className="text-sm text-indigo-600 font-medium">Finding similar companies with AI...</span>
        </div>
        <p className="text-[11px] text-slate-400 mt-3">Analyzing sector, revenue, and business model</p>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="py-12 text-center">
        <Sparkles className="w-8 h-8 text-slate-300 mx-auto mb-2" />
        <p className="text-sm font-medium text-slate-500">{error}</p>
        <button onClick={loadSimilar} className="mt-3 text-xs text-indigo-500 hover:text-indigo-700 font-medium">
          Try again
        </button>
      </div>
    );
  }

  // Empty state
  if (companies.length === 0) {
    return (
      <div className="py-12 text-center">
        <Sparkles className="w-8 h-8 text-slate-300 mx-auto mb-2" />
        <p className="text-sm font-medium text-slate-400">No similar companies found</p>
        <p className="text-xs text-slate-300 mt-1">This company may have a unique profile with no close peers</p>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="h-7 px-2.5 rounded-full bg-indigo-50 border border-indigo-100 flex items-center gap-1.5">
            <Sparkles className="w-3 h-3 text-indigo-500" />
            <span className="text-[11px] font-semibold text-indigo-600">AI Similar Companies</span>
          </div>
          <span className="text-[10px] text-slate-400">({companies.length})</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadSimilar}
            disabled={loading}
            className="inline-flex items-center gap-1 text-[10px] text-slate-400 hover:text-indigo-600 transition-colors disabled:opacity-50"
            title="Regenerate"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
          </button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-[11px] text-indigo-600 border-indigo-200 hover:bg-indigo-50 px-3"
            onClick={() => {
              const cbes = companies.map((sc) => sc.enterprise_number);
              if (!cbes.includes(cbe)) cbes.unshift(cbe);
              sessionStorage.setItem("compare_companies", JSON.stringify(cbes));
              router.push("/compare");
            }}
          >
            <Scale className="w-3 h-3 mr-1" />
            Compare all
          </Button>
        </div>
      </div>

      {/* Results */}
      <div className="space-y-2">
        {companies.map((sc, idx) => {
          const margin = computeMargin(sc.ebitda, sc.revenue);
          return (
            <div key={sc.enterprise_number} className="rounded-lg border border-slate-100 bg-white p-3 hover:border-indigo-100 hover:bg-indigo-50/20 transition-colors">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-slate-300 w-5 shrink-0">#{idx + 1}</span>
                    <Link href={`/company/${sc.enterprise_number}`} className="text-sm font-semibold text-indigo-600 hover:text-indigo-800 hover:underline truncate">
                      {sc.name}
                    </Link>
                  </div>
                  {sc.ai_reason && (
                    <p className="text-[11px] text-slate-500 mt-1 ml-7 leading-relaxed">{sc.ai_reason}</p>
                  )}
                  <div className="flex items-center gap-3 mt-1.5 ml-7 text-[10px] text-slate-400">
                    {sc.city && <span>{sc.city}</span>}
                    {sc.revenue != null && <span className="font-mono">Rev {fmtEur(sc.revenue)}</span>}
                    {sc.ebitda != null && <span className="font-mono">EBITDA {fmtEur(sc.ebitda)}</span>}
                    {margin != null && <span className="font-mono">Margin {fmtPct(margin)}</span>}
                    {sc.fte_total != null && <span className="font-mono">{fmtNumber(sc.fte_total)} FTE</span>}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
