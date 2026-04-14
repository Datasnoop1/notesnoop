"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  getFavourites,
  removeFavourite,
  getFavouriteProjects,
  createFavouriteProject,
  addProjectMember,
  removeProjectMember,
  deleteFavouriteProject,
  type FavouriteItem,
  type FavouriteProject,
} from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import {
  Star,
  Trash2,
  Loader2,
  FolderPlus,
  ChevronDown,
  ChevronRight,
  Plus,
  X,
} from "lucide-react";

/* ---------- skeleton ---------- */

function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-slate-200 ${className}`} />;
}

function SkeletonRows({ cols, count }: { cols: number; count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: cols }).map((_, j) => (
            <TableCell key={j}>
              <SkeletonBlock className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/* ---------- project card ---------- */

function ProjectCard({
  project,
  favourites,
  onAddMember,
  onRemoveMember,
  onDelete,
}: {
  project: FavouriteProject;
  favourites: FavouriteItem[];
  onAddMember: (projectId: number, cbe: string) => void;
  onRemoveMember: (projectId: number, cbe: string) => void;
  onDelete: (projectId: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showAddMenu, setShowAddMenu] = useState(false);

  const memberCbes = new Set(project.members.map((m) => m.enterprise_number));
  const addableFavourites = favourites.filter(
    (f) => !memberCbes.has(f.enterprise_number)
  );

  return (
    <Card className="bg-white overflow-hidden">
      <div className="px-4 py-3">
        <div className="flex items-center justify-between">
          <button
            onClick={() => setExpanded((prev) => !prev)}
            className="flex items-center gap-2 text-left flex-1 min-w-0"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4 text-slate-400 shrink-0" />
            ) : (
              <ChevronRight className="h-4 w-4 text-slate-400 shrink-0" />
            )}
            <span className="font-semibold text-sm text-slate-900 truncate">
              {project.name}
            </span>
            <Badge variant="secondary" className="text-[10px] shrink-0">
              {project.members.length}{" "}
              {project.members.length === 1 ? "company" : "companies"}
            </Badge>
          </button>
          <div className="flex items-center gap-1 shrink-0 ml-2">
            <div className="relative">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-indigo-600 hover:text-indigo-800"
                onClick={() => setShowAddMenu((prev) => !prev)}
              >
                <Plus className="h-3.5 w-3.5 mr-1" />
                Add
              </Button>
              {showAddMenu && (
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setShowAddMenu(false)}
                  />
                  <div className="absolute right-0 top-full mt-1 z-50 w-64 bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                    {addableFavourites.length === 0 ? (
                      <p className="text-xs text-slate-400 p-3 text-center">
                        All favourites already in this project
                      </p>
                    ) : (
                      addableFavourites.map((f) => (
                        <button
                          key={f.enterprise_number}
                          onClick={() => {
                            onAddMember(project.id, f.enterprise_number);
                            setShowAddMenu(false);
                          }}
                          className="w-full text-left px-3 py-2 hover:bg-slate-50 border-b border-slate-100 last:border-0 text-sm flex items-center justify-between"
                        >
                          <span className="truncate">
                            {f.name || fmtCbe(f.enterprise_number)}
                          </span>
                          <Plus className="h-3 w-3 text-indigo-500 shrink-0" />
                        </button>
                      ))
                    )}
                  </div>
                </>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 text-slate-400 hover:text-red-600 hover:bg-red-50"
              onClick={() => onDelete(project.id)}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Expanded member list */}
        {expanded && (
          <div className="mt-3 border-t border-slate-100 pt-2">
            {project.members.length === 0 ? (
              <p className="text-xs text-slate-400 py-2">
                No companies in this project yet. Add from your favourites.
              </p>
            ) : (
              <div className="space-y-1">
                {project.members.map((m) => (
                  <div
                    key={m.enterprise_number}
                    className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-slate-50"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Link
                        href={`/company/${m.enterprise_number}`}
                        className="text-sm text-indigo-600 hover:underline truncate"
                      >
                        {m.name || fmtCbe(m.enterprise_number)}
                      </Link>
                      <span className="text-[10px] text-slate-400 shrink-0">
                        {fmtCbe(m.enterprise_number)}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      {m.revenue != null && (
                        <span className="text-[10px] text-slate-500 font-mono">
                          {fmtEur(m.revenue)}
                        </span>
                      )}
                      <button
                        onClick={() =>
                          onRemoveMember(project.id, m.enterprise_number)
                        }
                        className="hover:bg-red-50 rounded p-0.5 text-slate-400 hover:text-red-600 transition-colors"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

/* ---------- main component ---------- */

export default function FavouritesPage() {
  const [favourites, setFavourites] = useState<FavouriteItem[]>([]);
  const [projects, setProjects] = useState<FavouriteProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [removing, setRemoving] = useState<string | null>(null);
  const [newProjectName, setNewProjectName] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);

  const loadFavourites = useCallback(async () => {
    try {
      const data = await getFavourites();
      setFavourites(data);
    } catch (err) {
      console.error("Failed to load favourites:", err);
      setFavourites([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadProjects = useCallback(async () => {
    try {
      const data = await getFavouriteProjects();
      setProjects(data);
    } catch (err) {
      console.error("Failed to load projects:", err);
      setProjects([]);
    } finally {
      setLoadingProjects(false);
    }
  }, []);

  useEffect(() => {
    loadFavourites();
    loadProjects();
  }, [loadFavourites, loadProjects]);

  async function handleRemove(cbe: string) {
    setRemoving(cbe);
    try {
      await removeFavourite(cbe);
      setFavourites((prev) => prev.filter((f) => f.enterprise_number !== cbe));
    } catch (err) {
      console.error("Failed to remove favourite:", err);
    } finally {
      setRemoving(null);
    }
  }

  async function handleCreateProject() {
    if (!newProjectName.trim()) return;
    setCreatingProject(true);
    try {
      const proj = await createFavouriteProject(newProjectName.trim());
      setProjects((prev) => [proj, ...prev]);
      setNewProjectName("");
    } catch (err) {
      console.error("Failed to create project:", err);
    } finally {
      setCreatingProject(false);
    }
  }

  async function handleAddProjectMember(projectId: number, cbe: string) {
    try {
      await addProjectMember(projectId, cbe);
      // Reload projects to get fresh member data
      const data = await getFavouriteProjects();
      setProjects(data);
    } catch (err) {
      console.error("Failed to add project member:", err);
    }
  }

  async function handleRemoveProjectMember(projectId: number, cbe: string) {
    try {
      await removeProjectMember(projectId, cbe);
      setProjects((prev) =>
        prev.map((p) =>
          p.id === projectId
            ? {
                ...p,
                members: p.members.filter(
                  (m) => m.enterprise_number !== cbe
                ),
              }
            : p
        )
      );
    } catch (err) {
      console.error("Failed to remove project member:", err);
    }
  }

  async function handleDeleteProject(projectId: number) {
    try {
      await deleteFavouriteProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
    } catch (err) {
      console.error("Failed to delete project:", err);
    }
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return "\u2014";
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            <Star className="w-4 h-4 inline mr-1.5" />
            Favourites
          </h1>
          <p className="mt-0.5 text-xs text-slate-500">
            Companies you are tracking for deal sourcing
          </p>
        </div>
        {!loading && favourites.length > 0 && (
          <Badge variant="secondary" className="text-indigo-700 bg-indigo-50 border-indigo-200">
            {favourites.length} {favourites.length === 1 ? "company" : "companies"}
          </Badge>
        )}
      </div>

      {/* ── Projects section ──────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">
            <FolderPlus className="w-4 h-4 inline mr-1.5" />
            Projects
          </h2>
        </div>

        {/* Create project */}
        <div className="flex gap-2 max-w-md">
          <Input
            placeholder="New project name..."
            value={newProjectName}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setNewProjectName(e.target.value)
            }
            onKeyDown={(e: React.KeyboardEvent) => {
              if (e.key === "Enter") handleCreateProject();
            }}
            className="text-sm"
          />
          <Button
            size="sm"
            onClick={handleCreateProject}
            disabled={!newProjectName.trim() || creatingProject}
          >
            {creatingProject ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              "Create"
            )}
          </Button>
        </div>

        {/* Project cards */}
        {loadingProjects && (
          <div className="flex items-center gap-2 py-4">
            <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
            <span className="text-sm text-slate-400">Loading projects...</span>
          </div>
        )}

        {!loadingProjects && projects.length === 0 && (
          <p className="text-xs text-slate-400 py-2">
            No projects yet. Create one to group your favourite companies.
          </p>
        )}

        {!loadingProjects && projects.length > 0 && (
          <div className="space-y-2">
            {projects.map((proj) => (
              <ProjectCard
                key={proj.id}
                project={proj}
                favourites={favourites}
                onAddMember={handleAddProjectMember}
                onRemoveMember={handleRemoveProjectMember}
                onDelete={handleDeleteProject}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Favourites list ──────────────────────────────── */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-700">
          All Favourites
        </h2>

        {/* Loading state */}
        {loading && (
          <Card className="bg-white overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead>Company</TableHead>
                  <TableHead>NACE</TableHead>
                  <TableHead className="text-right">Revenue</TableHead>
                  <TableHead className="text-right">EBITDA</TableHead>
                  <TableHead className="text-right">Margin</TableHead>
                  <TableHead className="text-right">FTE</TableHead>
                  <TableHead>Added</TableHead>
                  <TableHead>Notes</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                <SkeletonRows cols={9} count={5} />
              </TableBody>
            </Table>
          </Card>
        )}

        {/* Empty state */}
        {!loading && favourites.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-10">
            <Star className="h-6 w-6 text-slate-300 mb-2" />
            <p className="text-sm font-medium text-slate-500">
              No favourites yet. Star companies to track them here.
            </p>
            <p className="mt-2 text-xs text-slate-400">
              Use the company page or screener to add companies to your favourites list.
            </p>
          </div>
        )}

        {/* Favourites table */}
        {!loading && favourites.length > 0 && (
          <Card className="bg-white overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead className="min-w-[200px]">Company</TableHead>
                  <TableHead>NACE</TableHead>
                  <TableHead className="text-right">Revenue</TableHead>
                  <TableHead className="text-right">EBITDA</TableHead>
                  <TableHead className="text-right">Margin</TableHead>
                  <TableHead className="text-right">FTE</TableHead>
                  <TableHead>Added</TableHead>
                  <TableHead className="max-w-[200px]">Notes</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {favourites.map((fav) => (
                  <TableRow key={fav.enterprise_number} className="hover:bg-indigo-50/40">
                    <TableCell className="font-medium py-1.5 text-sm">
                      <Link
                        href={`/company/${fav.enterprise_number}`}
                        className="text-indigo-600 hover:text-indigo-800 hover:underline"
                      >
                        {fav.name || fmtCbe(fav.enterprise_number)}
                      </Link>
                    </TableCell>
                    <TableCell className="text-slate-600 text-xs py-1.5">
                      {fav.nace_code ?? "\u2014"}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5">
                      {fmtEur(fav.revenue)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5">
                      {fmtEur(fav.ebitda)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5">
                      {fmtPct(fav.margin_pct)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs py-1.5">
                      {fmtNumber(fav.fte_total)}
                    </TableCell>
                    <TableCell className="text-xs text-slate-500 whitespace-nowrap py-1.5">
                      {formatDate(fav.added_at)}
                    </TableCell>
                    <TableCell className="max-w-[200px] truncate text-xs text-slate-500 py-1.5" title={fav.notes ?? ""}>
                      {fav.notes ?? "\u2014"}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0 text-slate-400 hover:text-red-600 hover:bg-red-50"
                        onClick={() => handleRemove(fav.enterprise_number)}
                        disabled={removing === fav.enterprise_number}
                      >
                        {removing === fav.enterprise_number ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
    </div>
  );
}
