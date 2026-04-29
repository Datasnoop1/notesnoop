"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getDeepNetwork } from "@/lib/api";
import type {
  DeepNetworkResponse,
  DeepNetworkNode,
  DeepNetworkEdge,
} from "@/lib/api";
import { Loader2, AlertTriangle } from "lucide-react";

// d3 is loaded lazily from /d3.min.js (self-hosted in /public). The
// network-sunburst tab is the only consumer in the app today, so we keep
// it out of the main bundle.
declare global {
  // eslint-disable-next-line no-var
  var d3: any;
}

// ---------- types ---------------------------------------------------------

type ArmType = "directors" | "shareholders" | "subsidiaries";
type ChartScope = "governance" | "subsidiaries";

interface TreeNode {
  name: string;
  type?: "target" | ArmType | "leaf";
  arm?: ArmType;
  role?: string;
  pct?: string;
  country?: string;
  vat?: string;
  children?: TreeNode[];
}

interface Props {
  cbe: string;
  companyName: string;
  vat?: string | null;
}

// ---------- relation → arm mapping ---------------------------------------

const ARM_FOR_RELATION: Record<string, ArmType | null> = {
  administrator: "directors",
  shareholder: "shareholders",
  participating_interest: "subsidiaries",
};

const ARM_LABEL: Record<ArmType, string> = {
  directors: "Directors",
  shareholders: "Shareholders",
  subsidiaries: "Subsidiaries",
};

// ---------- tree builders -------------------------------------------------

function pickRoleAndPct(label: string | null | undefined): {
  role?: string;
  pct?: string;
} {
  if (!label) return {};
  const trimmed = String(label).trim();
  if (!trimmed) return {};
  if (/%/.test(trimmed)) return { pct: trimmed };
  return { role: trimmed };
}

