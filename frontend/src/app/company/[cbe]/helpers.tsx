"use client";

import React, { useEffect, useState } from "react";
import { fmtEur } from "@/lib/format";

/* ---------- helper to clean CBE from identifier ---------- */

export function cleanCbe(id: string | null): string | null {
  if (!id) return null;
  const c = id.replace(/\./g, "").replace(/ /g, "").trim();
  return /^\d{10}$/.test(c) ? c : null;
}

/* ---------- Formula tooltip (credit tab) ---------- */

export function FormulaTooltip({ children, formula, detail }: { children: React.ReactNode; formula: string; detail?: string }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    // Defer binding so the opening click doesn't immediately close us.
    const t = setTimeout(() => document.addEventListener("click", () => setOpen(false), { once: true }), 0);
    return () => clearTimeout(t);
  }, [open]);

  return (
    <span className="group/tip relative inline-block">
      <span
        role="button"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
        className="cursor-help underline decoration-dotted decoration-slate-300 underline-offset-2 hover:decoration-solid hover:decoration-slate-500"
      >
        {children}
      </span>
      <div
        onClick={(e) => e.stopPropagation()}
        className={`absolute z-50 top-full left-0 mt-2 px-3 py-2 bg-slate-800 text-white text-[11px] rounded-lg shadow-lg transition-opacity duration-100 max-w-[260px] whitespace-normal break-words ${
          open
            ? "opacity-100"
            : "opacity-0 pointer-events-none group-hover/tip:opacity-100 group-hover/tip:pointer-events-auto"
        }`}
      >
        <div className="font-medium">{formula}</div>
        {detail && <div className="text-slate-300 font-mono mt-0.5">{detail}</div>}
        <div className="absolute bottom-full left-4 border-4 border-transparent border-b-slate-800" />
      </div>
    </span>
  );
}

/* ---------- YoY delta helper ---------- */

export function renderDelta(current: number | null, previous: number | null): React.ReactNode {
  if (current == null || previous == null || previous === 0) return null;
  const abs = current - previous;
  const pct = (abs / Math.abs(previous)) * 100;
  const sign = abs >= 0 ? "+" : "";
  const color = abs >= 0 ? "text-emerald-400" : "text-rose-400";
  const arrow = abs >= 0 ? "▲" : "▼";
  return (
    <div className={`${color} leading-tight`}>
      <div className="text-[10px] font-mono truncate">{sign}{fmtEur(abs)}</div>
      <div className="text-[9px] font-medium">{arrow} {sign}{pct.toFixed(1)}%</div>
    </div>
  );
}

/** Render delta column headers between year columns */
export function renderDeltaHeaders(years: number[]): React.ReactNode[] {
  const headers: React.ReactNode[] = [];
  for (let i = 0; i < years.length; i++) {
    headers.push(
      <th key={`y-${years[i]}`} className="px-1.5 md:px-3 py-2 text-right text-slate-400 font-medium min-w-[56px] md:min-w-[80px]">
        FY{years[i]}
      </th>
    );
    if (i < years.length - 1) {
      headers.push(
        <th key={`d-${years[i]}`} className="px-0.5 md:px-1 py-2 text-center text-slate-400 font-normal w-[32px] md:w-[70px] text-[10px] md:text-[9px]">
          Δ
        </th>
      );
    }
  }
  return headers;
}

/** Render value cells with delta columns between years */
export function renderValueCellsWithDeltas(
  values: (number | null)[],
  formatter: (v: number | null) => React.ReactNode,
  showDelta = true,
): React.ReactNode[] {
  const cells: React.ReactNode[] = [];
  for (let i = 0; i < values.length; i++) {
    cells.push(
      <td key={`v-${i}`} className="px-3 py-1 text-right font-mono text-xs">
        {formatter(values[i])}
      </td>
    );
    if (i < values.length - 1) {
      cells.push(
        <td key={`d-${i}`} className="px-1 py-1 text-center">
          {showDelta ? renderDelta(values[i + 1], values[i]) : null}
        </td>
      );
    }
  }
  return cells;
}

/* ---------- custom tooltip for chart ---------- */

export function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-white p-3 shadow-md">
      <p className="mb-1 text-xs font-semibold text-slate-700">FY {label}</p>
      {payload.map((entry) => (
        <p key={entry.name} className="text-xs" style={{ color: entry.color }}>
          {entry.name}: {fmtEur(entry.value)}
        </p>
      ))}
    </div>
  );
}

/* ---------- generic CSV export helper ---------- */

export function downloadCsv(filename: string, headers: string[], rows: (string | number | null)[][]) {
  const csvContent = [
    headers.join(","),
    ...rows.map((r) => r.map((v) => (v == null ? "" : String(v).includes(",") ? `"${v}"` : v)).join(",")),
  ].join("\n");
  const blob = new Blob([csvContent], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
