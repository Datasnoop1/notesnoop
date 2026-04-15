"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { getCompanyNetwork, getDeepNetwork } from "@/lib/api";
import type { DeepNetworkResponse } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Maximize2, Minimize2, AlertTriangle } from "lucide-react";

interface NetworkNode {
  id: string;
  label: string;
  type: string;
  depth?: number;
}

interface NetworkEdge {
  source: string;
  target: string;
  relation: string;
  pct: number | null;
}

interface NetworkData {
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  truncated?: boolean;
  depth_reached?: number;
}

interface Props {
  cbe: string;
  companyName: string;
}

/* Depth-based color palette (darker = closer to target) */
const DEPTH_COLORS: Record<number, string> = {
  0: "#4f46e5", // indigo-600 — target company
  1: "#6366f1", // indigo-500 — direct
  2: "#818cf8", // indigo-400 — 2nd degree
  3: "#a5b4fc", // indigo-300 — 3rd degree
  4: "#c7d2fe", // indigo-200 — 4th degree
};

const DEPTH_LABELS: Record<number, string> = {
  0: "Target",
  1: "Direct",
  2: "2nd degree",
  3: "3rd degree",
  4: "4th degree",
};

export default function NetworkGraph({ cbe, companyName }: Props) {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const [data, setData] = useState<NetworkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [depth, setDepth] = useState(2);
  const [deepMode, setDeepMode] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [ForceGraph, setForceGraph] = useState<typeof import("react-force-graph-2d").default | null>(null);

  // Dynamic import of react-force-graph-2d (it uses canvas, SSR-incompatible)
  useEffect(() => {
    import("react-force-graph-2d").then((mod) => {
      setForceGraph(() => mod.default);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    if (deepMode) {
      getDeepNetwork(cbe, depth)
        .then((resp: DeepNetworkResponse) => {
          // Adapt deep network response to the shared NetworkData format
          const adapted: NetworkData = {
            nodes: resp.nodes.map((n) => ({
              id: n.id,
              label: n.name,
              type: n.type,
              depth: n.depth,
            })),
            edges: resp.edges.map((e) => ({
              source: e.source,
              target: e.target,
              relation: e.relationship || e.label,
              pct: null,
            })),
            truncated: resp.truncated,
            depth_reached: resp.depth_reached,
          };
          setData(adapted);
        })
        .catch(() => setData(null))
        .finally(() => setLoading(false));
    } else {
      getCompanyNetwork(cbe, depth)
        .then(setData)
        .catch(() => setData(null))
        .finally(() => setLoading(false));
    }
  }, [cbe, depth, deepMode]);

  // Close fullscreen on Escape
  useEffect(() => {
    if (!isFullscreen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsFullscreen(false);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isFullscreen]);

  // Configure force spacing + refit on data/mode change
  useEffect(() => {
    if (graphRef.current) {
      graphRef.current.d3Force("charge")?.strength(-200);
      graphRef.current.d3Force("link")?.distance(120);
      setTimeout(() => graphRef.current?.zoomToFit(400), 100);
    }
  }, [deepMode, depth, isFullscreen]);

  const handleNodeClick = useCallback(
    (node: { id?: string }) => {
      if (node.id && node.id !== cbe) {
        router.push(`/company/${node.id}`);
      }
    },
    [cbe, router]
  );

  if (loading) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-slate-400">
          Loading network graph...
        </CardContent>
      </Card>
    );
  }

  if (!data || data.nodes.length <= 1) {
    return null; // No connections to show
  }

  if (!ForceGraph) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-slate-400">
          Loading graph renderer...
        </CardContent>
      </Card>
    );
  }

  // Color nodes: in deep mode use depth-based colors, otherwise use type-based
  const nodeColor = (node: { type?: string; id?: string; depth?: number }) => {
    if (node.id === cbe) return "#4f46e5"; // indigo — current company
    if (deepMode && node.depth != null) {
      return DEPTH_COLORS[node.depth] || "#c7d2fe";
    }
    switch (node.type) {
      case "company": return "#6366f1";
      case "shareholder": return "#059669";
      case "subsidiary": return "#d97706";
      case "admin": return "#dc2626";
      default: return "#94a3b8";
    }
  };

  // Color edges by relation type: green for shareholder, orange for subsidiary
  const edgeColor = (link: { relation?: string }) => {
    const rel = (link.relation || "").toLowerCase();
    if (rel.includes("shareholder") || rel.includes("aandeelhouder")) return "#059669";
    if (rel.includes("subsidiary") || rel.includes("participating") || rel.includes("deelneming")) return "#d97706";
    return "#94a3b8";
  };

  const graphData = {
    nodes: data.nodes.map((n) => ({
      id: n.id,
      label: n.label,
      type: n.type,
      depth: n.depth,
      val: n.id === cbe ? 3 : 1,
    })),
    // Include ALL edges from the backend (inter-node connections for depth 2+)
    links: data.edges.map((e) => ({
      source: e.source,
      target: e.target,
      label: e.pct ? `${e.pct}%` : e.relation,
      relation: e.relation,
      pct: e.pct,
    })),
  };

  const graphHeight = isFullscreen ? window.innerHeight - 60 : 700;
  const graphWidth = isFullscreen
    ? window.innerWidth - 32
    : containerRef.current?.clientWidth || 800;

  const wrapperClass = isFullscreen
    ? "fixed inset-0 z-50 bg-white flex flex-col"
    : "";

  // Determine which depth levels are present for legend
  const depthLevels = deepMode
    ? [...new Set(data.nodes.map((n) => n.depth ?? 0))].sort()
    : [];

  return (
    <div className={wrapperClass}>
      <Card className={isFullscreen ? "border-0 rounded-none flex-1 flex flex-col" : ""}>
        <CardContent className={`pt-4 pb-2 ${isFullscreen ? "flex-1 flex flex-col" : ""}`}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-700">
              Corporate Network
            </h3>
            {!deepMode ? (
              <div className="flex gap-3 text-[11px] text-slate-500">
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-full bg-indigo-600 inline-block" />
                  Company
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-600 inline-block" />
                  Shareholder
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-600 inline-block" />
                  Subsidiary
                </span>
                {/* Edge color legend */}
                <span className="flex items-center gap-1 ml-2 border-l border-slate-200 pl-2">
                  <span className="w-4 h-0.5 bg-emerald-600 inline-block rounded" />
                  SH link
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-4 h-0.5 bg-amber-600 inline-block rounded" />
                  Sub link
                </span>
              </div>
            ) : (
              /* Deep mode legend: color-coded by depth */
              <div className="flex gap-3 text-[11px] text-slate-500">
                {depthLevels.map((d) => (
                  <span key={d} className="flex items-center gap-1">
                    <span
                      className="w-2.5 h-2.5 rounded-full inline-block"
                      style={{ backgroundColor: DEPTH_COLORS[d] || "#c7d2fe" }}
                    />
                    {DEPTH_LABELS[d] || `Depth ${d}`}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Truncation warning */}
          {deepMode && data.truncated && (
            <div className="flex items-center gap-2 px-3 py-2 mb-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              Graph capped at 100 nodes. Reached depth {data.depth_reached ?? depth}. Some connections may be hidden.
            </div>
          )}

          <div className="flex items-center gap-2 mb-2">
            {/* Mode toggle */}
            <div className="flex items-center rounded-md border border-slate-200 overflow-hidden">
              <button
                onClick={() => { setDeepMode(false); setDepth(Math.min(depth, 3)); }}
                className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                  !deepMode
                    ? "bg-indigo-600 text-white"
                    : "bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                Simple
              </button>
              <button
                onClick={() => setDeepMode(true)}
                className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                  deepMode
                    ? "bg-indigo-600 text-white"
                    : "bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                Deep
              </button>
            </div>

            <span className="text-[10px] text-slate-300">|</span>

            <span className="text-xs text-slate-500 font-medium">Depth:</span>
            {(deepMode ? [1, 2, 3, 4] : [1, 2, 3]).map(d => (
              <button
                key={d}
                onClick={() => setDepth(d)}
                className={`px-2.5 py-1 text-xs rounded-md font-medium transition-colors ${
                  depth === d
                    ? "bg-indigo-600 text-white"
                    : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
                }`}
              >
                {d === 1 ? "1st" : d === 2 ? "2nd" : d === 3 ? "3rd" : "4th"} degree
              </button>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={() => {
                  if (graphRef.current) {
                    graphRef.current.zoomToFit(400);
                  }
                }}
                className="px-2.5 py-1 text-xs rounded-md font-medium bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
              >
                Reset view
              </button>
              <button
                onClick={() => setIsFullscreen((prev) => !prev)}
                className="px-2.5 py-1 text-xs rounded-md font-medium bg-white text-slate-600 border border-slate-200 hover:bg-slate-50 inline-flex items-center gap-1"
              >
                {isFullscreen ? (
                  <><Minimize2 className="h-3 w-3" /> Exit fullscreen</>
                ) : (
                  <><Maximize2 className="h-3 w-3" /> Fullscreen</>
                )}
              </button>
            </div>
          </div>
          <div
            ref={containerRef}
            className={`border border-slate-200 rounded-lg overflow-hidden bg-white ${isFullscreen ? "flex-1" : ""}`}
            style={{ height: isFullscreen ? undefined : 700 }}
          >
            <ForceGraph
              ref={graphRef}
              graphData={graphData}
              width={graphWidth}
              height={graphHeight}
              nodeColor={nodeColor}
              nodeLabel={(node: { label?: string }) => node.label || ""}
              nodeRelSize={6}
              d3VelocityDecay={0.3}
              d3AlphaDecay={0.02}
              cooldownTicks={100}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              linkLabel={(link: { label?: string }) => link.label || ""}
              linkColor={edgeColor}
              linkWidth={(link: { pct?: number | null }) => (link.pct != null ? 1.5 : 1)}
              onNodeClick={handleNodeClick}
              linkCanvasObjectMode={() => "after"}
              linkCanvasObject={(
                link: { source?: any; target?: any; label?: string; pct?: number | null; relation?: string },
                ctx: CanvasRenderingContext2D,
                globalScale: number
              ) => {
                // Draw edge label (ownership %) on the link
                if (!link.label || globalScale < 0.5) return;
                const sx = typeof link.source === "object" ? link.source.x : 0;
                const sy = typeof link.source === "object" ? link.source.y : 0;
                const tx = typeof link.target === "object" ? link.target.x : 0;
                const ty = typeof link.target === "object" ? link.target.y : 0;
                const mx = (sx + tx) / 2;
                const my = (sy + ty) / 2;

                const fontSize = Math.min(10 / globalScale, 12);
                ctx.font = `${fontSize}px Inter, sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";

                // Background pill for readability
                const textWidth = ctx.measureText(link.label).width;
                const pad = 2 / globalScale;
                ctx.fillStyle = "rgba(255,255,255,0.85)";
                ctx.fillRect(mx - textWidth / 2 - pad, my - fontSize / 2 - pad, textWidth + pad * 2, fontSize + pad * 2);

                ctx.fillStyle = edgeColor(link as { relation?: string });
                ctx.fillText(link.label, mx, my);
              }}
              nodeCanvasObject={(
                node: { x?: number; y?: number; id?: string; label?: string; type?: string; depth?: number },
                ctx: CanvasRenderingContext2D,
                globalScale: number
              ) => {
                const x = node.x || 0;
                const y = node.y || 0;
                const isCenter = node.id === cbe;
                const r = isCenter ? 12 : (deepMode && node.depth != null ? Math.max(4, 8 - node.depth) : 5);
                const color = nodeColor(node);

                // Circle -- central company is bigger with bold border
                ctx.beginPath();
                ctx.arc(x, y, r, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
                ctx.strokeStyle = isCenter ? "#1e1b4b" : "#e2e8f0";
                ctx.lineWidth = isCenter ? 3 : 1;
                ctx.stroke();

                // Extra ring for central company
                if (isCenter) {
                  ctx.beginPath();
                  ctx.arc(x, y, r + 3, 0, 2 * Math.PI);
                  ctx.strokeStyle = "rgba(79, 70, 229, 0.3)";
                  ctx.lineWidth = 2;
                  ctx.stroke();
                }

                // Label
                if (globalScale > 0.5) {
                  const label = (node.label || "").substring(0, 30);
                  const fontSize = isCenter
                    ? Math.min(14 / globalScale, 16)
                    : Math.min(11 / globalScale, 13);
                  ctx.font = `${isCenter ? "bold " : ""}${fontSize}px Inter, sans-serif`;
                  ctx.textAlign = "center";
                  ctx.textBaseline = "top";
                  ctx.fillStyle = isCenter ? "#1e1b4b" : "#334155";
                  ctx.fillText(label, x, y + r + 3);
                }
              }}
            />
          </div>
          <p className="text-[11px] text-slate-400 mt-2 text-center">
            Click a node to navigate to that company &middot; {data.nodes.length} nodes, {data.edges.length} connections
            {deepMode && data.depth_reached != null && ` \u00b7 Depth reached: ${data.depth_reached}`}
            {isFullscreen && " \u00b7 Press Esc to exit fullscreen"}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
