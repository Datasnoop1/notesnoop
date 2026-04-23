"use client";

import { useEffect, useLayoutEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { getDeepNetwork } from "@/lib/api";
import type { DeepNetworkResponse } from "@/lib/api";
import { useTranslation } from "@/components/language-provider";
import { Card, CardContent } from "@/components/ui/card";
import { Maximize2, Minimize2, AlertTriangle, ArrowLeft, ExternalLink } from "lucide-react";

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
  is_active: boolean;
  mandate_end: string | null;
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

function isCompanyNodeId(id: string | undefined): id is string {
  return typeof id === "string" && /^\d{10}$/.test(id);
}

function isPersonNodeId(id: string | undefined): id is string {
  return typeof id === "string" && id.startsWith("person:");
}

/* Depth-based color palette (darker = closer to target) */
const DEPTH_COLORS: Record<number, string> = {
  0: "#4f46e5", // indigo-600 — target company
  1: "#6366f1", // indigo-500 — direct
  2: "#818cf8", // indigo-400 — 2nd degree
  3: "#a5b4fc", // indigo-300 — 3rd degree
  4: "#c7d2fe", // indigo-200 — 4th degree
};

export default function NetworkGraph({ cbe, companyName }: Props) {
  const { t } = useTranslation();

  const DEPTH_LABELS: Record<number, string> = {
    0: t("company.networkTab.target"),
    1: t("company.networkTab.direct"),
    2: t("company.networkTab.degree2"),
    3: t("company.networkTab.degree3"),
    4: t("company.networkTab.degree4"),
  };
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const [data, setData] = useState<NetworkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [depth, setDepth] = useState(2);
  const [isFullscreen, setIsFullscreen] = useState(false);
  // The node the graph is currently centered on. Starts as the company
  // whose profile the user is on; a node click re-centers the graph
  // without navigating away from the tab. A small pill at the top lets
  // the operator jump back to the original.
  const [centerNodeId, setCenterNodeId] = useState<string>(cbe);
  const [centerLabel, setCenterLabel] = useState<string>(companyName);
  // Reset to the profile's CBE whenever the parent route changes.
  useEffect(() => {
    setCenterNodeId(cbe);
    setCenterLabel(companyName);
  }, [cbe, companyName]);
  // Initialize with a viewport-aware default so the first render isn't 0-wide
  // on mobile; the layout effect below refines it to the actual container width.
  const [graphWidth, setGraphWidth] = useState(() =>
    typeof window !== "undefined" ? Math.min(window.innerWidth - 32, 1000) : 800,
  );
  const [ForceGraph, setForceGraph] = useState<typeof import("react-force-graph-2d").default | null>(null);

  // Dynamic import of react-force-graph-2d (it uses canvas, SSR-incompatible)
  useEffect(() => {
    import("react-force-graph-2d").then((mod) => {
      setForceGraph(() => mod.default);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    getDeepNetwork(centerNodeId, depth)
      .then((resp: DeepNetworkResponse) => {
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
            is_active: e.is_active !== false,
            mandate_end: e.mandate_end ?? null,
          })),
          truncated: resp.truncated,
          depth_reached: resp.depth_reached,
        };
        setData(adapted);
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [centerNodeId, depth]);

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
  }, [depth, isFullscreen, graphWidth]);

  // Track container width so the graph fits cleanly on mobile. Falling
  // back to a hard-coded 800px used to overflow the viewport on phones.
  useLayoutEffect(() => {
    if (loading || !ForceGraph || !data) return;
    if (isFullscreen) {
      const update = () => setGraphWidth(window.innerWidth - 32);
      update();
      window.addEventListener("resize", update);
      return () => window.removeEventListener("resize", update);
    }
    const el = containerRef.current;
    if (!el) return;
    setGraphWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setGraphWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [isFullscreen, loading, ForceGraph, data]);

  // Clicking a node RE-CENTERS the spider web around either a company or a
  // person. Synthetic subsidiary placeholders still do not expand.
  const handleNodeClick = useCallback(
    (node: { id?: string; label?: string; type?: string }) => {
      if ((isCompanyNodeId(node.id) || isPersonNodeId(node.id)) && node.id !== centerNodeId) {
        setCenterNodeId(node.id);
        setCenterLabel(node.label || node.id);
      }
    },
    [centerNodeId]
  );

  if (loading) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-slate-400">
          {t("company.networkTab.loading")}
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
          {t("company.networkTab.loadingRenderer")}
        </CardContent>
      </Card>
    );
  }

  // Depth-based node colors (darker closer to target)
  const nodeColor = (node: { type?: string; id?: string; depth?: number }) => {
    if (node.id === centerNodeId) return "#4f46e5";
    if (node.depth != null) return DEPTH_COLORS[node.depth] || "#c7d2fe";
    return "#94a3b8";
  };

  // Color edges by relation type: green for shareholder, orange for subsidiary.
  // Ended administrator mandates render as desaturated grey so they recede
  // visually behind active connections.
  const edgeColor = (link: { relation?: string; is_active?: boolean }) => {
    if (link.is_active === false) return "#cbd5e1"; // slate-300 — past
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
      val: n.id === centerNodeId ? 3 : 1,
    })),
    // Include ALL edges from the backend (inter-node connections for depth 2+)
    links: data.edges.map((e) => ({
      source: e.source,
      target: e.target,
      label: e.pct ? `${e.pct}%` : e.relation,
      relation: e.relation,
      pct: e.pct,
      is_active: e.is_active,
      mandate_end: e.mandate_end,
    })),
  };

  const graphHeight = isFullscreen ? window.innerHeight - 60 : 700;

  const wrapperClass = isFullscreen
    ? "fixed inset-0 z-50 bg-white flex flex-col"
    : "";

  const depthLevels = [...new Set(data.nodes.map((n) => n.depth ?? 0))].sort();
  const centeredOnOriginalCompany = centerNodeId === cbe;
  const centeredCompanyId = isCompanyNodeId(centerNodeId) ? centerNodeId : null;

  return (
    <div className={wrapperClass}>
      <Card className={isFullscreen ? "border-0 rounded-none flex-1 flex flex-col" : ""}>
        <CardContent className={`pt-4 pb-2 ${isFullscreen ? "flex-1 flex flex-col" : ""}`}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-700">
              {t("company.networkTab.title")}
            </h3>
            <div className="flex flex-wrap gap-3 text-[11px] text-slate-500">
              {depthLevels.map((d) => (
                <span key={d} className="flex items-center gap-1">
                  <span
                    className="w-2.5 h-2.5 rounded-full inline-block"
                    style={{ backgroundColor: DEPTH_COLORS[d] || "#c7d2fe" }}
                  />
                  {DEPTH_LABELS[d] || `Depth ${d}`}
                </span>
              ))}
              {data.edges.some((e) => e.is_active === false) && (
                <span className="flex items-center gap-1">
                  <svg width="20" height="6" viewBox="0 0 20 6" aria-hidden>
                    <line x1="0" y1="3" x2="20" y2="3" stroke="#cbd5e1" strokeWidth="1.5" strokeDasharray="3 3" />
                  </svg>
                  {t("company.networkTab.endedMandate")}
                </span>
              )}
            </div>
          </div>

          {/* Centre badge — shows which CBE the spider web is currently
              focused on. After a node click this is different from the
              profile's CBE, so we also offer a back-to-original pill and
              a link to the clicked company's full profile. */}
          {!centeredOnOriginalCompany && (
            <div className="flex items-center gap-2 px-3 py-2 mb-2 bg-indigo-50 border border-indigo-200 rounded-lg text-xs">
              <span className="text-indigo-700">
                Centered on <strong>{centerLabel}</strong>{" "}
                {centeredCompanyId && (
                  <span className="text-indigo-400 font-mono">({centeredCompanyId})</span>
                )}
              </span>
              <button
                type="button"
                onClick={() => { setCenterNodeId(cbe); setCenterLabel(companyName); }}
                className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded border border-indigo-200 bg-white text-indigo-700 hover:bg-indigo-100"
              >
                <ArrowLeft className="h-3 w-3" /> Back to {companyName}
              </button>
              {centeredCompanyId && (
                <Link
                  href={`/company/${centeredCompanyId}`}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded border border-indigo-200 bg-white text-indigo-700 hover:bg-indigo-100"
                >
                  <ExternalLink className="h-3 w-3" /> Open profile
                </Link>
              )}
            </div>
          )}

          {/* Truncation warning */}
          {data.truncated && (
            <div className="flex items-center gap-2 px-3 py-2 mb-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              {t("company.networkTab.truncationWarning").replace("{depth}", String(data.depth_reached ?? depth))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="text-xs text-slate-500 font-medium">{t("company.networkTab.depth")}</span>
            {[1, 2, 3, 4].map(d => (
              <button
                key={d}
                onClick={() => setDepth(d)}
                className={`px-3 py-2 md:px-2.5 md:py-1 text-xs rounded-md font-medium transition-colors ${
                  depth === d
                    ? "bg-indigo-600 text-white"
                    : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
                }`}
              >
                {t(`company.networkTab.degree${d}`)}
              </button>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={() => {
                  if (graphRef.current) {
                    graphRef.current.zoomToFit(400);
                  }
                }}
                className="px-3 py-2 md:px-2.5 md:py-1 text-xs rounded-md font-medium bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
              >
                {t("company.networkTab.resetView")}
              </button>
              <button
                onClick={() => setIsFullscreen((prev) => !prev)}
                className="px-3 py-2 md:px-2.5 md:py-1 text-xs rounded-md font-medium bg-white text-slate-600 border border-slate-200 hover:bg-slate-50 inline-flex items-center gap-1"
              >
                {isFullscreen ? (
                  <><Minimize2 className="h-3 w-3" /> {t("company.networkTab.exitFullscreen")}</>
                ) : (
                  <><Maximize2 className="h-3 w-3" /> {t("company.networkTab.fullscreen")}</>
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
              linkLabel={(link: { label?: string; is_active?: boolean; mandate_end?: string | null }) =>
                link.is_active === false
                  ? `${link.label || ""} \u2014 ${t("company.networkTab.endedMandate")}${link.mandate_end ? ` (${link.mandate_end})` : ""}`
                  : link.label || ""
              }
              linkColor={edgeColor}
              linkWidth={(link: { pct?: number | null; is_active?: boolean }) =>
                link.is_active === false ? 0.5 : link.pct != null ? 1.5 : 1
              }
              onNodeClick={handleNodeClick}
              linkCanvasObjectMode={() => "after"}
              linkCanvasObject={(
                link: { source?: any; target?: any; label?: string; pct?: number | null; relation?: string; is_active?: boolean },
                ctx: CanvasRenderingContext2D,
                globalScale: number
              ) => {
                // Draw a dashed segment over inactive (ended-mandate) edges so
                // they're visually distinct even at small scales — react-force-graph
                // doesn't expose lineDash directly, so we paint the line ourselves.
                if (link.is_active === false) {
                  const sx = typeof link.source === "object" ? link.source.x : 0;
                  const sy = typeof link.source === "object" ? link.source.y : 0;
                  const tx = typeof link.target === "object" ? link.target.x : 0;
                  const ty = typeof link.target === "object" ? link.target.y : 0;
                  ctx.save();
                  ctx.strokeStyle = "#cbd5e1";
                  ctx.lineWidth = 0.7;
                  ctx.setLineDash([3 / globalScale, 3 / globalScale]);
                  ctx.beginPath();
                  ctx.moveTo(sx, sy);
                  ctx.lineTo(tx, ty);
                  ctx.stroke();
                  ctx.restore();
                }

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

                ctx.fillStyle = edgeColor(link as { relation?: string; is_active?: boolean });
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
                const r = isCenter ? 12 : (node.depth != null ? Math.max(4, 8 - node.depth) : 5);
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
            {t("company.networkTab.footer")} &middot; {t("company.networkTab.nodesConnections").replace("{nodes}", String(data.nodes.length)).replace("{connections}", String(data.edges.length))}
            {data.depth_reached != null && ` \u00b7 Depth reached: ${data.depth_reached}`}
            {isFullscreen && ` \u00b7 ${t("company.networkTab.pressEsc")}`}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