function indexResponse(resp: DeepNetworkResponse) {
  // Edge direction conventions in the backend (`backend/routers/companies/network.py`):
  //   - administrator:          source = admin       → target = company
  //   - shareholder:            source = shareholder → target = owned-company
  //   - participating_interest: source = parent      → target = subsidiary
  // So for a target company:
  //   - Its directors    are the SOURCES of incoming `administrator` edges
  //   - Its shareholders are the SOURCES of incoming `shareholder` edges
  //   - Its subsidiaries are the TARGETS of outgoing `participating_interest` edges
  // Looking only at outgoing(root) for all three caused subsidiaries (which
  // ARE shareholders of themselves disclosed via root) to leak into the
  // shareholders arm.
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

function buildGovernanceTree(
  resp: DeepNetworkResponse,
  rootId: string,
  rootName: string,
  rootVat: string | null,
): TreeNode {
  const { nodeById, outgoing, incoming } = indexResponse(resp);

  const ARM_RELATION: Record<"directors" | "shareholders", string> = {
    directors: "administrator",
    shareholders: "shareholder",
  };

  // Directors / shareholders are SOURCES of incoming edges to root.
  const buckets: Record<"directors" | "shareholders", DeepNetworkEdge[]> = {
    directors: [],
    shareholders: [],
  };
  for (const e of incoming.get(rootId) ?? []) {
    if (e.relationship === "administrator") buckets.directors.push(e);
    else if (e.relationship === "shareholder") buckets.shareholders.push(e);
  }

  function makeContact(
    arm: "directors" | "shareholders",
    parentEdge: DeepNetworkEdge,
    excludeIds: Set<string>,
  ): TreeNode | null {
    // The contact is the SOURCE of the parent edge (admin → company,
    // shareholder → company), not the target.
    const contactId = parentEdge.source;
    const node = nodeById.get(contactId);
    if (!node) return null;
    const grandSeen = new Set(excludeIds);
    grandSeen.add(contactId);

    // Ring 3: contact's *other engagements of the same kind*.
    //   - For a director: their other boards (administrator out-edges)
    //   - For a shareholder: their other holdings (shareholder out-edges)
    // Mixing relationship types here would put a director's PI subsidiary
    // into the directors arm, which is misleading.
    const wantedRel = ARM_RELATION[arm];
    const grandchildren: TreeNode[] = [];
    for (const e of outgoing.get(contactId) ?? []) {
      if (e.relationship !== wantedRel) continue;
      if (grandSeen.has(e.target)) continue;
      grandSeen.add(e.target);
      const grand = nodeById.get(e.target);
      if (!grand) continue;
      grandchildren.push({
        name: grand.name,
        type: "leaf",
        arm,
        ...pickRoleAndPct(e.label),
      });
    }
    return {
      name: node.name,
      type: "leaf",
      arm,
      ...pickRoleAndPct(parentEdge.label),
      children: grandchildren.length ? grandchildren : undefined,
    };
  }

  function makeArm(
    arm: "directors" | "shareholders",
    edges: DeepNetworkEdge[],
  ): TreeNode {
    const seen = new Set<string>();
    const children: TreeNode[] = [];
    const exclude = new Set<string>([rootId]);
    for (const e of edges) {
      // dedupe by SOURCE (the contact node) since incoming edges all share target=root
      if (seen.has(e.source)) continue;
      seen.add(e.source);
      const c = makeContact(arm, e, exclude);
      if (c) children.push(c);
    }
    return { name: ARM_LABEL[arm], type: arm, arm, children };
  }

  return {
    name: rootName,
    type: "target",
    vat: rootVat || undefined,
    children: [
      makeArm("directors", buckets.directors),
      makeArm("shareholders", buckets.shareholders),
    ],
  };
}

function buildSubsidiariesTree(
  resp: DeepNetworkResponse,
  rootId: string,
  rootName: string,
  rootVat: string | null,
): TreeNode {
  const { nodeById, outgoing } = indexResponse(resp);
  const MAX_DEPTH = 3;

  function buildLevel(
    currentId: string,
    visited: Set<string>,
    depth: number,
  ): TreeNode[] {
    if (depth > MAX_DEPTH) return [];
    const result: TreeNode[] = [];
    const seen = new Set<string>();
    for (const e of outgoing.get(currentId) ?? []) {
      if (e.relationship !== "participating_interest") continue;
      if (visited.has(e.target) || seen.has(e.target)) continue;
      seen.add(e.target);
      const node = nodeById.get(e.target);
      if (!node) continue;
      const newVisited = new Set(visited);
      newVisited.add(e.target);
      result.push({
        name: node.name,
        type: "leaf",
        arm: "subsidiaries",
        ...pickRoleAndPct(e.label),
        children:
          depth < MAX_DEPTH
            ? buildLevel(node.id, newVisited, depth + 1)
            : undefined,
      });
    }
    return result;
  }

  const visited = new Set([rootId]);
  return {
    name: rootName,
    type: "target",
    vat: rootVat || undefined,
    children: buildLevel(rootId, visited, 1),
  };
}

// ---------- d3 loader -----------------------------------------------------

function loadD3(): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  if ((window as any).d3) return Promise.resolve();
  const existing = document.querySelector(
    'script[data-d3-loader="self-hosted"]',
  );
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("d3 load")));
    });
  }
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/d3.min.js";
    s.async = true;
    s.dataset.d3Loader = "self-hosted";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("d3 load"));
    document.head.appendChild(s);
  });
}

// ---------- panel info shape ---------------------------------------------

interface PanelInfo {
  scope: ChartScope;
  depth: number;
  name: string;
  arm: ArmType | null;
  role?: string;
  pct?: string;
  country?: string;
  vat?: string;
  parentName?: string;
  pathNames?: string[];
  childCount: number;
  totalStakeDisclosed?: number;
  // Root-level summary (governance only)
  govSummary?: {
    directors: number;
    shareholders: number;
    secondDeg: number;
  };
  // Root-level summary (subsidiaries only)
  subsSummary?: {
    direct: number;
    second: number;
    third: number;
  };
}

