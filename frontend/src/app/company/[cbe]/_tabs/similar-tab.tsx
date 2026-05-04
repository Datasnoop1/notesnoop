"use client";

import React, { useMemo, useState, useEffect } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Sparkles, Loader2, Scale, RefreshCw, Heart, CheckSquare, Square, FolderPlus, ChevronDown, ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";
import { fmtEur, fmtNumber } from "@/lib/format";
import { useRouter } from "next/navigation";
import { getAiSimilarCompanies } from "@/lib/api";

/* ---------- Types ---------- */

interface AiSimilarCompany {
  enterprise_number: string;
  name: string;
  city: string;
  zipcode?: string | null;
  nace_code?: string | null;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  fiscal_year: number;
  ai_reason?: string;
  ai_reason_sections?: {
    activity?: string;
    size?: string;
    geography?: string;
  };
  signals?: {
    nace_match?: string;
    revenue_ratio?: number | null;
    activity_anchor?: string | null;
    geo_match?: string;
  };
}

interface SimilarTabProps {
  cbe: string;
}

const DEFAULT_LIMIT = 10;
// Bumped 30 -> 100 (2026-05-04) so users can browse the full exhaustive
// peer list. Backend supports up to 100 since PR #57.
const EXPANDED_LIMIT = 100;

/* ---------- Sort state ---------- */

type SortKey = "rank" | "name" | "zipcode" | "revenue" | "ebitda" | "fte_total";
type SortDir = "asc" | "desc";

interface SortState {
  key: SortKey;
  dir: SortDir;
}

function compareForSort(
  a: AiSimilarCompany,
  b: AiSimilarCompany,
  state: SortState,
  rankIndex: Map<string, number>,
): number {
  const dirMul = state.dir === "asc" ? 1 : -1;
  if (state.key === "rank") {
    return ((rankIndex.get(a.enterprise_number) ?? 0) - (rankIndex.get(b.enterprise_number) ?? 0)) * dirMul;
  }
  // For non-rank columns: nulls always sort last regardless of direction.
  // Otherwise compare by value.
  const av = a[state.key as keyof AiSimilarCompany] as string | number | null | undefined;
  const bv = b[state.key as keyof AiSimilarCompany] as string | number | null | undefined;
  const aMissing = av === null || av === undefined || av === "";
  const bMissing = bv === null || bv === undefined || bv === "";
  if (aMissing && bMissing) {
    return ((rankIndex.get(a.enterprise_number) ?? 0) - (rankIndex.get(b.enterprise_number) ?? 0));
  }
  if (aMissing) return 1;
  if (bMissing) return -1;
  if (typeof av === "number" && typeof bv === "number") {
    return (av - bv) * dirMul;
  }
  const as = String(av).toLowerCase();
  const bs = String(bv).toLowerCase();
  if (as < bs) return -1 * dirMul;
  if (as > bs) return 1 * dirMul;
  return 0;
}

/* ---------- Helpers ---------- */

const REASON_PARTS = [
  { key: "activity", label: "Activity" },
  { key: "size", label: "Size" },
  { key: "geography", label: "Geography" },
] as const;

function splitReason(
  reason?: string,
  sections?: AiSimilarCompany["ai_reason_sections"],
): Array<{ label: string; text: string }> {
  const structured = REASON_PARTS.flatMap(({ key, label }) => {
    const text = sections?.[key]?.trim();
    return text ? [{ label, text }] : [];
  });
  if (structured.length > 0) return structured;
  if (!reason) return [];

  const normalized = reason.replace(/\s+/g, " ").trim();
  const labelRegex = /(Activity|Size|Geography):/gi;
  const matches = Array.from(normalized.matchAll(labelRegex));
  if (matches.length === 0) {
    return [{ label: "Why", text: normalized }];
  }
  return matches
    .map((match, index) => {
      const start = (match.index ?? 0) + match[0].length;
      const end = index + 1 < matches.length
        ? (matches[index + 1].index ?? normalized.length)
        : normalized.length;
      const text = normalized
        .slice(start, end)
        .replace(/^[\s|.;:-]+|[\s|.;:-]+$/g, "")
        .trim();
      return {
        label: match[1][0].toUpperCase() + match[1].slice(1).toLowerCase(),
        text,
      };
    })
    .filter((part) => part.text.length > 0);
}

