"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  getGraveyardOverview,
  getRepeatOffenders,
  getPersonFailedCompanies,
  getInProcessCases,
  getDirectorAging,
  type GraveyardOverview,
  type RepeatOffender,
  type PersonCompaniesResponse,
  type InProcessCase,
  type InProcessResponse,
  type DirectorAgingRow,
  type DirectorAgingResponse,
} from "@/lib/api";
import { fmtEur, fmtNumber, fmtCbe } from "@/lib/format";
import {
  Skull,
  BarChart3,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertTriangle,
  Building2,
  Users,
  Search,
  Trophy,
  Activity,
  Clock,
  Gavel,
  UserCheck,
  UserX,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

/* ============================================================
   Helpers
   ============================================================ */

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

function ChartSkeleton({ height = "h-64" }: { height?: string }) {
  return (
    <div className={`${height} animate-pulse rounded-lg bg-slate-100 flex items-center justify-center`}>
      <BarChart3 className="h-10 w-10 text-slate-300" />
    </div>
  );
}

function SectionHeader({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-rose-400 pl-2 mb-4 flex items-center gap-1.5">
      {icon}{children}
    </h2>
  );
}

const STATUS_COLORS = [
  "#f43f5e", "#fb923c", "#f59e0b", "#a78bfa",
  "#64748b", "#94a3b8", "#cbd5e1",
];

const SITUATION_COLORS = [
  "#e11d48", "#f43f5e", "#fb7185", "#fda4af",
  "#c084fc", "#a78bfa", "#818cf8", "#93c5fd",
  "#94a3b8", "#cbd5e1",
];

const DECADE_COLOR = "#f43f5e";

/* ============================================================
   Sorting
   ============================================================ */

type SortKey = "name" | "failed_count" | "active_count";
type SortDir = "asc" | "desc";

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <ArrowUpDown className="ml-1 inline h-3 w-3 text-slate-300" />;
  return dir === "asc"
    ? <ArrowUp className="ml-1 inline h-3 w-3 text-rose-600" />
    : <ArrowDown className="ml-1 inline h-3 w-3 text-rose-600" />;
}

/* ============================================================
   Custom tooltips
   ============================================================ */

function StatusTooltip({ active, payload }: any) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-lg text-sm">
      <p className="font-semibold text-slate-800 mb-1">{d.label}</p>
      <p className="text-slate-600">Companies: <span className="font-semibold">{fmtNumber(d.count)}</span></p>
    </div>
  );
}

function DecadeTooltip({ active, payload }: any) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-lg text-sm">
      <p className="font-semibold text-slate-800 mb-1">{d.decade}s</p>
      <p className="text-slate-600">Closed companies: <span className="font-semibold">{fmtNumber(d.count)}</span></p>
    </div>
  );
}

/* ============================================================
   Scorebord Tab — repeat offenders, finished bankruptcies only
   ============================================================ */