function nodeToPanelInfo(d: any, root: any, scope: ChartScope): PanelInfo {
  const data: TreeNode = d.data;
  const arm = (data.arm ?? data.type) as ArmType | undefined;
  const parentData: TreeNode | undefined = d.parent?.data;
  const grandData: TreeNode | undefined = d.parent?.parent?.data;

  const info: PanelInfo = {
    scope,
    depth: d.depth,
    name: data.name,
    arm: arm && (["directors", "shareholders", "subsidiaries"] as const).includes(arm as any)
      ? (arm as ArmType)
      : null,
    role: data.role,
    pct: data.pct,
    country: data.country,
    vat: data.vat,
    parentName: parentData?.name,
    childCount: d.children ? d.children.length : 0,
  };

  if (d.depth === 0) {
    if (scope === "governance") {
      let dirs = 0;
      let shrs = 0;
      let secondDeg = 0;
      (d.children || []).forEach((armNode: any) => {
        const t = armNode.data.type as ArmType;
        const ct = (armNode.children || []).length;
        if (t === "directors") dirs = ct;
        if (t === "shareholders") shrs = ct;
        (armNode.children || []).forEach((c: any) => {
          secondDeg += (c.children || []).length;
        });
      });
      info.govSummary = { directors: dirs, shareholders: shrs, secondDeg };
    } else {
      const direct = (d.children || []).length;
      let second = 0;
      let third = 0;
      (d.children || []).forEach((c: any) => {
        second += (c.children || []).length;
        (c.children || []).forEach((cc: any) => {
          third += (cc.children || []).length;
        });
      });
      info.subsSummary = { direct, second, third };
    }
  } else if (
    scope === "governance" &&
    d.depth === 1 &&
    info.arm === "shareholders"
  ) {
    let total = 0;
    (d.children || []).forEach((c: any) => {
      const m = (c.data.pct || "").match(/(\d+(?:\.\d+)?)/);
      if (m) total += parseFloat(m[1]);
    });
    info.totalStakeDisclosed = total;
  }

  if (scope === "governance" && d.depth === 3) {
    info.pathNames = [
      root.data.name,
      grandData?.name || "",
      parentData?.name || "",
      data.name,
    ];
  }
  if (scope === "subsidiaries" && d.depth === 3) {
    info.pathNames = [
      root.data.name,
      grandData?.name || "",
      parentData?.name || "",
      data.name,
    ];
  }
  return info;
}

const COLOUR_GOV: Record<"directors" | "shareholders", { base: string; light: string; lighter: string }> = {
  directors:    { base: "#059669", light: "#d1fae5", lighter: "#ecfdf5" },
  shareholders: { base: "#d97706", light: "#fef3c7", lighter: "#fffbeb" },
};
const COLOUR_SUBS = { base: "#0284c7", light: "#7dd3fc", lighter: "#bae6fd", lightest: "#e0f2fe" };

// ---------- d3 sunburst renderer -----------------------------------------

interface RenderHandlers {
  onHover: (info: PanelInfo) => void;
  onLeave: () => void;
  onClick: (info: PanelInfo) => void;
}

