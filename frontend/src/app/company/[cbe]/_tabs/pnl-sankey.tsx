"use client";

import React from "react";
import { fmtEur } from "@/lib/format";

/* Minimal SVG Sankey-ish diagram for the P&L: Revenue → (OpEx buckets, D&A, EBIT)
 * → (Financial charges, Tax, Net profit). No external dep — Recharts has no Sankey
 * and @nivo/sankey would add ~80kB. Acceptable visual fidelity for a 2-column flow.
 *
 * Rubric mapping (Belgian GAAP):
 *   70 = Revenue
 *   60 = Materials + consumables
 *   61 = Services + other goods
 *   62 = Personnel
 *   630 = D&A
 *   9901 = Operating profit (EBIT)
 *   65 = Financial charges
 *   67/77 = Tax (net)
 *   9904 = Net profit
 */

interface Props {
  rubrics: Record<string, Record<string, number | null>>; // { code: { fiscal_year: value } }
  fiscalYear: number;
}

function rub(r: Record<string, Record<string, number | null>>, code: string, fy: number): number {
  return Math.max(0, Number(r?.[code]?.[String(fy)] ?? 0));
}

export function PnlSankey({ rubrics, fiscalYear }: Props) {
  const revenue = rub(rubrics, "70", fiscalYear);
  if (revenue <= 0) return null;

  const materials = rub(rubrics, "60", fiscalYear);
  const services = rub(rubrics, "61", fiscalYear);
  const personnel = rub(rubrics, "62", fiscalYear);
  const da = rub(rubrics, "630", fiscalYear);
  const ebit = Math.max(0, Number(rubrics?.["9901"]?.[String(fiscalYear)] ?? 0));
  const finCharges = rub(rubrics, "65", fiscalYear);
  const tax = Math.max(0, Number(rubrics?.["67"]?.[String(fiscalYear)] ?? 0));
  const netProfit = Math.max(0, Number(rubrics?.["9904"]?.[String(fiscalYear)] ?? 0));

  // Dimensions
  const W = 520;
  const H = 240;
  const pad = 8;
  const barW = 14;
  const leftX = 80;
  const midX = 260;
  const rightX = 440;

  // Heights proportional to values
  const maxV = revenue;
  const h = (v: number) => Math.max(1, (v / maxV) * (H - 2 * pad));

  // Left column: Revenue only
  const revH = h(revenue);
  const revY = pad + (H - 2 * pad - revH) / 2;

  // Middle column: OpEx buckets + EBIT (stacked top-to-bottom)
  type Block = { label: string; value: number; color: string };
  const mid: Block[] = [
    { label: "Materials", value: materials, color: "#a78bfa" },
    { label: "Services",  value: services,  color: "#22d3ee" },
    { label: "Personnel", value: personnel, color: "#fbbf24" },
    { label: "D&A",       value: da,        color: "#f97316" },
    { label: "EBIT",      value: ebit,      color: "#10b981" },
  ];
  const midTotal = mid.reduce((s, b) => s + b.value, 0) || revenue;
  const scaleMid = revH / midTotal;
  let y = revY;
  const midBlocks = mid.map((b) => {
    const hh = b.value * scaleMid;
    const block = { ...b, y, h: hh };
    y += hh;
    return block;
  });

  // Right column: Fin charges, Tax, Net profit (stack inside EBIT's height)
  const ebitBlock = midBlocks.find((b) => b.label === "EBIT")!;
  const ebitTotal = ebit || (finCharges + tax + netProfit);
  const right: Block[] = [
    { label: "Fin. charges", value: finCharges, color: "#ef4444" },
    { label: "Tax",          value: tax,        color: "#78716c" },
    { label: "Net profit",   value: netProfit,  color: "#059669" },
  ];
  const rTotal = right.reduce((s, b) => s + b.value, 0) || ebitTotal;
  const scaleR = (ebitBlock.h) / rTotal;
  let ry = ebitBlock.y;
  const rightBlocks = right.map((b) => {
    const hh = b.value * scaleR;
    const block = { ...b, y: ry, h: hh };
    ry += hh;
    return block;
  });

  function curve(x1: number, y1: number, x2: number, y2: number, stroke: string, strokeWidth: number) {
    const cx = (x1 + x2) / 2;
    return (
      <path
        d={`M ${x1},${y1} C ${cx},${y1} ${cx},${y2} ${x2},${y2}`}
        stroke={stroke}
        strokeWidth={strokeWidth}
        fill="none"
        strokeOpacity={0.4}
      />
    );
  }

  return (
    <div className="rounded-lg border bg-white p-3">
      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2 mb-2">
        P&amp;L flow — FY{fiscalYear}
      </h3>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        {/* Revenue → mid flows */}
        {midBlocks.map((b) => (
          <g key={`rflow-${b.label}`}>
            {curve(leftX + barW, revY + (b.y + b.h / 2 - revY), midX, b.y + b.h / 2, b.color, b.h)}
          </g>
        ))}
        {/* EBIT → right flows */}
        {rightBlocks.map((b) => (
          <g key={`eflow-${b.label}`}>
            {curve(midX + barW, b.y + b.h / 2, rightX, b.y + b.h / 2, b.color, b.h)}
          </g>
        ))}

        {/* Revenue bar */}
        <rect x={leftX} y={revY} width={barW} height={revH} fill="#6366f1" />
        <text x={leftX - 4} y={revY + revH / 2} fontSize={10} textAnchor="end" dominantBaseline="middle" fill="#334155">
          Revenue
        </text>
        <text x={leftX - 4} y={revY + revH / 2 + 11} fontSize={9} textAnchor="end" dominantBaseline="middle" fill="#94a3b8">
          {fmtEur(revenue)}
        </text>

        {/* Mid bars + labels */}
        {midBlocks.map((b) => (
          <g key={`mid-${b.label}`}>
            <rect x={midX} y={b.y} width={barW} height={b.h} fill={b.color} />
            <text x={midX + barW + 4} y={b.y + b.h / 2} fontSize={10} dominantBaseline="middle" fill="#334155">
              {b.label}
            </text>
          </g>
        ))}

        {/* Right bars + labels */}
        {rightBlocks.map((b) => (
          <g key={`r-${b.label}`}>
            <rect x={rightX} y={b.y} width={barW} height={b.h} fill={b.color} />
            <text x={rightX + barW + 4} y={b.y + b.h / 2} fontSize={10} dominantBaseline="middle" fill="#334155">
              {b.label}
            </text>
            <text x={rightX + barW + 4} y={b.y + b.h / 2 + 11} fontSize={9} dominantBaseline="middle" fill="#94a3b8">
              {fmtEur(b.value)}
            </text>
          </g>
        ))}
      </svg>
      <p className="text-[10px] text-slate-400 italic mt-1">
        Revenue splits into cost buckets + EBIT; EBIT then splits into financial charges, tax, and net profit.
      </p>
    </div>
  );
}