function ScorebordTab() {
  const [offenders, setOffenders] = useState<RepeatOffender[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("failed_count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [minFailed, setMinFailed] = useState(3);
  const [nameFilter, setNameFilter] = useState("");
  const [expandedName, setExpandedName] = useState<string | null>(null);
  const [personData, setPersonData] = useState<PersonCompaniesResponse | null>(null);
  const [loadingPerson, setLoadingPerson] = useState(false);

  useEffect(() => {
    setLoading(true);
    getRepeatOffenders(minFailed, 200)
      .then((d) => setOffenders(d.offenders))
      .catch((e) => console.error("Scorebord load failed:", e))
      .finally(() => setLoading(false));
  }, [minFailed]);

  const sorted = useMemo(() => {
    let rows = offenders;
    if (nameFilter.trim()) {
      const q = nameFilter.trim().toUpperCase();
      rows = rows.filter((o) => o.name.toUpperCase().includes(q));
    }
    return [...rows].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = typeof av === "string"
        ? av.localeCompare(bv as string)
        : (av as number) - (bv as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [offenders, sortKey, sortDir, nameFilter]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir(key === "name" ? "asc" : "desc"); }
  }

  async function toggleExpand(name: string) {
    if (expandedName === name) {
      setExpandedName(null);
      setPersonData(null);
      return;
    }
    setExpandedName(name);
    setPersonData(null);
    setLoadingPerson(true);
    try {
      setPersonData(await getPersonFailedCompanies(name));
    } catch (e) {
      console.error("Person load failed:", e);
    } finally {
      setLoadingPerson(false);
    }
  }

  return (
    <div>
      <p className="text-sm text-slate-500 mb-4">
        Track record of directors in companies whose bankruptcy proceedings
        have concluded. Click a row for the full company history.
      </p>

      <div className="flex flex-wrap items-end gap-4 mb-4">
        <div>
          <label className="text-xs font-medium text-slate-500 mb-1 block">Min. finished bankruptcies</label>
          <select
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 focus:border-rose-400 focus:ring-rose-400"
            value={minFailed}
            onChange={(e) => {
              setMinFailed(Number(e.target.value));
              setExpandedName(null);
              setPersonData(null);
            }}
          >
            {[2, 3, 4, 5, 7, 10].map((n) => (
              <option key={n} value={n}>{n}+</option>
            ))}
          </select>
        </div>
        <div className="flex-1 max-w-xs">
          <label className="text-xs font-medium text-slate-500 mb-1 block">Filter by name</label>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
            <Input
              placeholder="Search names..."
              className="pl-8 h-10 md:h-8 text-base md:text-sm"
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
            />
          </div>
        </div>
        <Badge variant="secondary" className="bg-rose-50 text-rose-700 border-rose-200 h-8 px-3">
          {sorted.length} results
        </Badge>
      </div>

      <Card className="bg-white overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50">
              <TableHead className="w-8" />
              <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("name")}>
                Name <SortIcon active={sortKey === "name"} dir={sortDir} />
              </TableHead>
              <TableHead className="text-right cursor-pointer select-none" onClick={() => toggleSort("failed_count")}>
                Finished bankruptcies <SortIcon active={sortKey === "failed_count"} dir={sortDir} />
              </TableHead>
              <TableHead className="text-right cursor-pointer select-none" onClick={() => toggleSort("active_count")}>
                Active <SortIcon active={sortKey === "active_count"} dir={sortDir} />
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <SkeletonRows cols={4} count={10} />
            ) : sorted.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center py-10 text-slate-400">
                  No results
                </TableCell>
              </TableRow>
            ) : (
              sorted.map((o) => (
                <>
                  <TableRow
                    key={o.name}
                    className="cursor-pointer hover:bg-rose-50/40"
                    onClick={() => toggleExpand(o.name)}
                  >
                    <TableCell className="w-8">
                      {expandedName === o.name
                        ? <ChevronDown className="h-4 w-4 text-rose-600" />
                        : <ChevronRight className="h-4 w-4 text-slate-400" />}
                    </TableCell>
                    <TableCell className="font-medium text-slate-900">{o.name}</TableCell>
                    <TableCell className="text-right">
                      <Badge variant="secondary" className="bg-rose-50 text-rose-700 border-rose-200 font-mono">
                        {o.failed_count}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {o.active_count > 0 ? (
                        <Badge variant="secondary" className="bg-emerald-50 text-emerald-700 border-emerald-200 font-mono">
                          {o.active_count}
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="bg-slate-50 text-slate-400 border-slate-200 font-mono">
                          0
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>

                  {expandedName === o.name && (
                    <TableRow key={`${o.name}-detail`}>
                      <TableCell colSpan={4} className="bg-slate-50/80 p-0">
                        <div className="px-4 py-3 space-y-4">
                          {loadingPerson && (
                            <div className="flex items-center gap-2 text-sm text-slate-500">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              Loading company history...
                            </div>
                          )}

                          {!loadingPerson && personData && (
                            <>
                              <div className="flex flex-wrap gap-2">
                                <Badge variant="secondary" className="bg-rose-50 text-rose-700 border-rose-200">
                                  {personData.failed_companies.length} failed
                                </Badge>
                                <Badge variant="secondary" className="bg-emerald-50 text-emerald-700 border-emerald-200">
                                  {personData.active_companies.length} active
                                </Badge>
                              </div>

                              {personData.failed_companies.length > 0 && (
                                <div>
                                  <h4 className="text-xs font-bold uppercase tracking-wide text-rose-500 mb-2">
                                    Failed Companies
                                  </h4>
                                  <div className="rounded-lg border bg-white overflow-x-auto">
                                    <Table>
                                      <TableHeader>
                                        <TableRow>
                                          <TableHead>Company</TableHead>
                                          <TableHead className="hidden md:table-cell">Role</TableHead>
                                          <TableHead>Status</TableHead>
                                          <TableHead className="hidden md:table-cell">Situation</TableHead>
                                          <TableHead className="text-right">Revenue</TableHead>
                                          <TableHead className="hidden md:table-cell text-right">EBITDA</TableHead>
                                        </TableRow>
                                      </TableHeader>
                                      <TableBody>
                                        {personData.failed_companies.map((c, idx) => (
                                          <TableRow key={`${c.enterprise_number}-${idx}`}>
                                            <TableCell>
                                              <Link
                                                href={`/company/${c.enterprise_number}`}
                                                className="text-brand hover:text-[color:var(--brand-ink)] hover:underline font-medium text-sm"
                                              >
                                                {c.company_name}
                                              </Link>
                                              <p className="text-[10px] text-slate-400 font-mono">{fmtCbe(c.enterprise_number)}</p>
                                            </TableCell>
                                            <TableCell className="hidden md:table-cell text-sm text-slate-600">
                                              {c.role_label || c.role || "\u2014"}
                                            </TableCell>
                                            <TableCell>
                                              <Badge variant="secondary" className="bg-rose-50 text-rose-600 border-rose-200 text-xs">
                                                {c.status_label || c.status || "\u2014"}
                                              </Badge>
                                            </TableCell>
                                            <TableCell className="hidden md:table-cell text-sm text-slate-600">
                                              {c.situation_label || "\u2014"}
                                            </TableCell>
                                            <TableCell className="text-right font-mono text-sm">
                                              {fmtEur(c.revenue)}
                                            </TableCell>
                                            <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                              {fmtEur(c.ebitda)}
                                            </TableCell>
                                          </TableRow>
                                        ))}
                                      </TableBody>
                                    </Table>
                                  </div>
                                </div>
                              )}

                              {personData.active_companies.length > 0 && (
                                <div>
                                  <h4 className="text-xs font-bold uppercase tracking-wide text-emerald-600 mb-2">
                                    Currently Active Companies
                                  </h4>
                                  <div className="rounded-lg border bg-white overflow-x-auto">
                                    <Table>
                                      <TableHeader>
                                        <TableRow>
                                          <TableHead>Company</TableHead>
                                          <TableHead className="hidden md:table-cell">Role</TableHead>
                                          <TableHead className="text-right">Revenue</TableHead>
                                          <TableHead className="hidden md:table-cell text-right">EBITDA</TableHead>
                                          <TableHead className="hidden md:table-cell text-right">FTE</TableHead>
                                        </TableRow>
                                      </TableHeader>
                                      <TableBody>
                                        {personData.active_companies.map((c, idx) => (
                                          <TableRow key={`${c.enterprise_number}-${idx}`}>
                                            <TableCell>
                                              <Link
                                                href={`/company/${c.enterprise_number}`}
                                                className="text-brand hover:text-[color:var(--brand-ink)] hover:underline font-medium text-sm"
                                              >
                                                {c.company_name}
                                              </Link>
                                              <p className="text-[10px] text-slate-400 font-mono">{fmtCbe(c.enterprise_number)}</p>
                                            </TableCell>
                                            <TableCell className="hidden md:table-cell text-sm text-slate-600">
                                              {c.role_label || c.role || "\u2014"}
                                            </TableCell>
                                            <TableCell className="text-right font-mono text-sm">
                                              {fmtEur(c.revenue)}
                                            </TableCell>
                                            <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                              {fmtEur(c.ebitda)}
                                            </TableCell>
                                            <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                              {fmtNumber(c.fte_total)}
                                            </TableCell>
                                          </TableRow>
                                        ))}
                                      </TableBody>
                                    </Table>
                                  </div>
                                </div>
                              )}

                              {personData.failed_companies.length === 0 &&
                                personData.active_companies.length === 0 && (
                                  <p className="text-sm text-slate-400">
                                    No company records found
                                  </p>
                                )}
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </>
              ))
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

/* ============================================================
   In-Process Tab — live bankruptcy / WCO cases with curator col
   ============================================================ */

type InProcessFilter = "all" | "bankruptcy" | "wco";

function InProcessTab() {
  const [data, setData] = useState<InProcessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [caseFilter, setCaseFilter] = useState<InProcessFilter>("all");
  const [nameFilter, setNameFilter] = useState("");

  useEffect(() => {
    setLoading(true);
    const t = caseFilter === "all" ? undefined : caseFilter;
    getInProcessCases(t, 300)
      .then(setData)
      .catch((e) => console.error("In-process load failed:", e))
      .finally(() => setLoading(false));
  }, [caseFilter]);

  const rows = useMemo(() => {
    const all = data?.cases ?? [];
    if (!nameFilter.trim()) return all;
    const q = nameFilter.trim().toUpperCase();
    return all.filter(
      (c) =>
        c.company_name.toUpperCase().includes(q) ||
        (c.curator_name ?? "").toUpperCase().includes(q),
    );
  }, [data, nameFilter]);

  return (
    <div>
      <p className="text-sm text-slate-500 mb-4">
        Companies currently in bankruptcy or judicial reorganisation (WCO).
        Curator assignment comes from Regsol — <span className="italic">not assigned</span> means no
        curator is known (yet).
      </p>

      <div className="flex flex-wrap items-end gap-4 mb-4">
        <div>
          <label className="text-xs font-medium text-slate-500 mb-1 block">Case type</label>
          <select
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 focus:border-rose-400 focus:ring-rose-400"
            value={caseFilter}
            onChange={(e) => setCaseFilter(e.target.value as InProcessFilter)}
          >
            <option value="all">All</option>
            <option value="bankruptcy">Bankruptcy</option>
            <option value="wco">WCO (reorganisation)</option>
          </select>
        </div>
        <div className="flex-1 max-w-xs">
          <label className="text-xs font-medium text-slate-500 mb-1 block">Filter company / curator</label>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
            <Input
              placeholder="Search..."
              className="pl-8 h-10 md:h-8 text-base md:text-sm"
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Summary chips */}
      {!loading && data && (
        <div className="flex flex-wrap gap-2 mb-4">
          <Badge variant="secondary" className="bg-rose-50 text-rose-700 border-rose-200">
            {fmtNumber(data.bankruptcy_count)} bankruptcies
          </Badge>
          <Badge variant="secondary" className="bg-amber-50 text-amber-700 border-amber-200">
            {fmtNumber(data.wco_count)} WCO
          </Badge>
          <Badge variant="secondary" className="bg-emerald-50 text-emerald-700 border-emerald-200">
            {fmtNumber(data.curator_assigned_count)} with curator
          </Badge>
          <Badge variant="secondary" className="bg-slate-50 text-slate-600 border-slate-200">
            {fmtNumber(rows.length)} shown
          </Badge>
        </div>
      )}

      <Card className="bg-white overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Company</TableHead>
                <TableHead>Type</TableHead>
                <TableHead className="hidden md:table-cell">Situation</TableHead>
                <TableHead className="hidden md:table-cell">Opened</TableHead>
                <TableHead className="hidden lg:table-cell">Court</TableHead>
                <TableHead className="hidden md:table-cell">Curator</TableHead>
                <TableHead className="text-right">Revenue</TableHead>
                <TableHead className="hidden md:table-cell text-right">FTE</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <SkeletonRows cols={8} count={10} />
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-10 text-slate-400">
                    No matching cases
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((c: InProcessCase) => (
                  <TableRow key={c.enterprise_number} className="hover:bg-rose-50/40">
                    <TableCell>
                      <Link
                        href={`/company/${c.enterprise_number}`}
                        className="text-brand hover:text-[color:var(--brand-ink)] hover:underline font-medium text-sm"
                      >
                        {c.company_name}
                      </Link>
                      <p className="text-[10px] text-slate-400 font-mono">{fmtCbe(c.enterprise_number)}</p>
                    </TableCell>
                    <TableCell>
                      {c.bucket === "bankruptcy" ? (
                        <Badge variant="secondary" className="bg-rose-50 text-rose-700 border-rose-200">
                          Bankruptcy
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="bg-amber-50 text-amber-700 border-amber-200">
                          WCO
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-sm text-slate-600">
                      {c.situation_label ?? "\u2014"}
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-sm text-slate-600 font-mono">
                      {c.opened_at ?? "\u2014"}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-sm text-slate-600">
                      {c.court ? (
                        <span className="inline-flex items-center gap-1">
                          <Gavel className="h-3 w-3 text-slate-400" />
                          <span className="truncate max-w-[180px]" title={c.court}>{c.court}</span>
                        </span>
                      ) : (
                        <span className="text-slate-400">{"\u2014"}</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {c.curator_name ? (
                        <span className="inline-flex items-center gap-1 text-sm text-slate-800">
                          <UserCheck className="h-3.5 w-3.5 text-emerald-600" />
                          {c.curator_name}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-sm text-slate-400 italic">
                          <UserX className="h-3.5 w-3.5" />
                          Not assigned
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {fmtEur(c.revenue)}
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                      {fmtNumber(c.fte_total)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </Card>
    </div>
  );
}

/* ============================================================
   Director Aging Tab — time before bankruptcy
   ============================================================ */

const AGING_COLS: Array<{
  key: keyof Omit<DirectorAgingRow, "name" | "total">;
  label: string;
  bg: string;
  fg: string;
  border: string;
}> = [
  { key: "at_bankruptcy", label: "≤3m",  bg: "bg-rose-100",    fg: "text-rose-800",    border: "border-rose-300" },
  { key: "within_6m",     label: "3–6m", bg: "bg-rose-50",     fg: "text-rose-700",    border: "border-rose-200" },
  { key: "within_1y",     label: "6–12m",bg: "bg-orange-50",   fg: "text-orange-700",  border: "border-orange-200" },
  { key: "within_2y",     label: "1–2y", bg: "bg-amber-50",    fg: "text-amber-700",   border: "border-amber-200" },
  { key: "within_3y",     label: "2–3y", bg: "bg-yellow-50",   fg: "text-yellow-700",  border: "border-yellow-200" },
  { key: "older",         label: ">3y",  bg: "bg-slate-50",    fg: "text-slate-500",   border: "border-slate-200" },
];

type AgingSortKey = "name" | "total" | keyof Omit<DirectorAgingRow, "name">;

function DirectorAgingTab() {
  const [data, setData] = useState<DirectorAgingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [minTotal, setMinTotal] = useState(2);
  const [nameFilter, setNameFilter] = useState("");
  const [sortKey, setSortKey] = useState<AgingSortKey>("at_bankruptcy");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  useEffect(() => {
    setLoading(true);
    getDirectorAging(minTotal, 300)
      .then(setData)
      .catch((e) => console.error("Director aging load failed:", e))
      .finally(() => setLoading(false));
  }, [minTotal]);

  const rows = useMemo(() => {
    let all = data?.directors ?? [];
    if (nameFilter.trim()) {
      const q = nameFilter.trim().toUpperCase();
      all = all.filter((r) => r.name.toUpperCase().includes(q));
    }
    return [...all].sort((a, b) => {
      const av = (a as any)[sortKey];
      const bv = (b as any)[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = typeof av === "string"
        ? av.localeCompare(bv as string)
        : (av as number) - (bv as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [data, nameFilter, sortKey, sortDir]);

  function toggleSort(key: AgingSortKey) {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir(key === "name" ? "asc" : "desc"); }
  }

  return (
    <div>
      <p className="text-sm text-slate-500 mb-4">
        Directors who were in office in companies that are now bankrupt,
        grouped by how close to the bankruptcy date their mandate still ran.
        &ldquo;≤3m&rdquo; means they were still a director when bankruptcy was
        declared (or left within 3 months of it). Only companies with a known
        Regsol opening date are counted.
      </p>

      <div className="flex flex-wrap items-end gap-4 mb-4">
        <div>
          <label className="text-xs font-medium text-slate-500 mb-1 block">Min. bankruptcies</label>
          <select
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 focus:border-rose-400 focus:ring-rose-400"
            value={minTotal}
            onChange={(e) => setMinTotal(Number(e.target.value))}
          >
            {[1, 2, 3, 4, 5, 7, 10].map((n) => (
              <option key={n} value={n}>{n}+</option>
            ))}
          </select>
        </div>
        <div className="flex-1 max-w-xs">
          <label className="text-xs font-medium text-slate-500 mb-1 block">Filter by name</label>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
            <Input
              placeholder="Search names..."
              className="pl-8 h-10 md:h-8 text-base md:text-sm"
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
            />
          </div>
        </div>
        <Badge variant="secondary" className="bg-rose-50 text-rose-700 border-rose-200 h-8 px-3">
          {rows.length} results
        </Badge>
      </div>

      <Card className="bg-white overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("name")}>
                  Name <SortIcon active={sortKey === "name"} dir={sortDir} />
                </TableHead>
                <TableHead className="text-right cursor-pointer select-none" onClick={() => toggleSort("total")}>
                  Total <SortIcon active={sortKey === "total"} dir={sortDir} />
                </TableHead>
                {AGING_COLS.map((col) => (
                  <TableHead
                    key={col.key}
                    className="text-right cursor-pointer select-none"
                    onClick={() => toggleSort(col.key)}
                  >
                    {col.label} <SortIcon active={sortKey === col.key} dir={sortDir} />
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <SkeletonRows cols={2 + AGING_COLS.length} count={10} />
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={2 + AGING_COLS.length} className="text-center py-10 text-slate-400">
                    No results — not enough Regsol coverage with dated openings.
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((r) => (
                  <TableRow key={r.name} className="hover:bg-rose-50/40">
                    <TableCell className="font-medium text-slate-900">{r.name}</TableCell>
                    <TableCell className="text-right">
                      <Badge variant="secondary" className="bg-slate-100 text-slate-700 border-slate-300 font-mono">
                        {r.total}
                      </Badge>
                    </TableCell>
                    {AGING_COLS.map((col) => {
                      const v = r[col.key];
                      return (
                        <TableCell key={col.key} className="text-right">
                          {v > 0 ? (
                            <Badge variant="secondary" className={`${col.bg} ${col.fg} ${col.border} font-mono`}>
                              {v}
                            </Badge>
                          ) : (
                            <span className="text-slate-300 font-mono text-sm">0</span>
                          )}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </Card>
    </div>
  );
}

/* ============================================================
   Main Page
   ============================================================ */

type TabKey = "scorebord" | "in-process" | "aging";

export default function FallenHeroesPage() {
  const [overview, setOverview] = useState<GraveyardOverview | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [tab, setTab] = useState<TabKey>("scorebord");

  useEffect(() => {
    setLoadingOverview(true);
    getGraveyardOverview()
      .then(setOverview)
      .catch((err) => console.error("Graveyard overview failed:", err))
      .finally(() => setLoadingOverview(false));
  }, []);

  const totalCompanies = overview ? overview.active_count + overview.non_active_count : 0;
  const pctNonActive = totalCompanies > 0 ? ((overview?.non_active_count ?? 0) / totalCompanies * 100) : 0;
  const topStatus = overview?.by_status?.[0];
  const topSituation = overview?.by_situation?.[0];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Demo banner */}
      <div className="bg-amber-50 border-b border-amber-200">
        <div className="mx-auto max-w-6xl px-4 py-2.5 flex items-center gap-2 text-[12px] text-amber-800">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            <strong>Demo page</strong> &middot; Fallen Heroes is a research playground built on top of DataSnoop&apos;s data.
            It is not part of the official DataSnoop offering.
          </span>
        </div>
      </div>

      {/* Header */}
      <div className="bg-slate-900 text-white">
        <div className="mx-auto max-w-6xl px-4 py-8">
          <div className="flex items-center gap-3 mb-2">
            <Skull className="h-7 w-7 text-rose-400" />
            <h1 className="text-2xl font-bold tracking-tight">Fallen Heroes</h1>
          </div>
          <p className="text-slate-400 text-sm max-w-xl">
            Non-active and failed Belgian companies. Track repeat directors,
            live insolvency proceedings, and director-aging patterns in
            companies that went bankrupt.
          </p>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 py-6 space-y-8">

        {/* Tabs */}
        <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
          <TabsList className="w-full max-w-xl">
            <TabsTrigger value="scorebord">
              <Trophy className="h-3.5 w-3.5 mr-1.5" />
              Scorebord
            </TabsTrigger>
            <TabsTrigger value="in-process">
              <Activity className="h-3.5 w-3.5 mr-1.5" />
              In Process
            </TabsTrigger>
            <TabsTrigger value="aging">
              <Clock className="h-3.5 w-3.5 mr-1.5" />
              Director Aging
            </TabsTrigger>
          </TabsList>

          <TabsContent value="scorebord" className="pt-4">
            <SectionHeader icon={<Users className="h-3.5 w-3.5" />}>
              Scorebord — Historical Bankruptcy Track Record
            </SectionHeader>
            <ScorebordTab />
          </TabsContent>

          <TabsContent value="in-process" className="pt-4">
            <SectionHeader icon={<Activity className="h-3.5 w-3.5" />}>
              Currently in Bankruptcy or WCO
            </SectionHeader>
            <InProcessTab />
          </TabsContent>

          <TabsContent value="aging" className="pt-4">
            <SectionHeader icon={<Clock className="h-3.5 w-3.5" />}>
              Director Aging — Proximity to Bankruptcy
            </SectionHeader>
            <DirectorAgingTab />
          </TabsContent>
        </Tabs>

        {/* Overview KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {loadingOverview ? (
            Array.from({ length: 4 }).map((_, i) => (
              <Card key={i} className="bg-white">
                <CardContent className="pt-4 pb-4">
                  <SkeletonBlock className="h-4 w-20 mb-2" />
                  <SkeletonBlock className="h-8 w-24" />
                </CardContent>
              </Card>
            ))
          ) : (
            <>
              <Card className="bg-white border-rose-200">
                <CardContent className="pt-4 pb-4">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Non-Active Companies</p>
                  <p className="text-2xl font-bold text-rose-600 mt-1">
                    {fmtNumber(overview?.non_active_count)}
                  </p>
                </CardContent>
              </Card>
              <Card className="bg-white">
                <CardContent className="pt-4 pb-4">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">% of All Companies</p>
                  <p className="text-2xl font-bold text-slate-800 mt-1">
                    {pctNonActive.toFixed(1)}%
                  </p>
                </CardContent>
              </Card>
              <Card className="bg-white">
                <CardContent className="pt-4 pb-4">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Top Status</p>
                  <p className="text-lg font-bold text-slate-800 mt-1">
                    {topStatus?.label ?? "—"}
                  </p>
                  <p className="text-xs text-slate-400">{fmtNumber(topStatus?.count)} companies</p>
                </CardContent>
              </Card>
              <Card className="bg-white">
                <CardContent className="pt-4 pb-4">
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Top Situation</p>
                  <p className="text-lg font-bold text-slate-800 mt-1">
                    {topSituation?.label ?? "—"}
                  </p>
                  <p className="text-xs text-slate-400">{fmtNumber(topSituation?.count)} companies</p>
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {/* Charts */}
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="bg-white">
            <CardContent className="pt-5 pb-4">
              <SectionHeader icon={<AlertTriangle className="h-3.5 w-3.5" />}>
                By Status
              </SectionHeader>
              {loadingOverview ? (
                <ChartSkeleton />
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart
                    data={overview?.by_status ?? []}
                    layout="vertical"
                    margin={{ left: 10, right: 20, top: 5, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} tickFormatter={(v) => fmtNumber(v)} />
                    <YAxis
                      type="category"
                      dataKey="label"
                      tick={{ fontSize: 11, fill: "#334155" }}
                      width={120}
                    />
                    <Tooltip content={<StatusTooltip />} />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                      {(overview?.by_status ?? []).map((_, idx) => (
                        <Cell key={idx} fill={STATUS_COLORS[idx % STATUS_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          <Card className="bg-white">
            <CardContent className="pt-5 pb-4">
              <SectionHeader icon={<Building2 className="h-3.5 w-3.5" />}>
                By Juridical Situation
              </SectionHeader>
              {loadingOverview ? (
                <ChartSkeleton />
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart
                    data={(overview?.by_situation ?? []).slice(0, 10)}
                    layout="vertical"
                    margin={{ left: 10, right: 20, top: 5, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} tickFormatter={(v) => fmtNumber(v)} />
                    <YAxis
                      type="category"
                      dataKey="label"
                      tick={{ fontSize: 11, fill: "#334155" }}
                      width={160}
                    />
                    <Tooltip content={<StatusTooltip />} />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                      {(overview?.by_situation ?? []).slice(0, 10).map((_, idx) => (
                        <Cell key={idx} fill={SITUATION_COLORS[idx % SITUATION_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="bg-white">
          <CardContent className="pt-5 pb-4">
            <SectionHeader icon={<BarChart3 className="h-3.5 w-3.5" />}>
              Closed Companies by Founding Decade
            </SectionHeader>
            {loadingOverview ? (
              <ChartSkeleton height="h-48" />
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={overview?.by_decade ?? []}
                  margin={{ left: 10, right: 20, top: 5, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis
                    dataKey="decade"
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    tickFormatter={(v) => `${v}s`}
                  />
                  <YAxis tick={{ fontSize: 11, fill: "#64748b" }} tickFormatter={(v) => fmtNumber(v)} />
                  <Tooltip content={<DecadeTooltip />} />
                  <Bar dataKey="count" fill={DECADE_COLOR} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <p className="text-xs text-slate-400 text-center pb-4">
          Data sourced from KBO registry, NBB annual accounts and Regsol. Name
          matching is approximate — different people with identical names may be
          grouped together.
        </p>
      </div>
    </div>
  );
}
