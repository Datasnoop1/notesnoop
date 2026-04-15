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
  getPeopleFavourites,
  removePeopleFavourite,
  searchCompanies,
  getCustomers,
  getSuppliers,
  uploadCustomers,
  uploadSuppliers,
  removeCustomer,
  removeSupplier,
  type FavouriteItem,
  type FavouriteProject,
  type PeopleFavourite,
  type SearchResult,
  type CustomerSupplierItem,
  type CsUploadResult,
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
  Users,
  Building2,
  Upload,
  FileSpreadsheet,
  Truck,
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
  const [addSearch, setAddSearch] = useState("");
  const [addResults, setAddResults] = useState<SearchResult[]>([]);
  const [addSearching, setAddSearching] = useState(false);

  const memberCbes = new Set(project.members.map((m) => m.enterprise_number));

  // Debounced search for companies to add
  useEffect(() => {
    if (!showAddMenu || addSearch.length < 2) {
      setAddResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setAddSearching(true);
      try {
        const results = await searchCompanies(addSearch);
        setAddResults(results.filter((r: SearchResult) => !memberCbes.has(r.enterprise_number)));
      } catch {
        setAddResults([]);
      } finally {
        setAddSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [addSearch, showAddMenu]);

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
                    onClick={() => { setShowAddMenu(false); setAddSearch(""); }}
                  />
                  <div className="absolute right-0 top-full mt-1 z-50 w-96 bg-white border border-slate-200 rounded-lg shadow-xl">
                    <div className="p-2 border-b border-slate-100">
                      <Input
                        placeholder="Search any company by name or CBE..."
                        value={addSearch}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setAddSearch(e.target.value)}
                        className="h-8 text-sm"
                        autoFocus
                      />
                    </div>
                    <div className="max-h-72 overflow-y-auto">
                      {addSearch.length < 2 ? (
                        <p className="text-xs text-slate-400 p-4 text-center">
                          Type at least 2 characters to search
                        </p>
                      ) : addSearching ? (
                        <div className="flex items-center justify-center gap-2 py-4">
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
                          <span className="text-xs text-slate-400">Searching...</span>
                        </div>
                      ) : addResults.length === 0 ? (
                        <p className="text-xs text-slate-400 p-4 text-center">
                          No companies found
                        </p>
                      ) : (
                        addResults.map((r) => (
                          <button
                            key={r.enterprise_number}
                            onClick={() => {
                              onAddMember(project.id, r.enterprise_number);
                              setAddSearch("");
                              setShowAddMenu(false);
                            }}
                            className="w-full text-left px-3 py-2.5 hover:bg-indigo-50 border-b border-slate-50 last:border-0 flex items-center justify-between gap-2"
                          >
                            <div className="min-w-0">
                              <span className="text-sm font-medium text-slate-800 truncate block">
                                {r.name || fmtCbe(r.enterprise_number)}
                              </span>
                              <span className="text-[10px] text-slate-400">
                                {fmtCbe(r.enterprise_number)} · {r.city || "—"}
                              </span>
                            </div>
                            <Plus className="h-3.5 w-3.5 text-indigo-500 shrink-0" />
                          </button>
                        ))
                      )}
                    </div>
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

/* ---------- file parser helper ---------- */

function parseCbeFromFile(file: File): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string;
        const lines = text.split(/[\r\n]+/).filter(Boolean);
        const cbes: string[] = [];
        for (const line of lines) {
          // Take the first column (comma or semicolon or tab separated)
          const cell = line.split(/[,;\t]/)[0].trim();
          // Strip dots, spaces, quotes
          const cleaned = cell.replace(/[."' ]/g, "");
          // Skip header-like rows and empty values
          if (!cleaned || /^[a-zA-Z]/.test(cleaned)) continue;
          // Pad to 10 digits
          const padded = cleaned.padStart(10, "0");
          // Basic validation: should be 10 digits
          if (/^\d{10}$/.test(padded)) {
            cbes.push(padded);
          }
        }
        resolve(cbes);
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsText(file);
  });
}

/* ---------- upload zone + table for customers/suppliers ---------- */

function CsTab({
  listType,
  items,
  loading,
  uploading,
  uploadResult,
  removing,
  onUpload,
  onRemove,
  onClearResult,
}: {
  listType: "customer" | "supplier";
  items: CustomerSupplierItem[];
  loading: boolean;
  uploading: boolean;
  uploadResult: CsUploadResult | null;
  removing: string | null;
  onUpload: (file: File) => void;
  onRemove: (cbe: string) => void;
  onClearResult: () => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  const label = listType === "customer" ? "Customers" : "Suppliers";
  const Icon = listType === "customer" ? Building2 : Truck;

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) onUpload(file);
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) onUpload(file);
    e.target.value = "";
  }

  return (
    <div className="space-y-4">
      {/* Upload zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-8 px-4 transition-colors ${
          dragOver
            ? "border-indigo-400 bg-indigo-50"
            : "border-slate-200 bg-slate-50/50 hover:border-slate-300"
        }`}
      >
        {uploading ? (
          <div className="flex items-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin text-indigo-500" />
            <span className="text-sm text-slate-600">Processing file...</span>
          </div>
        ) : (
          <>
            <FileSpreadsheet className="h-8 w-8 text-slate-300 mb-2" />
            <p className="text-sm font-medium text-slate-600">
              Drag & drop an Excel or CSV file
            </p>
            <p className="text-xs text-slate-400 mt-1 mb-3">
              First column should contain CBE numbers (0xxx.xxx.xxx or 0xxxxxxxxx)
            </p>
            <label>
              <input
                type="file"
                accept=".csv,.xlsx,.xls,.tsv,.txt"
                onChange={handleFileInput}
                className="hidden"
              />
              <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-md cursor-pointer transition-colors">
                <Upload className="h-3.5 w-3.5" />
                Browse files
              </span>
            </label>
          </>
        )}
      </div>

      {/* Upload result banner */}
      {uploadResult && (
        <div className="flex items-center justify-between rounded-md bg-emerald-50 border border-emerald-200 px-4 py-2.5">
          <div className="text-sm text-emerald-800">
            <span className="font-semibold">{uploadResult.matched}</span> {uploadResult.matched === 1 ? "company" : "companies"} matched
            {uploadResult.not_found > 0 && (
              <span className="text-amber-700 ml-2">
                · {uploadResult.not_found} not found
              </span>
            )}
          </div>
          <button
            onClick={onClearResult}
            className="text-emerald-600 hover:text-emerald-800 p-0.5"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <Card className="bg-white overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Company</TableHead>
                <TableHead>City</TableHead>
                <TableHead className="text-right">Revenue</TableHead>
                <TableHead className="text-right">EBITDA</TableHead>
                <TableHead className="text-right">Margin</TableHead>
                <TableHead className="text-right">FTE</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              <SkeletonRows cols={7} count={5} />
            </TableBody>
          </Table>
        </Card>
      )}

      {/* Empty state */}
      {!loading && items.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-10">
          <Icon className="h-6 w-6 text-slate-300 mb-2" />
          <p className="text-sm font-medium text-slate-500">
            No {label.toLowerCase()} yet.
          </p>
          <p className="mt-2 text-xs text-slate-400">
            Upload a CSV or Excel file with CBE numbers to populate this list.
          </p>
        </div>
      )}

      {/* Table */}
      {!loading && items.length > 0 && (
        <Card className="bg-white overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="min-w-[200px]">Company</TableHead>
                <TableHead>City</TableHead>
                <TableHead className="text-right">Revenue</TableHead>
                <TableHead className="text-right">EBITDA</TableHead>
                <TableHead className="text-right">Margin</TableHead>
                <TableHead className="text-right">FTE</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.enterprise_number} className="hover:bg-indigo-50/40">
                  <TableCell className="font-medium py-1.5 text-sm">
                    <Link
                      href={`/company/${item.enterprise_number}`}
                      className="text-indigo-600 hover:text-indigo-800 hover:underline"
                    >
                      {item.name || item.custom_name || fmtCbe(item.enterprise_number)}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs text-slate-600 py-1.5">
                    {item.city ?? "\u2014"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs py-1.5">
                    {fmtEur(item.revenue)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs py-1.5">
                    {fmtEur(item.ebitda)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs py-1.5">
                    {fmtPct(item.margin_pct)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs py-1.5">
                    {fmtNumber(item.fte_total)}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 text-slate-400 hover:text-red-600 hover:bg-red-50"
                      onClick={() => onRemove(item.enterprise_number)}
                      disabled={removing === item.enterprise_number}
                    >
                      {removing === item.enterprise_number ? (
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
  );
}

/* ---------- main component ---------- */

export default function FavouritesPage() {
  const [favourites, setFavourites] = useState<FavouriteItem[]>([]);
  const [projects, setProjects] = useState<FavouriteProject[]>([]);
  const [peopleFavs, setPeopleFavs] = useState<PeopleFavourite[]>([]);
  const [customers, setCustomers] = useState<CustomerSupplierItem[]>([]);
  const [suppliers, setSuppliers] = useState<CustomerSupplierItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingPeople, setLoadingPeople] = useState(true);
  const [loadingCustomers, setLoadingCustomers] = useState(true);
  const [loadingSuppliers, setLoadingSuppliers] = useState(true);
  const [removing, setRemoving] = useState<string | null>(null);
  const [removingPerson, setRemovingPerson] = useState<string | null>(null);
  const [removingCustomer, setRemovingCustomer] = useState<string | null>(null);
  const [removingSupplier, setRemovingSupplier] = useState<string | null>(null);
  const [uploadingCustomers, setUploadingCustomers] = useState(false);
  const [uploadingSuppliers, setUploadingSuppliers] = useState(false);
  const [customerUploadResult, setCustomerUploadResult] = useState<CsUploadResult | null>(null);
  const [supplierUploadResult, setSupplierUploadResult] = useState<CsUploadResult | null>(null);
  const [newProjectName, setNewProjectName] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);
  const [activeTab, setActiveTab] = useState<"companies" | "people" | "customers" | "suppliers">("companies");

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

  const loadPeopleFavourites = useCallback(async () => {
    try {
      const data = await getPeopleFavourites();
      setPeopleFavs(data);
    } catch (err) {
      console.error("Failed to load people favourites:", err);
      setPeopleFavs([]);
    } finally {
      setLoadingPeople(false);
    }
  }, []);

  const loadCustomers = useCallback(async () => {
    try {
      const data = await getCustomers();
      setCustomers(data);
    } catch (err) {
      console.error("Failed to load customers:", err);
      setCustomers([]);
    } finally {
      setLoadingCustomers(false);
    }
  }, []);

  const loadSuppliers = useCallback(async () => {
    try {
      const data = await getSuppliers();
      setSuppliers(data);
    } catch (err) {
      console.error("Failed to load suppliers:", err);
      setSuppliers([]);
    } finally {
      setLoadingSuppliers(false);
    }
  }, []);

  useEffect(() => {
    loadFavourites();
    loadProjects();
    loadPeopleFavourites();
    loadCustomers();
    loadSuppliers();
  }, [loadFavourites, loadProjects, loadPeopleFavourites, loadCustomers, loadSuppliers]);

  async function handleRemovePerson(name: string) {
    setRemovingPerson(name);
    try {
      await removePeopleFavourite(name);
      setPeopleFavs((prev) => prev.filter((p) => p.person_name !== name));
    } catch (err) {
      console.error("Failed to remove person favourite:", err);
    } finally {
      setRemovingPerson(null);
    }
  }

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

  async function handleCustomerUpload(file: File) {
    setUploadingCustomers(true);
    setCustomerUploadResult(null);
    try {
      const cbes = await parseCbeFromFile(file);
      if (cbes.length === 0) {
        setCustomerUploadResult({ matched: 0, not_found: 0, total: 0, not_found_cbes: [] });
        return;
      }
      const result = await uploadCustomers(cbes);
      setCustomerUploadResult(result);
      loadCustomers();
    } catch (err) {
      console.error("Customer upload failed:", err);
    } finally {
      setUploadingCustomers(false);
    }
  }

  async function handleSupplierUpload(file: File) {
    setUploadingSuppliers(true);
    setSupplierUploadResult(null);
    try {
      const cbes = await parseCbeFromFile(file);
      if (cbes.length === 0) {
        setSupplierUploadResult({ matched: 0, not_found: 0, total: 0, not_found_cbes: [] });
        return;
      }
      const result = await uploadSuppliers(cbes);
      setSupplierUploadResult(result);
      loadSuppliers();
    } catch (err) {
      console.error("Supplier upload failed:", err);
    } finally {
      setUploadingSuppliers(false);
    }
  }

  async function handleRemoveCustomer(cbe: string) {
    setRemovingCustomer(cbe);
    try {
      await removeCustomer(cbe);
      setCustomers((prev) => prev.filter((c) => c.enterprise_number !== cbe));
    } catch (err) {
      console.error("Failed to remove customer:", err);
    } finally {
      setRemovingCustomer(null);
    }
  }

  async function handleRemoveSupplier(cbe: string) {
    setRemovingSupplier(cbe);
    try {
      await removeSupplier(cbe);
      setSuppliers((prev) => prev.filter((s) => s.enterprise_number !== cbe));
    } catch (err) {
      console.error("Failed to remove supplier:", err);
    } finally {
      setRemovingSupplier(null);
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
            Track companies and people for deal sourcing
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!loading && (
            <Badge variant="secondary" className="text-indigo-700 bg-indigo-50 border-indigo-200">
              {favourites.length} {favourites.length === 1 ? "company" : "companies"} · {peopleFavs.length} {peopleFavs.length === 1 ? "person" : "people"}
            </Badge>
          )}
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex items-center gap-1 border-b border-slate-100 pb-0">
        <button
          onClick={() => setActiveTab("companies")}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 ${
            activeTab === "companies"
              ? "border-indigo-500 text-indigo-600"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          <Building2 className="h-3.5 w-3.5" /> Companies
        </button>
        <button
          onClick={() => setActiveTab("people")}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 ${
            activeTab === "people"
              ? "border-indigo-500 text-indigo-600"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          <Users className="h-3.5 w-3.5" /> People
        </button>
        <button
          onClick={() => setActiveTab("customers")}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 ${
            activeTab === "customers"
              ? "border-indigo-500 text-indigo-600"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          <Building2 className="h-3.5 w-3.5" /> Customers
          {!loadingCustomers && customers.length > 0 && (
            <Badge variant="secondary" className="text-[10px] ml-0.5 px-1.5 py-0">{customers.length}</Badge>
          )}
        </button>
        <button
          onClick={() => setActiveTab("suppliers")}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 ${
            activeTab === "suppliers"
              ? "border-indigo-500 text-indigo-600"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          <Truck className="h-3.5 w-3.5" /> Suppliers
          {!loadingSuppliers && suppliers.length > 0 && (
            <Badge variant="secondary" className="text-[10px] ml-0.5 px-1.5 py-0">{suppliers.length}</Badge>
          )}
        </button>
      </div>

      {activeTab === "companies" && (<>
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
      </>)}

      {/* ── People Favourites ──────────────────────────────── */}
      {activeTab === "people" && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
            <Users className="w-4 h-4" />
            Saved People
          </h2>

          {loadingPeople && (
            <div className="flex items-center gap-2 py-8">
              <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
              <span className="text-sm text-slate-400">Loading people favourites...</span>
            </div>
          )}

          {!loadingPeople && peopleFavs.length === 0 && (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-10">
              <Users className="h-6 w-6 text-slate-300 mb-2" />
              <p className="text-sm font-medium text-slate-500">
                No people saved yet.
              </p>
              <p className="mt-2 text-xs text-slate-400">
                Visit a company profile → Administrators tab and click the star next to a person to save them here.
              </p>
            </div>
          )}

          {!loadingPeople && peopleFavs.length > 0 && (
            <Card className="bg-white overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="bg-slate-50">
                    <TableHead className="min-w-[200px]">Name</TableHead>
                    <TableHead className="text-right">Companies</TableHead>
                    <TableHead>Current Roles</TableHead>
                    <TableHead>Added</TableHead>
                    <TableHead>Notes</TableHead>
                    <TableHead className="w-12" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {peopleFavs.map((pf) => (
                    <TableRow key={pf.person_name} className="hover:bg-indigo-50/40">
                      <TableCell className="font-medium py-1.5 text-sm">
                        <Link
                          href={`/people?q=${encodeURIComponent(pf.person_name)}`}
                          className="text-indigo-600 hover:text-indigo-800 hover:underline"
                        >
                          {pf.person_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs py-1.5">
                        {pf.company_count ?? 0}
                      </TableCell>
                      <TableCell className="text-xs text-slate-500 py-1.5 max-w-[300px] truncate" title={pf.companies ?? ""}>
                        {pf.companies ?? "—"}
                      </TableCell>
                      <TableCell className="text-xs text-slate-500 whitespace-nowrap py-1.5">
                        {formatDate(pf.added_at)}
                      </TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs text-slate-500 py-1.5" title={pf.notes ?? ""}>
                        {pf.notes ?? "—"}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 w-8 p-0 text-slate-400 hover:text-red-600 hover:bg-red-50"
                          onClick={() => handleRemovePerson(pf.person_name)}
                          disabled={removingPerson === pf.person_name}
                        >
                          {removingPerson === pf.person_name ? (
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
      )}

      {/* ── Customers ──────────────────────────────────────── */}
      {activeTab === "customers" && (
        <CsTab
          listType="customer"
          items={customers}
          loading={loadingCustomers}
          uploading={uploadingCustomers}
          uploadResult={customerUploadResult}
          removing={removingCustomer}
          onUpload={handleCustomerUpload}
          onRemove={handleRemoveCustomer}
          onClearResult={() => setCustomerUploadResult(null)}
        />
      )}

      {/* ── Suppliers ──────────────────────────────────────── */}
      {activeTab === "suppliers" && (
        <CsTab
          listType="supplier"
          items={suppliers}
          loading={loadingSuppliers}
          uploading={uploadingSuppliers}
          uploadResult={supplierUploadResult}
          removing={removingSupplier}
          onUpload={handleSupplierUpload}
          onRemove={handleRemoveSupplier}
          onClearResult={() => setSupplierUploadResult(null)}
        />
      )}
    </div>
  );
}