function renderSunburst(
  container: HTMLElement,
  tree: TreeNode,
  scope: ChartScope,
  handlers: RenderHandlers,
): () => void {
  const d3 = (window as any).d3;
  if (!d3) return () => {};

  container.innerHTML = "";

  const width = 720;
  const height = 720;
  const radius = width / 2;

  const svg = d3
    .select(container)
    .append("svg")
    .attr("viewBox", `0 0 ${width} ${height}`)
    .attr("preserveAspectRatio", "xMidYMid meet")
    .style("width", "100%")
    .style("height", "auto")
    .style("max-width", `${width}px`)
    .style("display", "block")
    .style("margin", "0 auto");

  const g = svg
    .append("g")
    .attr("transform", `translate(${width / 2},${height / 2})`);

  const root = d3.hierarchy(tree).sum(() => 1).sort((a: any, b: any) => b.value - a.value);
  d3.partition().size([2 * Math.PI, radius])(root);

  function getArm(d: any): "directors" | "shareholders" | null {
    if (scope !== "governance") return null;
    let n = d;
    while (n.parent && n.depth > 1) n = n.parent;
    if (n.depth !== 1) return null;
    const t = n.data.type as ArmType;
    return t === "directors" || t === "shareholders" ? t : null;
  }
  function nodeColour(d: any): string {
    if (d.depth === 0) return "#ffffff";
    if (scope === "governance") {
      const arm = getArm(d);
      if (!arm) return "#f1f5f9";
      const c = COLOUR_GOV[arm];
      if (d.depth === 1) return c.base;
      if (d.depth === 2) return c.light;
      return c.lighter;
    }
    // subsidiaries: depth = ownership depth from target
    if (d.depth === 1) return COLOUR_SUBS.base;
    if (d.depth === 2) return COLOUR_SUBS.light;
    if (d.depth === 3) return COLOUR_SUBS.lighter;
    return COLOUR_SUBS.lightest;
  }
  function nodeStroke(d: any): string {
    if (d.depth === 0) return "#e2e8f0";
    if (scope === "governance") {
      const arm = getArm(d);
      return arm ? COLOUR_GOV[arm].base : "#e2e8f0";
    }
    return COLOUR_SUBS.base;
  }

  const arc = d3
    .arc()
    .startAngle((d: any) => d.x0)
    .endAngle((d: any) => d.x1)
    .padAngle(0.003)
    .padRadius(radius / 2)
    .innerRadius((d: any) => d.y0)
    .outerRadius((d: any) => d.y1 - 1);

  const path = g
    .selectAll("path")
    .data(root.descendants().filter((d: any) => d.depth))
    .join("path")
    .attr("d", arc)
    .attr("fill", nodeColour)
    .attr("stroke", nodeStroke)
    .attr("stroke-width", (d: any) => (d.depth === 1 ? 1.5 : 1))
    .style("cursor", "pointer")
    .style("transition", "filter 0.15s ease")
    .on("mouseenter", function (this: any, _e: any, d: any) {
      d3.select(this).style("filter", "brightness(1.08)");
      handlers.onHover(nodeToPanelInfo(d, root, scope));
    })
    .on("mouseleave", function (this: any) {
      d3.select(this).style("filter", "none");
      handlers.onLeave();
    })
    .on("click", function (_e: any, d: any) {
      handlers.onClick(nodeToPanelInfo(d, root, scope));
      clicked(d);
    });

  // ---- slice labels --------------------------------------------------
  const minArcLength = 22;
  const arcLengthPx = (d: any) =>
    Math.max(0, ((d.y0 + d.y1) / 2) * (d.x1 - d.x0));
  const pxPerChar = (depth: number) =>
    depth === 1 ? 6.8 : depth === 2 ? 6.0 : 5.4;
  const truncate = (str: string, n: number) =>
    str.length > n ? str.slice(0, n - 1) + "…" : str;

  const labelText = (d: any): string => {
    const arcL = arcLengthPx(d);
    if (arcL < minArcLength) return "";
    const maxChars = Math.max(3, Math.floor(arcL / pxPerChar(d.depth)) - 1);
    let txt = d.data.name as string;
    if (scope === "governance" && d.depth === 1 && d.children) {
      txt = `${txt}  ·  ${d.children.length}`;
    } else if (
      (scope === "governance" && d.depth >= 2) ||
      (scope === "subsidiaries" && d.depth >= 1)
    ) {
      const meta = (d.data.role as string) || (d.data.pct as string);
      if (meta) txt = `${txt}  ·  ${meta}`;
    }
    return truncate(txt, maxChars);
  };
  const labelTransform = (d: any): string => {
    const xDeg = (((d.x0 + d.x1) / 2) * 180) / Math.PI;
    const yMid = (d.y0 + d.y1) / 2;
    return `rotate(${xDeg - 90}) translate(${yMid},0) rotate(${xDeg < 180 ? 0 : 180})`;
  };

  // For subsidiaries chart: white text on the dark base ring, dark on lighter.
  const labelFill = (d: any): string => {
    if (scope === "governance") {
      return d.depth === 1 ? "#ffffff" : "#0f172a";
    }
    return d.depth === 1 ? "#ffffff" : "#0f172a";
  };

  const label = g
    .selectAll("text.slice-label")
    .data(root.descendants().filter((d: any) => d.depth >= 1 && d.depth <= 3))
    .join("text")
    .attr("class", "slice-label")
    .attr("transform", labelTransform)
    .attr("dy", "0.32em")
    .style("font-family", "var(--font-geist), system-ui, -apple-system, sans-serif")
    .style("font-size", (d: any) =>
      d.depth === 1 ? "12px" : d.depth === 2 ? "11px" : "10px",
    )
    .style("font-weight", (d: any) =>
      d.depth === 1 ? 600 : d.depth === 2 ? 500 : 400,
    )
    .style("fill", labelFill)
    .style("text-anchor", "middle")
    .style("pointer-events", "none")
    .style("user-select", "none")
    .text(labelText);

  // ---- centre label -------------------------------------------------
  const centreGroup = g.append("g");
  const centreLabel = centreGroup
    .append("text")
    .attr("dy", "-0.3em")
    .attr("text-anchor", "middle")
    .style("font-family", "var(--font-geist), system-ui, sans-serif")
    .style("font-size", "13px")
    .style("font-weight", 600)
    .style("fill", "#0f172a")
    .style("pointer-events", "none")
    .text(truncate(root.data.name, 20));
  const centreSub = centreGroup
    .append("text")
    .attr("dy", "1.1em")
    .attr("text-anchor", "middle")
    .style("font-family", "var(--font-geist-mono), monospace")
    .style("font-size", "11px")
    .style("fill", "#64748b")
    .style("pointer-events", "none")
    .text((root.data.vat as string) || "");

  // Invisible centre-circle for click-to-zoom-out
  g.append("circle")
    .attr("r", root.y0 + 4)
    .attr("fill", "transparent")
    .style("cursor", "pointer")
    .on("click", () => {
      handlers.onClick(nodeToPanelInfo(root, root, scope));
      clicked(root);
    });

  // ---- zoom ----------------------------------------------------------
  root.each((d: any) => {
    d.current = { x0: d.x0, x1: d.x1, y0: d.y0, y1: d.y1 };
  });

  function clicked(p: any) {
    if (!p) p = root;
    const name = p === root ? root.data.name : p.data.name;
    const sub =
      p === root
        ? (root.data.vat as string) || ""
        : (p.data.role as string) || (p.data.pct as string) || "";
    centreLabel.text(truncate(name, 20));
    centreSub.text(sub);

    root.each((d: any) => {
      d.target = {
        x0:
          Math.max(0, Math.min(1, (d.x0 - p.x0) / (p.x1 - p.x0))) *
          2 *
          Math.PI,
        x1:
          Math.max(0, Math.min(1, (d.x1 - p.x0) / (p.x1 - p.x0))) *
          2 *
          Math.PI,
        y0: Math.max(0, d.y0 - p.depth),
        y1: Math.max(0, d.y1 - p.depth),
      };
    });

    const t = g.transition().duration(550).ease(d3.easeCubicOut);
    path.transition(t).attrTween("d", (d: any) => () => arc(d.current));
    label
      .attr("transform", (d: any) => labelTransform(d.target))
      .text((d: any) => labelText(d.target));

    root.each((d: any) => {
      d.current = d.target;
    });
  }

  return () => {
    container.innerHTML = "";
  };
}

