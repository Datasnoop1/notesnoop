"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Sparkles, Loader2, Scale, RefreshCw, Heart, CheckSquare, Square, FolderPlus, ChevronDown } from "lucide-react";
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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [addingFavs, setAddingFavs] = useState(false);
  const [showProjectMenu, setShowProjectMenu] = useState(false);
  const [projects, setProjects] = useState<{ id: number; name: string }[]>([]);
  const [newProjectName, setNewProjectName] = useState("");
  const [addingToProject, setAddingToProject] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [noMoreAvailable, setNoMoreAvailable] = useState(false);
  const triggered = useRef(false);

  const toggleSelect = (ent: string) => setSelected((prev) => {
    const next = new Set(prev);
    next.has(ent) ? next.delete(ent) : next.add(ent);
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
  const loadSimilar = async (limit?: number): Promise<AiSimilarCompany[] | null> => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAiSimilarCompanies(cbe, limit);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const mapped = data.map((d) => ({ ...d, ai_reason: (d as any).ai_reason as string | undefined }));
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
    const data = await loadSimilar(20);
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
    await loadSimilar();
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
        <button onClick={() => loadSimilar()} className="mt-3 text-xs text-indigo-500 hover:text-indigo-700 font-medium">
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
            onClick={resetResults}
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

      {/* Selection action bar */}
      {selected.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-indigo-100 bg-indigo-50/50 px-3 py-2">
          <span className="text-[11px] text-indigo-600 font-medium">{selected.size} selected</span>
          <div className="flex-1" />
          <button
            onClick={addSelectedToFavourites}
            disabled={addingFavs}
            className="inline-flex items-center gap-1 h-10 md:h-7 px-3 text-[11px] font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-100 disabled:opacity-50 transition-colors bg-white"
          >
            {addingFavs ? <Loader2 className="w-3 h-3 animate-spin" /> : <Heart className="w-3 h-3" />}
            Favourites
          </button>
          <div className="relative">
            <button
              onClick={() => { setShowProjectMenu(!showProjectMenu); if (!showProjectMenu) loadProjects(); }}
              className="inline-flex items-center gap-1 h-10 md:h-7 px-3 text-[11px] font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-100 transition-colors bg-white"
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
                    className="w-full text-left px-3 py-1.5 text-[11px] text-slate-700 hover:bg-indigo-50 disabled:opacity-50"
                  >
                    {p.name}
                  </button>
                ))}
                {projects.length > 0 && <div className="border-t border-slate-100 my-1" />}
                <div className="px-2 py-1.5 flex gap-1">
                  <input
                    className="flex-1 h-6 text-[11px] border border-slate-200 rounded px-2 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                    placeholder="New project name..."
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") createProjectAndAdd(); }}
                  />
                  <button
                    onClick={createProjectAndAdd}
                    disabled={!newProjectName.trim() || addingToProject}
                    className="h-6 px-2 text-[10px] font-medium text-white bg-indigo-600 rounded disabled:opacity-40 hover:bg-indigo-700"
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
            className="h-10 md:h-7 text-[11px] text-indigo-600 border-indigo-200 hover:bg-indigo-100 px-3 bg-white"
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
                  className="h-10 w-10 md:h-auto md:w-auto flex items-center justify-center text-slate-400 hover:text-indigo-600 transition-colors"
                  title={selected.size === companies.length ? "Unselect all" : "Select all"}
                >
                  {selected.size === companies.length ? <CheckSquare className="w-4 h-4 md:w-3.5 md:h-3.5" /> : <Square className="w-4 h-4 md:w-3.5 md:h-3.5" />}
                </button>
              </th>
              <th className="px-3 py-2 text-left text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400 w-6 hidden sm:table-cell">#</th>
              <th className="px-3 py-2 text-left text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400">Company</th>
              <th className="px-3 py-2 text-left text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400 min-w-[180px]">Why similar</th>
              <th className="px-3 py-2 text-right text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400">Revenue</th>
              <th className="px-3 py-2 text-right text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400">EBITDA</th>
              <th className="px-3 py-2 text-right text-[11px] md:text-[10px] font-semibold uppercase tracking-wider text-slate-400 hidden sm:table-cell">FTE</th>
            </tr>
          </thead>
          <tbody>
            {companies.map((sc, idx) => (
              <tr key={sc.enterprise_number} className={`border-t border-slate-50 hover:bg-indigo-50/30 transition-colors ${selected.has(sc.enterprise_number) ? "bg-indigo-50/40" : ""}`}>
                <td className="px-2 py-2.5">
                  <button
                    onClick={() => toggleSelect(sc.enterprise_number)}
                    className="h-10 w-10 md:h-auto md:w-auto flex items-center justify-center text-slate-300 hover:text-indigo-600 transition-colors"
                    title={selected.has(sc.enterprise_number) ? "Unselect" : "Select"}
                  >
                    {selected.has(sc.enterprise_number) ? <CheckSquare className="w-4 h-4 md:w-3.5 md:h-3.5 text-indigo-500" /> : <Square className="w-4 h-4 md:w-3.5 md:h-3.5" />}
                  </button>
                </td>
                <td className="px-3 py-2.5 text-[11px] md:text-[10px] font-mono text-slate-300 hidden sm:table-cell">{idx + 1}</td>
                <td className="px-3 py-2.5">
                  <Link href={`/company/${sc.enterprise_number}`} className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 hover:underline">
                    {sc.name}
                  </Link>
                  {sc.city && <div className="text-[11px] md:text-[10px] text-slate-400 mt-0.5">{sc.city}</div>}
                </td>
                <td className="px-3 py-2.5 text-[11px] md:text-[10px] text-slate-500 leading-relaxed max-w-[250px]">
                  {sc.ai_reason || "\u2014"}
                </td>
                <td className="px-3 py-2.5 text-right text-[11px] md:text-xs font-mono text-slate-700">{fmtEur(sc.revenue)}</td>
                <td className="px-3 py-2.5 text-right text-[11px] md:text-xs font-mono text-slate-600">{fmtEur(sc.ebitda)}</td>
                <td className="px-3 py-2.5 text-right text-[11px] md:text-xs font-mono text-slate-600 hidden sm:table-cell">{sc.fte_total != null ? fmtNumber(sc.fte_total) : "\u2014"}</td>
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
            className="inline-flex items-center gap-1.5 px-5 py-2 text-[11px] font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50 disabled:opacity-50 transition-colors"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            {loading ? "Finding more..." : "Find more similar companies"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
