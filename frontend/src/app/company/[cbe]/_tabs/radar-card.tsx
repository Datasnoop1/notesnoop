"use client";

import React, { useEffect, useState } from "react";
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { apiFetch } from "@/lib/api";

/* Snowflake-style radar chart: 6 axes (Scale / Profitability / Efficiency
 * / Leverage / Liquidity / Growth), each 0..100 vs NACE-2 peers. Pulled
 * from /api/open-data/companies/{cbe}/radar which uses the sector_percentiles
 * MV + derived leverage / liquidity scores. */

interface RadarData {
  scores: Record<string, number | null> | null;
  peer_count: number;
}

export function CompanyRadarCard({ cbe }: { cbe: string }) {
  const [data, setData] = useState<RadarData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch<RadarData>(`/api/open-data/companies/${cbe}/radar`);
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
    return (
      <div className="rounded-lg border bg-white p-3 animate-pulse h-[220px]" />
    );
  }
  if (!data?.scores || data.peer_count < 10) return null;

  const chartData = Object.entries(data.scores)
    .filter(([, v]) => v != null)
    .map(([name, value]) => ({ axis: name, value: value as number }));

  if (chartData.length < 3) return null;

  return (
    <div className="rounded-lg border bg-white p-3">
      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2 mb-2">
        Sector radar — {data.peer_count} peers
      </h3>
      <ResponsiveContainer width="100%" height={220}>
        <RadarChart data={chartData} outerRadius="72%">
          <PolarGrid stroke="#e2e8f0" />
          <PolarAngleAxis dataKey="axis" tick={{ fontSize: 10, fill: "#64748b" }} />
          <PolarRadiusAxis tick={false} domain={[0, 100]} stroke="#cbd5e1" />
          <Tooltip formatter={(v: number) => `${v?.toFixed(0)}/100`} />
          <Radar
            name="Score"
            dataKey="value"
            stroke="#6366f1"
            fill="#6366f1"
            fillOpacity={0.35}
          />
        </RadarChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-slate-400 italic mt-1">
        Each axis 0–100 vs same-sector peers. Leverage &amp; Liquidity are
        derived; others use percentile rank.
      </p>
    </div>
  );
}