// ---------- React component -----------------------------------------------

const ARM_PILL_CLS: Record<ArmType, string> = {
  directors:    "bg-emerald-50 border-emerald-200 text-emerald-800",
  shareholders: "bg-amber-50 border-amber-200 text-amber-800",
  subsidiaries: "bg-sky-50 border-sky-200 text-sky-800",
};

function DetailRow({ dt, dd, mono }: { dt: string; dd: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3 items-baseline pb-2 border-b border-dashed border-[#E2E8F2] last:border-b-0 last:pb-0">
      <dt className="text-[12px] text-[#64748B] font-medium">{dt}</dt>
      <dd
        className={`text-[13.5px] text-[#0F172A] font-medium text-right ${mono ? "font-mono text-[12.5px]" : ""}`}
      >
        {dd}
      </dd>
    </div>
  );
}

function onwardNoun(arm: ArmType, n: number): string {
  if (arm === "directors")    return n === 1 ? "other board" : "other boards";
  if (arm === "subsidiaries") return n === 1 ? "sub-subsidiary" : "sub-subsidiaries";
  return n === 1 ? "further holding" : "further holdings";
}

function eyebrowFor(info: PanelInfo): string {
  if (info.depth === 0) {
    return info.scope === "governance"
      ? "Target · governance view"
      : "Target · subsidiary tree";
  }
  if (info.scope === "governance") {
    if (info.depth === 1) return "Relationship type";
    if (info.depth === 2)
      return `${info.arm ? ARM_LABEL[info.arm] : ""} of target`;
    if (info.depth === 3 && info.parentName) return `via ${info.parentName}`;
  } else {
    if (info.depth === 1) return "Direct subsidiary";
    if (info.depth === 2) return `Sub-subsidiary via ${info.parentName ?? ""}`;
    if (info.depth === 3) return `3rd-degree subsidiary via ${info.parentName ?? ""}`;
  }
  return "";
}

function DetailPanel({
  info,
  truncated,
  depthReached,
}: {
  info: PanelInfo | null;
  truncated: boolean;
  depthReached: number;
}) {
  if (!info) {
    return (
      <div className="rounded-lg border border-[#E2E8F2] bg-[#F8FAFC] p-5 text-sm text-[#94A3B8] text-center">
        Hover any slice in either chart to inspect it.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[#E2E8F2] bg-[#F8FAFC] p-5 text-sm text-[#475569]">
      <div className="grid grid-cols-1 md:grid-cols-[minmax(220px,1fr)_minmax(0,2fr)] gap-5 items-start">
        <div className="flex flex-col">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B] mb-1.5">
            {eyebrowFor(info)}
          </div>
          <div className="text-[17px] font-semibold text-[#0F172A] leading-tight break-words">
            {info.name}
          </div>
          <div className="flex flex-wrap gap-1.5 mt-2.5">
            {info.depth > 0 && info.arm && (
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-mono border ${ARM_PILL_CLS[info.arm]}`}
              >
                Ring {info.depth}
              </span>
            )}
            {info.depth === 0 && info.vat && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-mono border bg-white border-[#E2E8F2] text-[#475569]">
                {info.vat}
              </span>
            )}
            {truncated && info.depth === 0 && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-mono border bg-white border-rose-200 text-rose-700">
                truncated · depth {depthReached}
              </span>
            )}
          </div>
        </div>

        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2.5 min-w-0">
          {info.depth === 0 && info.govSummary && (
            <>
              <DetailRow dt="Direct directors" dd={String(info.govSummary.directors)} />
              <DetailRow dt="Direct shareholders" dd={String(info.govSummary.shareholders)} />
              <DetailRow dt="Second-degree links" dd={String(info.govSummary.secondDeg)} />
            </>
          )}
          {info.depth === 0 && info.subsSummary && (
            <>
              <DetailRow dt="Direct subsidiaries" dd={String(info.subsSummary.direct)} />
              <DetailRow dt="Sub-subsidiaries" dd={String(info.subsSummary.second)} />
              <DetailRow dt="3rd-degree subsidiaries" dd={String(info.subsSummary.third)} />
            </>
          )}
          {info.depth === 1 && info.scope === "governance" && (
            <>
              <DetailRow dt="Direct count" dd={String(info.childCount)} />
              {info.arm === "shareholders" && info.totalStakeDisclosed != null && (
                <DetailRow
                  dt="Total stake disclosed"
                  dd={`${info.totalStakeDisclosed}%`}
                  mono
                />
              )}
            </>
          )}
          {info.depth === 1 && info.scope === "subsidiaries" && (
            <>
              {info.pct && <DetailRow dt="Stake" dd={info.pct} mono />}
              {info.country && <DetailRow dt="Country" dd={info.country} mono />}
              {info.childCount > 0 && (
                <DetailRow dt="Onward subsidiaries" dd={String(info.childCount)} />
              )}
            </>
          )}
          {info.depth >= 2 && (
            <>
              {info.role    && <DetailRow dt="Role"    dd={info.role} />}
              {info.pct     && <DetailRow dt="Stake"   dd={info.pct} mono />}
              {info.country && <DetailRow dt="Country" dd={info.country} mono />}
              {info.scope === "governance" && info.depth === 2 && info.childCount > 0 && info.arm && (
                <DetailRow
                  dt="Onward links"
                  dd={`${info.childCount} ${onwardNoun(info.arm, info.childCount)}`}
                />
              )}
              {info.scope === "subsidiaries" && info.childCount > 0 && (
                <DetailRow
                  dt="Onward subsidiaries"
                  dd={String(info.childCount)}
                />
              )}
              {info.depth === 3 && info.pathNames && (
                <div className="col-span-full pt-1.5 border-t border-dashed border-[#E2E8F2]">
                  <dt className="text-[12px] text-[#64748B] font-medium">Network path</dt>
                  <dd className="text-[11.5px] text-[#0F172A] leading-snug font-mono mt-0.5">
                    {info.pathNames.join(" → ")}
                  </dd>
                </div>
              )}
              {!info.role && !info.pct && !info.country && info.depth === 3 && !info.pathNames && (
                <DetailRow dt="No additional metadata" dd="—" />
              )}
            </>
          )}
        </dl>
      </div>
      <div className="mt-4 pt-3 border-t border-[#E2E8F2] text-[12px] text-[#64748B] leading-snug">
        Hover any slice to inspect. Click to zoom in; click the centre to zoom out.
      </div>
    </div>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="inline-block h-[12px] w-[12px] rounded-sm"
        style={{ background: swatch }}
      />
      {label}
    </span>
  );
}

export default function NetworkSunburst({ cbe, companyName, vat }: Props) {
  const [resp, setResp] = useState<DeepNetworkResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [depth, setDepth] = useState(2);
  const [historical, setHistorical] = useState(false);
  const [d3Ready, setD3Ready] = useState(false);
  const [hovered, setHovered] = useState<PanelInfo | null>(null);
  const [focus, setFocus] = useState<PanelInfo | null>(null);
  const govRef = useRef<HTMLDivElement>(null);
  const subsRef = useRef<HTMLDivElement>(null);

  // 1) Lazy-load d3
  useEffect(() => {
    let cancelled = false;
    loadD3()
      .then(() => {
        if (!cancelled) setD3Ready(true);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load chart library.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 2) Fetch network on cbe / depth / historical changes
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

  // 3) Build the two trees from the same response
  const govTree = useMemo(() => {
    if (!resp) return null;
    return buildGovernanceTree(resp, cbe, companyName, vat ?? null);
  }, [resp, cbe, companyName, vat]);
  const subsTree = useMemo(() => {
    if (!resp) return null;
    return buildSubsidiariesTree(resp, cbe, companyName, vat ?? null);
  }, [resp, cbe, companyName, vat]);

  // Reset hover/focus when trees rebuild
  useEffect(() => {
    setHovered(null);
    setFocus(null);
  }, [govTree, subsTree]);

  const govEmpty =
    !!govTree &&
    (govTree.children ?? []).every(
      (arm) => !arm.children || arm.children.length === 0,
    );
  const subsEmpty =
    !!subsTree && !(subsTree.children && subsTree.children.length > 0);

  // 4) Render charts
  useEffect(() => {
    if (!d3Ready || !govTree || !govRef.current || govEmpty) return;
    return renderSunburst(govRef.current, govTree, "governance", {
      onHover: (info) => setHovered(info),
      onLeave: () => setHovered(null),
      onClick: (info) => setFocus(info),
    });
  }, [d3Ready, govTree, govEmpty]);

  useEffect(() => {
    if (!d3Ready || !subsTree || !subsRef.current || subsEmpty) return;
    return renderSunburst(subsRef.current, subsTree, "subsidiaries", {
      onHover: (info) => setHovered(info),
      onLeave: () => setHovered(null),
      onClick: (info) => setFocus(info),
    });
  }, [d3Ready, subsTree, subsEmpty]);

  // Default panel info (no hover / no focus): show whichever scope the user
  // last interacted with — fall back to a synthetic "governance overview"
  // so the panel isn't empty on first load.
  const rootGovPanel: PanelInfo | null = useMemo(() => {
    if (!govTree) return null;
    let dirs = 0;
    let shrs = 0;
    let secondDeg = 0;
    (govTree.children ?? []).forEach((arm) => {
      const t = arm.type as ArmType;
      const ct = (arm.children || []).length;
      if (t === "directors") dirs = ct;
      if (t === "shareholders") shrs = ct;
      (arm.children || []).forEach((c) => {
        secondDeg += (c.children || []).length;
      });
    });
    return {
      scope: "governance",
      depth: 0,
      name: govTree.name,
      arm: null,
      vat: govTree.vat,
      childCount: (govTree.children ?? []).length,
      govSummary: { directors: dirs, shareholders: shrs, secondDeg },
    };
  }, [govTree]);

  const detailInfo = hovered ?? focus ?? rootGovPanel;

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
        {resp?.truncated && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-rose-700 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-full">
            <AlertTriangle className="h-3 w-3" />
            Result truncated · reached depth {resp.depth_reached}
          </span>
        )}
      </div>

      {error && (
        <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-[13px] text-rose-800 mb-3">
          {error}
        </div>
      )}

      {(loading || !d3Ready) && !error && (
        <div className="flex items-center justify-center py-16 text-sm text-[#64748B]">
          <Loader2 className="h-4 w-4 animate-spin mr-2" />
          Building network sunbursts…
        </div>
      )}

      {!loading && !error && govTree && subsTree && (
        <>
          {govEmpty && subsEmpty ? (
            <div className="rounded border border-[#E2E8F2] bg-[#F8FAFC] px-4 py-10 text-center text-sm text-[#64748B]">
              No directors, shareholders or subsidiaries found for this company.
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B] mb-2">
                    Ownership &amp; governance
                  </div>
                  {govEmpty ? (
                    <div className="rounded border border-dashed border-[#E2E8F2] bg-[#F8FAFC] py-12 text-center text-[13px] text-[#94A3B8]">
                      No directors or shareholders disclosed.
                    </div>
                  ) : (
                    <>
                      <div ref={govRef} className="min-h-[420px]" />
                      <div className="flex flex-wrap gap-x-5 gap-y-2 mt-3 text-[12.5px] text-[#64748B]">
                        <Legend swatch="#059669" label="Directors" />
                        <Legend swatch="#d97706" label="Shareholders" />
                      </div>
                      <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2 text-[11.5px] text-[#64748B]">
                        <span><strong className="text-[#0F172A] font-semibold mr-1">R1</strong>relationship type</span>
                        <span><strong className="text-[#0F172A] font-semibold mr-1">R2</strong>direct contact</span>
                        <span><strong className="text-[#0F172A] font-semibold mr-1">R3</strong>their other engagements</span>
                      </div>
                    </>
                  )}
                </div>
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B] mb-2">
                    Subsidiaries
                  </div>
                  {subsEmpty ? (
                    <div className="rounded border border-dashed border-[#E2E8F2] bg-[#F8FAFC] py-12 text-center text-[13px] text-[#94A3B8]">
                      No participating interests on file.
                    </div>
                  ) : (
                    <>
                      <div ref={subsRef} className="min-h-[420px]" />
                      <div className="flex flex-wrap gap-x-5 gap-y-1 mt-3 text-[11.5px] text-[#64748B]">
                        <span><strong className="text-[#0F172A] font-semibold mr-1">R1</strong>direct subsidiary</span>
                        <span><strong className="text-[#0F172A] font-semibold mr-1">R2</strong>sub-subsidiary</span>
                        <span><strong className="text-[#0F172A] font-semibold mr-1">R3</strong>3rd-degree subsidiary</span>
                      </div>
                    </>
                  )}
                </div>
              </div>

              <div className="mt-6">
                <DetailPanel
                  info={detailInfo}
                  truncated={resp?.truncated ?? false}
                  depthReached={resp?.depth_reached ?? 0}
                />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
