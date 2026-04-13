"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { getCompanyNetwork } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

interface NetworkNode {
  id: string;
  label: string;
  type: string;
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
}

interface Props {
  cbe: string;
  companyName: string;
}

export default function NetworkGraph({ cbe, companyName }: Props) {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const [data, setData] = useState<NetworkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [depth, setDepth] = useState(2);
  const [ForceGraph, setForceGraph] = useState<typeof import("react-force-graph-2d").default | null>(null);

  // Dynamic import of react-force-graph-2d (it uses canvas, SSR-incompatible)
  useEffect(() => {
    import("react-force-graph-2d").then((mod) => {
      setForceGraph(() => mod.default);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    getCompanyNetwork(cbe, depth)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [cbe, depth]);

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

  // Color nodes by type
  const nodeColor = (node: { type?: string; id?: string }) => {
    if (node.id === cbe) return "#4f46e5"; // indigo — current company
    switch (node.type) {
      case "company": return "#6366f1";
      case "shareholder": return "#059669";
      case "subsidiary": return "#d97706";
      case "admin": return "#dc2626";
      default: return "#94a3b8";
    }
  };

  const graphData = {
    nodes: data.nodes.map((n) => ({
      id: n.id,
      label: n.label,
      type: n.type,
      val: n.id === cbe ? 3 : 1,
    })),
    links: data.edges.map((e) => ({
      source: e.source,
      target: e.target,
      label: e.pct ? `${e.pct}%` : e.relation,
    })),
  };

  return (
    <Card>
      <CardContent className="pt-4 pb-2">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">
            Corporate Network
          </h3>
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
          </div>
        </div>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs text-slate-500 font-medium">Depth:</span>
          {[1, 2, 3].map(d => (
            <button
              key={d}
              onClick={() => setDepth(d)}
              className={`px-2.5 py-1 text-xs rounded-md font-medium transition-colors ${
                depth === d
                  ? "bg-indigo-600 text-white"
                  : "bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
              }`}
            >
              {d === 1 ? "1st" : d === 2 ? "2nd" : "3rd"} degree
            </button>
          ))}
          <button
            onClick={() => {
              if (graphRef.current) {
                graphRef.current.zoomToFit(400);
              }
            }}
            className="ml-auto px-2.5 py-1 text-xs rounded-md font-medium bg-white text-slate-600 border border-slate-200 hover:bg-slate-50"
          >
            Reset view
          </button>
        </div>
        <div
          ref={containerRef}
          className="border border-slate-200 rounded-lg overflow-hidden bg-white"
          style={{ height: 400 }}
        >
          <ForceGraph
            ref={graphRef}
            graphData={graphData}
            width={containerRef.current?.clientWidth || 800}
            height={400}
            nodeColor={nodeColor}
            nodeLabel={(node: { label?: string }) => node.label || ""}
            nodeRelSize={6}
            linkDirectionalArrowLength={4}
            linkDirectionalArrowRelPos={1}
            linkLabel={(link: { label?: string }) => link.label || ""}
            linkColor={() => "#cbd5e1"}
            onNodeClick={handleNodeClick}
            nodeCanvasObject={(
              node: { x?: number; y?: number; id?: string; label?: string; type?: string },
              ctx: CanvasRenderingContext2D,
              globalScale: number
            ) => {
              const x = node.x || 0;
              const y = node.y || 0;
              const r = node.id === cbe ? 8 : 5;
              const color = nodeColor(node);

              // Circle
              ctx.beginPath();
              ctx.arc(x, y, r, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
              ctx.strokeStyle = node.id === cbe ? "#312e81" : "#e2e8f0";
              ctx.lineWidth = node.id === cbe ? 2 : 1;
              ctx.stroke();

              // Label
              if (globalScale > 0.7) {
                const label = (node.label || "").substring(0, 25);
                const fontSize = Math.min(12 / globalScale, 14);
                ctx.font = `${node.id === cbe ? "bold " : ""}${fontSize}px Inter, sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                ctx.fillStyle = "#334155";
                ctx.fillText(label, x, y + r + 2);
              }
            }}
            cooldownTicks={100}
          />
        </div>
        <p className="text-[11px] text-slate-400 mt-2 text-center">
          Click a node to navigate to that company
        </p>
      </CardContent>
    </Card>
  );
}
