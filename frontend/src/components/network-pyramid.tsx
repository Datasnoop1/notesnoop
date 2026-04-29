"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getDeepNetwork } from "@/lib/api";
import type {
  DeepNetworkResponse,
  DeepNetworkNode,
  DeepNetworkEdge,
} from "@/lib/api";
import { Loader2, AlertTriangle, ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

interface Props {
  cbe: string;
  companyName: string;
  vat?: string | null;
}

// One node positioned in the pyramid layout.
interface PyramidNode {
  id: string;
  name: string;
  /** Level relative to target: negative = ancestor, 0 = target, positive = descendant */
  level: number;
  /** % stake on the edge from this node to its parent at the previous level (or vice versa) */
  edgePct?: string;
  /** id of the node ON THE OPPOSITE SIDE OF THE EDGE — i.e. a level closer to target */
  toward: string | null;
  x: number; // computed
  y: number; // computed
  isTarget?: boolean;
}

interface BuildResult {
  nodes: PyramidNode[];
  width: number;
  height: number;
  hasAncestors: boolean;
  hasDescendants: boolean;
}

// Layout constants
const BOX_W = 150;
const BOX_H = 56;
const ROW_GAP = 96; // vertical gap between row centres beyond box height
const COL_GAP = 28; // minimum horizontal gap between siblings
const MARGIN_X = 40;
const MARGIN_Y = 40;

function indexResponse(resp: DeepNetworkResponse) {
  const nodeById = new Map<string, DeepNetworkNode>();
  resp.nodes.forEach((n) => nodeById.set(n.id, n));
  const outgoing = new Map<string, DeepNetworkEdge[]>();
  const incoming = new Map<string, DeepNetworkEdge[]>();
  resp.edges.forEach((e) => {
    const out = outgoing.get(e.source) ?? [];
    out.push(e);
    outgoing.set(e.source, out);
    const inc = incoming.get(e.target) ?? [];
    inc.push(e);
    incoming.set(e.target, inc);
  });
  return { nodeById, outgoing, incoming };
}

function buildPyramid(
  resp: DeepNetworkResponse,
  rootId: string,
  rootName: string,
  maxDepth: number,
): BuildResult {
  const { nodeById, outgoing, incoming } = indexResponse(resp);

  // Ancestors (upward via incoming participating_interest edges — parent → root)
  const ancestorRows: PyramidNode[][] = [];
  {
    const visited = new Set<string>([rootId]);
    let frontier: string[] = [rootId];
    for (let lvl = 1; lvl <= maxDepth; lvl++) {
      const row: PyramidNode[] = [];
      const seenSrc = new Set<string>();
      for (const childId of frontier) {
        for (const e of incoming.get(childId) ?? []) {
          if (e.relationship !== "participating_interest") continue;
          if (e.source === childId) continue;
          if (visited.has(e.source) || seenSrc.has(e.source)) continue;
          seenSrc.add(e.source);
          const node = nodeById.get(e.source);
          if (!node) continue;
          row.push({
            id: e.source,
            name: node.name,
            level: -lvl,
            edgePct: e.label || undefined,
            toward: childId,
            x: 0,
            y: 0,
          });
        }
      }
      if (!row.length) break;
      row.forEach((n) => visited.add(n.id));
      ancestorRows.push(row);
      frontier = row.map((n) => n.id);
    }
  }

  // Descendants (downward via outgoing participating_interest edges — root → sub)
  const descendantRows: PyramidNode[][] = [];
  {
    const visited = new Set<string>([rootId]);
    let frontier: string[] = [rootId];
    for (let lvl = 1; lvl <= maxDepth; lvl++) {
      const row: PyramidNode[] = [];
      const seenTgt = new Set<string>();
      for (const parentId of frontier) {
        for (const e of outgoing.get(parentId) ?? []) {
          if (e.relationship !== "participating_interest") continue;
          if (e.target === parentId) continue;
          if (visited.has(e.target) || seenTgt.has(e.target)) continue;
          seenTgt.add(e.target);
          const node = nodeById.get(e.target);
          if (!node) continue;
          row.push({
            id: e.target,
            name: node.name,
            level: lvl,
            edgePct: e.label || undefined,
            toward: parentId,
            x: 0,
            y: 0,
          });
        }
      }
      if (!row.length) break;
      row.forEach((n) => visited.add(n.id));
      descendantRows.push(row);
      frontier = row.map((n) => n.id);
    }
  }

  // Compose row order top→bottom: deepest ancestors first, then ..., parents,
  // target, direct subs, ..., deepest descendants.
  const allRows: PyramidNode[][] = [
    ...[...ancestorRows].reverse(),
    [
      {
        id: rootId,
        name: rootName,
        level: 0,
        toward: null,
        x: 0,
        y: 0,
        isTarget: true,
      },
    ],
    ...descendantRows,
  ];

  // Width: drive by widest row, never less than 880
  const widestCount = Math.max(...allRows.map((r) => r.length), 1);
  const usableWidth = Math.max(880, widestCount * (BOX_W + COL_GAP) + MARGIN_X * 2);

  // Position each row horizontally centred, stretched evenly.
  allRows.forEach((row, idx) => {
    const y = MARGIN_Y + idx * (BOX_H + ROW_GAP) + BOX_H / 2;
    if (row.length === 1) {
      row[0].x = usableWidth / 2;
      row[0].y = y;
      return;
    }
    // Evenly spaced; first node centred at MARGIN_X+BOX_W/2, last at usableWidth-MARGIN_X-BOX_W/2
    const left = MARGIN_X + BOX_W / 2;
    const right = usableWidth - MARGIN_X - BOX_W / 2;
    const step = (right - left) / (row.length - 1);
    row.forEach((n, i) => {
      n.x = left + i * step;
      n.y = y;
    });
  });

  const totalHeight =
    MARGIN_Y * 2 + allRows.length * BOX_H + (allRows.length - 1) * ROW_GAP;

  const flat = allRows.flat();
  return {
    nodes: flat,
    width: usableWidth,
    height: totalHeight,
    hasAncestors: ancestorRows.length > 0,
    hasDescendants: descendantRows.length > 0,
  };
}

// ----------------------------------------------------------------------

export default function NetworkPyramid({ cbe, companyName, vat }: Props) {
  const router = useRouter();
  const [resp, setResp] = useState<DeepNetworkResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [depth, setDepth] = useState(2);
  const [historical, setHistorical] = useState(false);
  const [zoom, setZoom] = useState(1);
  const wrapRef = useRef<HTMLDivElement>(null);

  // 1) Fetch network
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDeepNetwork(cbe, depth, historical)
      .then((r) => {
        if (cancelled) return;
        setResp(r);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e?.message ?? e));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [cbe, depth, historical]);

  // 2) Build the pyramid
  const layout = useMemo<BuildResult | null>(() => {
    if (!resp) return null;
    return buildPyramid(resp, cbe, companyName, depth);
  }, [resp, cbe, companyName, depth]);

  const isEmpty = !!layout && !layout.hasAncestors && !layout.hasDescendants;

  function nodeClick(n: PyramidNode) {
    if (n.isTarget) return;
    // Only navigate to nodes that look like Belgian CBEs (10 digits).
    if (/^\d{10}$/.test(n.id)) {
      router.push(`/company/${n.id}`);
    }
  }

  return (
    <div>
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-4 text-sm">
        <label className="flex items-center gap-2 text-[#475569]">
          <span className="text-[12px] uppercase tracking-wider font-medium text-[#64748B]">
            Depth
          </span>
          <select
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value))}
            className="rounded border border-[#E2E8F2] bg-white px-2 py-1 text-[13px] text-[#0F172A]"
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-[#475569] cursor-pointer">
          <input
            type="checkbox"
            checked={historical}
            onChange={(e) => setHistorical(e.target.checked)}
            className="rounded border-[#CBD5E1]"
          />
          <span className="text-[13px]">Include historical links</span>
        </label>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setZoom((z) => Math.max(0.4, z - 0.15))}
            title="Zoom out"
            className="h-7 w-7 inline-flex items-center justify-center rounded border border-[#E2E8F2] bg-white text-[#475569] hover:bg-slate-50"
          >
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setZoom(1)}
            title="Reset zoom"
            className="h-7 w-7 inline-flex items-center justify-center rounded border border-[#E2E8F2] bg-white text-[#475569] hover:bg-slate-50"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setZoom((z) => Math.min(2.5, z + 0.15))}
            title="Zoom in"
            className="h-7 w-7 inline-flex items-center justify-center rounded border border-[#E2E8F2] bg-white text-[#475569] hover:bg-slate-50"
          >
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
        </div>
        {resp?.truncated && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-full">
            <AlertTriangle className="h-3 w-3" />
            Truncated · reached depth {resp.depth_reached}
          </span>
        )}
      </div>

      {error && (
        <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-[13px] text-rose-800 mb-3">
          {error}
        </div>
      )}

      {loading && !error && (
        <div className="flex items-center justify-center py-16 text-sm text-[#64748B]">
          <Loader2 className="h-4 w-4 animate-spin mr-2" />
          Building group pyramid…
        </div>
      )}

      {!loading && !error && layout && (
        <>
          {isEmpty ? (
            <div className="rounded border border-[#E2E8F2] bg-[#F8FAFC] px-4 py-10 text-center text-sm text-[#64748B]">
              No parent companies or subsidiaries found for this company.
            </div>
          ) : (
            <div
              ref={wrapRef}
              className="relative overflow-auto rounded-lg border border-[#E2E8F2] bg-[#fafaf9]"
              style={{ minHeight: 360 }}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width={layout.width * zoom}
                height={layout.height * zoom}
                viewBox={`0 0 ${layout.width} ${layout.height}`}
                style={{ display: "block" }}
              >
                <defs>
                  <marker
                    id="pyramid-arrow"
                    viewBox="0 -4 10 8"
                    refX={8}
                    refY={0}
                    markerWidth={7}
                    markerHeight={7}
                    orient="auto"
                  >
                    <path d="M0,-4L10,0L0,4Z" fill="#fda4af" />
                  </marker>
                </defs>

                {/* Edges */}
                {layout.nodes.map((n) => {
                  if (n.toward == null) return null;
                  const other = layout.nodes.find((m) => m.id === n.toward);
                  if (!other) return null;

                  // Arrow direction:
                  //   ancestors are owners (parent at top → child at bottom)  → arrow goes from ancestor down to child
                  //   descendants are owned (child at bottom → parent at top) → arrow goes from target down to sub
                  // Visually both render top-to-bottom because pyramid layout
                  // puts higher-y on owner side.
                  const fromX = other.x;
                  const fromY = other.y + BOX_H / 2; // bottom of upper box
                  const toX = n.x;
                  const toY = n.y - BOX_H / 2 - 2; // top of lower box minus arrow inset
                  // For ancestors, the geometry is already correct (other = level closer to target = below).
                  // We swap so the arrow always points DOWN from owner to owned.
                  let aX: number, aY: number, bX: number, bY: number;
                  if (n.level < 0) {
                    // n is ancestor (above), other is closer to target (below)
                    // owner = n (upper), owned = other (lower)
                    aX = n.x;
                    aY = n.y + BOX_H / 2;
                    bX = other.x;
                    bY = other.y - BOX_H / 2 - 2;
                  } else {
                    // n is descendant (below), other is closer to target (above)
                    // owner = other (upper), owned = n (lower)
                    aX = fromX;
                    aY = fromY;
                    bX = toX;
                    bY = toY;
                  }
                  // Curved cubic bezier for visual softness
                  const midY = (aY + bY) / 2;
                  const dPath = `M ${aX} ${aY} C ${aX} ${midY}, ${bX} ${midY}, ${bX} ${bY}`;
                  // % label midpoint
                  const labelX = (aX + bX) / 2;
                  const labelY = midY;

                  return (
                    <g key={`edge-${n.id}-${n.toward}`}>
                      <path
                        d={dPath}
                        stroke="#fda4af"
                        strokeWidth={1.6}
                        fill="none"
                        markerEnd="url(#pyramid-arrow)"
                      />
                      {n.edgePct && (
                        <g transform={`translate(${labelX},${labelY})`}>
                          <rect
                            x={-26}
                            y={-9}
                            width={52}
                            height={18}
                            rx={4}
                            fill="#fff1f2"
                            stroke="#fecdd3"
                          />
                          <text
                            textAnchor="middle"
                            dy="0.32em"
                            style={{
                              fontFamily:
                                "var(--font-geist-mono), ui-monospace, monospace",
                              fontSize: 11,
                              fontWeight: 600,
                              fill: "#9f1239",
                            }}
                          >
                            {n.edgePct}
                          </text>
                        </g>
                      )}
                    </g>
                  );
                })}

                {/* Nodes */}
                {layout.nodes.map((n) => {
                  const navigable = !n.isTarget && /^\d{10}$/.test(n.id);
                  return (
                    <g
                      key={n.id}
                      transform={`translate(${n.x - BOX_W / 2},${n.y - BOX_H / 2})`}
                      onClick={() => nodeClick(n)}
                      style={{ cursor: navigable ? "pointer" : "default" }}
                    >
                      <rect
                        width={BOX_W}
                        height={BOX_H}
                        rx={8}
                        fill={n.isTarget ? "#fff7ed" : "#ffffff"}
                        stroke={n.isTarget ? "#ea580c" : "#cbd5e1"}
                        strokeWidth={n.isTarget ? 2 : 1}
                      />
                      <foreignObject x={6} y={6} width={BOX_W - 12} height={BOX_H - 12}>
                        <div
                          style={{
                            width: "100%",
                            height: "100%",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                          title={n.name}
                        >
                          <span
                            style={{
                              textAlign: "center",
                              fontFamily:
                                "var(--font-geist), system-ui, sans-serif",
                              color: n.isTarget ? "#9a3412" : "#0f172a",
                              fontSize: 12.5,
                              fontWeight: n.isTarget ? 700 : 500,
                              lineHeight: 1.2,
                              display: "-webkit-box",
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                              wordBreak: "break-word",
                            }}
                          >
                            {n.name}
                          </span>
                        </div>
                      </foreignObject>
                    </g>
                  );
                })}
              </svg>
            </div>
          )}

          <div className="mt-3 flex flex-wrap gap-x-7 gap-y-1.5 text-[12.5px] text-[#64748B]">
            <span>
              <strong className="text-[#0F172A] font-semibold mr-1">
                Above the target
              </strong>
              parent companies that own it
            </span>
            <span>
              <strong className="text-[#0F172A] font-semibold mr-1">
                Below the target
              </strong>
              subsidiaries it owns
            </span>
            <span>
              <strong className="text-[#0F172A] font-semibold mr-1">
                Click any box
              </strong>
              to open that company's profile
            </span>
          </div>
          {vat && (
            <div className="mt-1 text-[11.5px] text-[#94A3B8] font-mono">{vat}</div>
          )}
        </>
      )}
    </div>
  );
}