function fallbackReasonParts(company: AiSimilarCompany): Array<{ label: string; text: string }> {
  const signals = company.signals;
  if (!signals) return [];

  const parts: Array<{ label: string; text: string }> = [];

  const activityAnchor = signals.activity_anchor?.trim();
  if (activityAnchor) {
    parts.push({
      label: "Activity",
      text: `Business overlap around ${activityAnchor}`,
    });
  } else if (signals.nace_match && signals.nace_match !== "none") {
    const naceLabel =
      signals.nace_match === "exact" ? "Exact activity-code match" :
      signals.nace_match === "class" ? "Same 3-digit activity class" :
      signals.nace_match === "group" ? "Same 2-digit activity group" :
      "";
    if (naceLabel) {
      parts.push({ label: "Activity", text: naceLabel });
    }
  }

  const revenueRatio = signals.revenue_ratio;
  if (typeof revenueRatio === "number" && Number.isFinite(revenueRatio) && revenueRatio > 0) {
    const sizeText =
      revenueRatio >= 0.85 && revenueRatio <= 1.15
        ? "Revenue is very close to the target"
        : revenueRatio >= 0.6 && revenueRatio <= 1.4
          ? "Revenue is in a comparable range"
          : revenueRatio < 1
            ? `Revenue is smaller at about ${revenueRatio.toFixed(1)}x of target`
            : `Revenue is larger at about ${revenueRatio.toFixed(1)}x of target`;
    parts.push({ label: "Size", text: sizeText });
  }

  const city = company.city?.trim();
  const geoText =
    signals.geo_match === "same_city"
      ? `Same city${city ? `: ${city}` : ""}`
      : signals.geo_match === "same_province"
        ? `Same province area${city ? `: ${city}` : ""}`
        : city
          ? `Different geography: ${city}`
          : "Geography is a secondary factor";
  parts.push({ label: "Geography", text: geoText });

  return parts;
}

/* ---------- Component ---------- */

export function SimilarTab({ cbe }: SimilarTabProps) {
  const router = useRouter();
  const [companies, setCompanies] = useState<AiSimilarCompany[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addingFavs, setAddingFavs] = useState(false);
  const [showProjectMenu, setShowProjectMenu] = useState(false);
  const [projects, setProjects] = useState<{ id: number; name: string }[]>([]);
  const [newProjectName, setNewProjectName] = useState("");
  const [addingToProject, setAddingToProject] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [noMoreAvailable, setNoMoreAvailable] = useState(false);
  const [sortState, setSortState] = useState<SortState>({ key: "rank", dir: "asc" });

  // Capture each company's incoming AI rank so we can fall back to it
  // for tiebreakers and as the "rank" sort option. Reset whenever the
  // companies list itself changes.
  const rankIndex = useMemo(() => {
    const m = new Map<string, number>();
    companies.forEach((c, i) => m.set(c.enterprise_number, i));
    return m;
  }, [companies]);

  const sortedCompanies = useMemo(() => {
    if (sortState.key === "rank" && sortState.dir === "asc") {
      return companies;
    }
    return [...companies].sort((a, b) => compareForSort(a, b, sortState, rankIndex));
  }, [companies, sortState, rankIndex]);

  const onSortClick = (key: SortKey) => {
    setSortState((prev) => {
      if (prev.key !== key) {
        // First click on a column: ascending (numbers small→large, names a→z).
        // Exception: "rank" defaults to ascending (top of list = best peer).
        return { key, dir: "asc" };
      }
      // Second click on same column: flip direction.
      return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
    });
  };

  const SortIcon = ({ active, dir }: { active: boolean; dir: SortDir }) => {
    if (!active) return <ArrowUpDown className="w-3 h-3 inline-block ml-1 opacity-40" />;
    return dir === "asc"
      ? <ArrowUp className="w-3 h-3 inline-block ml-1" />
      : <ArrowDown className="w-3 h-3 inline-block ml-1" />;
  };

  const toggleSelect = (ent: string) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(ent)) {
      next.delete(ent);
    } else {
      next.add(ent);
    }
    return next;
  });
  const toggleAll = () => setSelected((prev) =>
    prev.size === companies.length ? new Set() : new Set(companies.map((c) => c.enterprise_number))
  );
  const addSelectedToFavourites = async () => {
    if (selected.size === 0) return;
    setAddingFavs(true);
    try {
      const { addFavourite } = await import("@/lib/api");
      for (const ent of selected) {
        await addFavourite(ent);
      }
      setSelected(new Set());
    } catch { /* ignore */ }
    finally { setAddingFavs(false); }
  };
  const loadProjects = async () => {
    try {
      const { getFavouriteProjects } = await import("@/lib/api");
      const data = await getFavouriteProjects();
      setProjects(data.map((p) => ({ id: p.id, name: p.name })));
    } catch { /* ignore */ }
  };
  const addSelectedToProject = async (projectId: number) => {
    if (selected.size === 0) return;
    setAddingToProject(true);
    try {
      const { addProjectMember } = await import("@/lib/api");
      for (const ent of selected) {
        await addProjectMember(projectId, ent);
      }
      setSelected(new Set());
      setShowProjectMenu(false);
    } catch { /* ignore */ }
    finally { setAddingToProject(false); }
  };
  const createProjectAndAdd = async () => {
    if (!newProjectName.trim() || selected.size === 0) return;
    setAddingToProject(true);
    try {
      const { createFavouriteProject, addProjectMember } = await import("@/lib/api");
      const proj = await createFavouriteProject(newProjectName.trim());
      for (const ent of selected) {
        await addProjectMember(proj.id, ent);
      }
      setSelected(new Set());
      setShowProjectMenu(false);
      setNewProjectName("");
    } catch { /* ignore */ }
    finally { setAddingToProject(false); }
  };

  // Returns the mapped array on success, or null on error. expandResults
  // needs the real fetched length (React state updates are batched / async,
  // so reading `companies.length` after an await gives a stale closure value).
  const loadSimilar = async (limit = DEFAULT_LIMIT): Promise<AiSimilarCompany[] | null> => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAiSimilarCompanies(cbe, limit);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const mapped = data.map((d) => ({
        ...d,
        ai_reason: (d as any).ai_reason as string | undefined,
        ai_reason_sections: (d as any).ai_reason_sections as AiSimilarCompany["ai_reason_sections"] | undefined,
      }));
      setCompanies(mapped);
      return mapped;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("401") || msg.includes("403")) {
        setError("Sign in to use AI Similar Companies.");
      } else {
        setError("Could not load similar companies.");
      }
      return null;
    } finally {
      setLoading(false);
    }
  };

  const expandResults = async () => {
    const prevCount = companies.length;
    const data = await loadSimilar(EXPANDED_LIMIT);
    // Only flip the "no more" flag when the refetch actually succeeded AND
    // didn't grow the list. On fetch error, keep existing rows + let the
    // user retry via the Regenerate icon.
    if (data !== null) {
      setExpanded(true);
      setNoMoreAvailable(data.length <= prevCount);
    }
  };

  const resetResults = async () => {
    setExpanded(false);
    setNoMoreAvailable(false);
    await loadSimilar(DEFAULT_LIMIT);
  };

  // Reload when the viewed company changes so the button state and results
  // always match the current profile.
  useEffect(() => {
    setCompanies([]);
    setSelected(new Set());
    setExpanded(false);
    setNoMoreAvailable(false);
    void loadSimilar(DEFAULT_LIMIT);
  }, [cbe]); // eslint-disable-line react-hooks/exhaustive-deps

  // Loading state
  if (loading && companies.length === 0) {
    return (
      <div className="py-12 text-center">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-soft border border-brand/20">
          <Loader2 className="w-4 h-4 animate-spin text-brand" />
          <span className="text-sm text-brand font-medium">Finding similar companies with AI...</span>
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
        <button onClick={() => loadSimilar()} className="mt-3 text-xs text-brand hover:text-[color:var(--brand-ink)] font-medium">
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
          <div className="h-7 px-2.5 rounded-full bg-brand-soft border border-brand/20 flex items-center gap-1.5">
            <Sparkles className="w-3 h-3 text-brand" />
            <span className="text-[11px] font-semibold text-brand">AI Similar Companies</span>
          </div>
          <span className="text-[10px] text-slate-400">({companies.length})</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={resetResults}
            disabled={loading}
            className="inline-flex items-center gap-1 text-[10px] text-slate-400 hover:text-brand transition-colors disabled:opacity-50"
            title="Regenerate"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
          </button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-[11px] text-brand border-brand/30 hover:bg-brand-soft/60 px-3"
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

      {/* Selection action bar */}
      {selected.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-brand/20 bg-brand-soft/50 px-3 py-2">
          <span className="text-[11px] text-brand font-medium">{selected.size} selected</span>
          <div className="flex-1" />
          <button
            onClick={addSelectedToFavourites}
            disabled={addingFavs}
            className="inline-flex items-center gap-1 h-10 md:h-7 px-3 text-[11px] font-medium text-brand border border-brand/30 rounded-md hover:bg-brand-soft disabled:opacity-50 transition-colors bg-white"
          >
            {addingFavs ? <Loader2 className="w-3 h-3 animate-spin" /> : <Heart className="w-3 h-3" />}
            Favourites
          </button>
          <div className="relative">
            <button
              onClick={() => { setShowProjectMenu(!showProjectMenu); if (!showProjectMenu) loadProjects(); }}
              className="inline-flex items-center gap-1 h-10 md:h-7 px-3 text-[11px] font-medium text-brand border border-brand/30 rounded-md hover:bg-brand-soft transition-colors bg-white"
            >
              <FolderPlus className="w-3 h-3" />
              Project
              <ChevronDown className="w-2.5 h-2.5" />
            </button>
            {showProjectMenu && (
              <div className="absolute top-full right-0 mt-1 w-56 max-w-[calc(100vw-2rem)] bg-white rounded-lg border border-slate-200 shadow-lg z-50 py-1">
                {projects.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => addSelectedToProject(p.id)}
                    disabled={addingToProject}
                    className="w-full text-left px-3 py-1.5 text-[11px] text-slate-700 hover:bg-brand-soft/60 disabled:opacity-50"
                  >
                    {p.name}
                  </button>
                ))}
                {projects.length > 0 && <div className="border-t border-slate-100 my-1" />}
                <div className="px-2 py-1.5 flex gap-1">
                  <input
                    className="flex-1 h-9 md:h-6 text-base md:text-[11px] border border-slate-200 rounded px-2 focus:outline-none focus:ring-1 focus:ring-brand/60"
                    placeholder="New project name..."
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") createProjectAndAdd(); }}
                  />
                  <button
                    onClick={createProjectAndAdd}
                    disabled={!newProjectName.trim() || addingToProject}
                    className="h-6 px-2 text-[10px] font-medium text-white bg-brand rounded disabled:opacity-40 hover:bg-[color:var(--brand-ink)]"
                  >
                    {addingToProject ? "..." : "Create"}
                  </button>
                </div>
              </div>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-10 md:h-7 text-[11px] text-brand border-brand/30 hover:bg-brand-soft px-3 bg-white"
            onClick={() => {
              const cbes = [...selected];
              if (!cbes.includes(cbe)) cbes.unshift(cbe);
              sessionStorage.setItem("compare_companies", JSON.stringify(cbes));
              router.push("/compare");
            }}
          >
            <Scale className="w-3 h-3 mr-1" />
            Compare
          </Button>
        </div>
      )}

      {/* Results table */}
      <div className="rounded-xl border border-slate-200 overflow-x-auto bg-white">
        <table className="w-full min-w-[720px]">
          <thead>
            <tr className="bg-slate-50/80 border-b border-slate-100">
              <th className="px-2 py-2 w-11">
                <button
                  onClick={toggleAll}
                  className="h-10 w-10 md:h-auto md:w-auto flex items-center justify-center text-slate-400 hover:text-brand transition-colors"
                  title={selected.size === companies.length ? "Unselect all" : "Select all"}
                >
                  {selected.size === companies.length ? <CheckSquare className="w-4 h-4 md:w-3.5 md:h-3.5" /> : <Square className="w-4 h-4 md:w-3.5 md:h-3.5" />}
                </button>
              </th>
              <th className="px-3 py-2 text-left text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400 w-6 hidden sm:table-cell">
                <button
                  onClick={() => onSortClick("rank")}
                  className="flex items-center hover:text-brand transition-colors"
                  title="Sort by AI rank"
                >
                  #<SortIcon active={sortState.key === "rank"} dir={sortState.dir} />
                </button>
              </th>
              <th className="px-3 py-2 text-left text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                <button
                  onClick={() => onSortClick("name")}
                  className="flex items-center hover:text-brand transition-colors"
                  title="Sort by company name"
                >
                  Company<SortIcon active={sortState.key === "name"} dir={sortState.dir} />
                </button>
              </th>
              <th className="px-3 py-2 text-left text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400 min-w-[180px]">Why similar</th>
              <th className="px-3 py-2 text-left text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400 hidden md:table-cell">
                <button
                  onClick={() => onSortClick("zipcode")}
                  className="flex items-center hover:text-brand transition-colors"
                  title="Sort by postcode"
                >
                  Postcode<SortIcon active={sortState.key === "zipcode"} dir={sortState.dir} />
                </button>
              </th>
              <th className="px-3 py-2 text-right text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                <button
                  onClick={() => onSortClick("revenue")}
                  className="flex items-center justify-end ml-auto hover:text-brand transition-colors"
                  title="Sort by revenue"
                >
                  Revenue<SortIcon active={sortState.key === "revenue"} dir={sortState.dir} />
                </button>
              </th>
              <th className="px-3 py-2 text-right text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                <button
                  onClick={() => onSortClick("ebitda")}
                  className="flex items-center justify-end ml-auto hover:text-brand transition-colors"
                  title="Sort by EBITDA"
                >
                  EBITDA<SortIcon active={sortState.key === "ebitda"} dir={sortState.dir} />
                </button>
              </th>
              <th className="px-3 py-2 text-right text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400 hidden sm:table-cell">
                <button
                  onClick={() => onSortClick("fte_total")}
                  className="flex items-center justify-end ml-auto hover:text-brand transition-colors"
                  title="Sort by FTE"
                >
                  FTE<SortIcon active={sortState.key === "fte_total"} dir={sortState.dir} />
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedCompanies.map((sc, idx) => (
              <tr key={sc.enterprise_number} className={`border-t border-slate-50 align-top hover:bg-brand-soft/30 transition-colors ${selected.has(sc.enterprise_number) ? "bg-brand-soft/40" : ""}`}>
                <td className="px-2 py-2.5 align-top">
                  <button
                    onClick={() => toggleSelect(sc.enterprise_number)}
                    className="h-10 w-10 md:h-auto md:w-auto flex items-center justify-center text-slate-300 hover:text-brand transition-colors"
                    title={selected.has(sc.enterprise_number) ? "Unselect" : "Select"}
                  >
                    {selected.has(sc.enterprise_number) ? <CheckSquare className="w-4 h-4 md:w-3.5 md:h-3.5 text-brand" /> : <Square className="w-4 h-4 md:w-3.5 md:h-3.5" />}
                  </button>
                </td>
                <td className="px-3 py-2.5 align-top text-[11px] md:text-[10px] font-mono text-slate-300 hidden sm:table-cell">{idx + 1}</td>
                <td className="px-3 py-2.5 align-top">
                  <Link href={`/company/${sc.enterprise_number}`} className="text-xs font-semibold text-brand hover:text-[color:var(--brand-ink)] hover:underline">
                    {sc.name}
                  </Link>
                  {sc.city && <div className="text-[11px] md:text-[10px] text-slate-400 mt-0.5">{sc.city}</div>}
                </td>
                <td className="px-3 py-2.5 align-top text-[11px] md:text-[10px] text-slate-500 leading-relaxed max-w-[360px]">
                  {(() => {
                    const reasonParts = splitReason(sc.ai_reason, sc.ai_reason_sections);
                    const displayParts = reasonParts.length > 0 ? reasonParts : fallbackReasonParts(sc);
                    return displayParts.length > 0 ? (
                      <div className="space-y-2">
                        {displayParts.map((part) => (
                          <div
                            key={`${sc.enterprise_number}-${part.label}`}
                            className="grid grid-cols-[76px_minmax(0,1fr)] items-start gap-x-3 gap-y-0.5 leading-snug"
                          >
                            <span className="pt-0.5 text-[10px] uppercase tracking-wide text-slate-400 font-semibold">
                              {part.label}
                            </span>
                            <span className="min-w-0 text-slate-600">{part.text}</span>
                          </div>
                        ))}
                      </div>
                    ) : "\u2014";
                  })()}
                </td>
                <td className="px-3 py-2.5 align-top text-[11px] md:text-[10px] font-mono text-slate-500 hidden md:table-cell">{sc.zipcode || "—"}</td>
                <td className="px-3 py-2.5 align-top text-right text-[11px] md:text-xs font-mono text-slate-700">{fmtEur(sc.revenue)}</td>
                <td className="px-3 py-2.5 align-top text-right text-[11px] md:text-xs font-mono text-slate-600">{fmtEur(sc.ebitda)}</td>
                <td className="px-3 py-2.5 align-top text-right text-[11px] md:text-xs font-mono text-slate-600 hidden sm:table-cell">{sc.fte_total != null ? fmtNumber(sc.fte_total) : "\u2014"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Find more — visible whenever there are any results and we haven't
          either expanded yet or learned the LLM has nothing more. Clicking
          either grows the list or flips to the "no more" notice, so the
          user always has a way to check. The min-height on the wrapper
          keeps the slot the same size whether it contains the button, the
          notice, or nothing at all, so the rows above don't jump. */}
      <div className="mt-4 text-center min-h-[40px] flex items-center justify-center">
        {noMoreAvailable ? (
          <p className="text-[11px] text-slate-400 italic">
            No more similar companies to show.
          </p>
        ) : !expanded && companies.length > 0 ? (
          <button
            onClick={expandResults}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-5 py-2 text-[11px] font-medium text-brand border border-brand/30 rounded-lg hover:bg-brand-soft/60 disabled:opacity-50 transition-colors"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            {loading ? "Finding more..." : "Find more similar companies"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
