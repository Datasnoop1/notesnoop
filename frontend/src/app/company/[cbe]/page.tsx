"use client";

import React, { useState, useEffect, useCallback, use } from "react";
import Link from "next/link";
import ExportButtons from "@/components/export-buttons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  getCompanyDetail,
  getCompanyFinancials,
  getCompanyStructure,
  addFavourite,
  removeFavourite,
  loadCompanyNBB,
  loadPublications,
  getSectorBenchmark,
  getSimilarCompanies,
  addPeopleFavourite,
  enrichCompany,
  getEnrichment,
  enrichPerson,
  getPersonEnrichment,
  scrapeCompanyWebsite,
  scrapeCompanyLinkedIn,
} from "@/lib/api";
import type { SectorBenchmark } from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import { useRouter } from "next/navigation";
import {
  Star,
  ArrowLeft,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Users,
  Network,
  Briefcase,
  GitBranch,
  FileText,
  Download,
  Shield,
  Scale,
  BarChart3,
  DollarSign,
  TrendingUp,
  Percent,
  Activity,
  Calendar,
  UserCheck,
  Newspaper,
  Loader2,
  CheckCircle2,
  XCircle,
  FileSpreadsheet,
  FileDown,
  Sparkles,
  Globe,
} from "lucide-react";
import { SearchableText, GoogleSearchLink } from "@/components/google-search-link";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { derivePnlData, deriveCashFlowData, deriveBalanceSheetData, deriveCreditData } from "@/lib/export/data";
import type { ExportData } from "@/lib/export/types";
import dynamic from "next/dynamic";

const NetworkGraph = dynamic(() => import("@/components/network-graph"), {
  ssr: false,
  loading: () => <div className="py-8 text-center text-sm text-slate-400">Loading graph...</div>,
});
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

/* ---------- types ---------- */

interface CompanyDetail {
  enterprise_number: string;
  status: string;
  start_date: string | null;
  jf_label: string | null;
  name: string | null;
  zipcode: string | null;
  city: string | null;
  municipality: string | null;
  street: string | null;
  house_number: string | null;
  nace_code: string | null;
  nace_label: string | null;
  website: string | null;
}

interface FinancialRow {
  fiscal_year: number;
  deposit_key: string | null;
  filing_model: string | null;
  revenue: number | null;
  gross_margin: number | null;
  ebit: number | null;
  da: number | null;
  ebitda: number | null;
  net_profit: number | null;
  equity: number | null;
  lt_debt: number | null;
  lt_financial_debt: number | null;
  st_financial_debt: number | null;
  cash: number | null;
  total_assets: number | null;
  fixed_assets: number | null;
  inventories: number | null;
  trade_receivables: number | null;
  trade_payables: number | null;
  financial_charges: number | null;
  current_investments: number | null;
  fte_total: number | null;
  personnel_costs: number | null;
  ebitda_margin_pct: number | null;
}

interface Administrator {
  name: string;
  role: string;
  role_label: string;
  mandate_start: string | null;
  mandate_end: string | null;
  identifier: string | null;
  person_type: string | null;
}

interface Shareholder {
  name: string;
  ownership_pct: number | null;
  shareholder_type: string | null;
  identifier: string | null;
  fiscal_year: string | null;
}

interface ParticipatingInterest {
  name: string;
  ownership_pct: number | null;
  country: string | null;
  identifier: string | null;
  fiscal_year: string | null;
}

interface StaatsbladPub {
  pub_date: string;
  pub_type: string | null;
  reference: string | null;
  pdf_url: string | null;
}

interface StructureData {
  administrators: Administrator[];
  participating_interests: ParticipatingInterest[];
  shareholders: Shareholder[];
  staatsblad_publications: StaatsbladPub[];
}

interface FinancialsData {
  summary: FinancialRow[];
  rubric_data?: Record<string, Record<string, number | null>>;
}

/* ---------- helper to clean CBE from identifier ---------- */

function cleanCbe(id: string | null): string | null {
  if (!id) return null;
  const c = id.replace(/\./g, "").replace(/ /g, "").trim();
  return /^\d{10}$/.test(c) ? c : null;
}

/* ---------- publication type mapping ---------- */

const PUB_TYPE_MAP: Record<string, { label: string; color: string; summary: string }> = {
  "ONTSLAGEN - BENOEMINGEN": {
    label: "Board",
    color: "bg-blue-100 text-blue-700",
    summary: "Board changes: resignations and appointments",
  },
  "OPRICHTING": {
    label: "Formation",
    color: "bg-green-100 text-green-700",
    summary: "Company formation / incorporation",
  },
  "STATUTENWIJZIGING": {
    label: "Statutes",
    color: "bg-purple-100 text-purple-700",
    summary: "Amendment of articles of association",
  },
  "ONTBINDING": {
    label: "Dissolution",
    color: "bg-rose-50 text-rose-500",
    summary: "Dissolution",
  },
  "VEREFFENING": {
    label: "Liquidation",
    color: "bg-rose-50 text-rose-500",
    summary: "Liquidation",
  },
  "FUSIE": {
    label: "Merger",
    color: "bg-amber-100 text-amber-700",
    summary: "Merger",
  },
  "SPLITSING": {
    label: "Demerger",
    color: "bg-amber-100 text-amber-700",
    summary: "Demerger / split",
  },
  "ZETELVERPLAATSING": {
    label: "Relocation",
    color: "bg-cyan-100 text-cyan-700",
    summary: "Registered office relocation",
  },
  "KAPITAALVERHOGING": {
    label: "Cap. increase",
    color: "bg-emerald-100 text-emerald-700",
    summary: "Capital increase",
  },
  "KAPITAALVERMINDERING": {
    label: "Cap. decrease",
    color: "bg-orange-100 text-orange-700",
    summary: "Capital decrease",
  },
  "JAARREKENING": {
    label: "Accounts",
    color: "bg-slate-100 text-slate-600",
    summary: "Annual accounts filing",
  },
};

/* ---------- skeleton ---------- */

function HeaderSkeleton() {
  return (
    <div className="space-y-3 py-6">
      <div className="h-7 w-80 animate-pulse rounded bg-slate-200" />
      <div className="h-4 w-48 animate-pulse rounded bg-slate-200" />
      <div className="flex gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-4 w-32 animate-pulse rounded bg-slate-200"
          />
        ))}
      </div>
    </div>
  );
}

function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 10 }).map((_, j) => (
            <TableCell key={j}>
              <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/* ---------- custom tooltip for chart ---------- */

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-white p-3 shadow-md">
      <p className="mb-1 text-xs font-semibold text-slate-700">FY {label}</p>
      {payload.map((entry) => (
        <p key={entry.name} className="text-xs" style={{ color: entry.color }}>
          {entry.name}: {fmtEur(entry.value)}
        </p>
      ))}
    </div>
  );
}

/* ---------- Formula tooltip (credit tab) ---------- */

function FormulaTooltip({ children, formula, detail }: { children: React.ReactNode; formula: string; detail?: string }) {
  return (
    <div className="group/tip relative inline-block">
      {children}
      <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-slate-800 text-white text-[10px] rounded-lg shadow-lg opacity-0 pointer-events-none group-hover/tip:opacity-100 transition-opacity duration-100 whitespace-nowrap">
        <div className="font-medium">{formula}</div>
        {detail && <div className="text-slate-300 font-mono mt-0.5">{detail}</div>}
        <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-800" />
      </div>
    </div>
  );
}

/* ---------- YoY delta helper ---------- */

function renderDelta(current: number | null, previous: number | null): React.ReactNode {
  if (current == null || previous == null || previous === 0) return null;
  const abs = current - previous;
  const pct = (abs / Math.abs(previous)) * 100;
  const sign = abs >= 0 ? "+" : "";
  const color = abs >= 0 ? "text-emerald-400" : "text-rose-400";
  const arrow = abs >= 0 ? "▲" : "▼";
  return (
    <div className={`${color} leading-tight`}>
      <div className="text-[10px] font-mono">{sign}{fmtEur(abs)}</div>
      <div className="text-[9px] font-medium">{arrow} {sign}{pct.toFixed(1)}%</div>
    </div>
  );
}

/** Render delta column headers between year columns */
function renderDeltaHeaders(years: number[]): React.ReactNode[] {
  const headers: React.ReactNode[] = [];
  for (let i = 0; i < years.length; i++) {
    headers.push(
      <th key={`y-${years[i]}`} className="px-3 py-2 text-right text-slate-400 font-medium min-w-[80px]">
        FY{years[i]}
      </th>
    );
    if (i < years.length - 1) {
      headers.push(
        <th key={`d-${years[i]}`} className="px-1 py-2 text-center text-slate-400 font-normal w-[70px] text-[9px]">
          Δ
        </th>
      );
    }
  }
  return headers;
}

/** Render value cells with delta columns between years */
function renderValueCellsWithDeltas(
  values: (number | null)[],
  formatter: (v: number | null) => React.ReactNode,
  showDelta = true,
): React.ReactNode[] {
  const cells: React.ReactNode[] = [];
  for (let i = 0; i < values.length; i++) {
    cells.push(
      <td key={`v-${i}`} className="px-3 py-1 text-right font-mono text-xs">
        {formatter(values[i])}
      </td>
    );
    if (i < values.length - 1) {
      cells.push(
        <td key={`d-${i}`} className="px-1 py-1 text-center">
          {showDelta ? renderDelta(values[i + 1], values[i]) : null}
        </td>
      );
    }
  }
  return cells;
}

/* ---------- generic CSV export helper ---------- */

function downloadCsv(filename: string, headers: string[], rows: (string | number | null)[][]) {
  const csvContent = [
    headers.join(","),
    ...rows.map((r) => r.map((v) => (v == null ? "" : String(v).includes(",") ? `"${v}"` : v)).join(",")),
  ].join("\n");
  const blob = new Blob([csvContent], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/* ---------- main component ---------- */

export default function CompanyDetailPage(props: {
  params: Promise<{ cbe: string }>;
}) {
  const { cbe } = use(props.params);

  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [financials, setFinancials] = useState<FinancialsData | null>(null);
  const [structure, setStructure] = useState<StructureData | null>(null);
  const [benchmark, setBenchmark] = useState<SectorBenchmark | null>(null);
  const [similarCompanies, setSimilarCompanies] = useState<{ enterprise_number: string; name: string; city: string; revenue: number | null; ebitda: number | null; fte_total: number | null; fiscal_year: number }[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [isFavourite, setIsFavourite] = useState(false);
  const [activeTab, setActiveTab] = useState("summary");
  const [nbbLoading, setNbbLoading] = useState(false);
  const [nbbResult, setNbbResult] = useState<"success" | "error" | "no-data" | null>(null);
  const nbbAutoTriggered = React.useRef(false);
  const router = useRouter();

  /* ── Auto-load overlay state ── */
  type LoadStage = { label: string; status: "pending" | "active" | "done" | "error" };
  const [loadOverlay, setLoadOverlay] = useState(false);
  const [loadStages, setLoadStages] = useState<LoadStage[]>([]);
  const [loadStartTime, setLoadStartTime] = useState<number | null>(null);
  const [loadElapsed, setLoadElapsed] = useState(0);

  /* ── AI Enrichment state ── */
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [personEnrichments, setPersonEnrichments] = useState<Record<string, { summary: string; loading: boolean }>>({});

  /* ── Website & LinkedIn AI Insights state ── */
  const [websiteScrape, setWebsiteScrape] = useState<{ summary: string; products: string; employees: string; key_people: string; website_url: string } | null>(null);
  const [websiteScrapeLoading, setWebsiteScrapeLoading] = useState(false);
  const [websiteError, setWebsiteError] = useState<string | null>(null);
  const [linkedinScrape, setLinkedinScrape] = useState<{ summary: string; employee_count: string; industry: string; specialties: string; linkedin_url: string } | null>(null);
  const [linkedinScrapeLoading, setLinkedinScrapeLoading] = useState(false);
  const [linkedinError, setLinkedinError] = useState<string | null>(null);

  /* ── Collapsible section state ── */
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const toggleSection = (key: string) =>
    setCollapsedSections((prev) => ({ ...prev, [key]: !prev[key] }));

  /* Elapsed timer for load overlay */
  useEffect(() => {
    if (!loadStartTime) return;
    const interval = setInterval(() => setLoadElapsed(Math.floor((Date.now() - loadStartTime) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [loadStartTime]);

  /* ── Check for existing AI enrichment on load ── */
  useEffect(() => {
    getEnrichment(cbe)
      .then((data) => {
        if (data && data.summary) setAiSummary(data.summary);
        // Restore existing website enrichment
        if (data && data.website_summary) {
          try {
            const parsed = typeof data.website_summary === "string"
              ? JSON.parse(data.website_summary)
              : data.website_summary;
            if (parsed && typeof parsed === "object") {
              setWebsiteScrape({
                summary: parsed.summary || "",
                products: parsed.products || "",
                employees: parsed.employees || "",
                key_people: parsed.key_people || "",
                website_url: data.website_url || "",
              });
            }
          } catch {
            // website_summary wasn't valid JSON — skip
          }
        }
        // Restore existing LinkedIn enrichment
        if (data && data.linkedin_summary) {
          try {
            const parsed = typeof data.linkedin_summary === "string"
              ? JSON.parse(data.linkedin_summary)
              : data.linkedin_summary;
            if (parsed && typeof parsed === "object") {
              setLinkedinScrape({
                summary: parsed.summary || "",
                employee_count: parsed.employee_count || "",
                industry: parsed.industry || "",
                specialties: parsed.specialties || "",
                linkedin_url: parsed.linkedin_url || "",
              });
            }
          } catch {
            // linkedin_summary wasn't valid JSON — skip
          }
        }
      })
      .catch(() => {});
  }, [cbe]);

  useEffect(() => {
    setLoading(true);
    nbbAutoTriggered.current = false;
    Promise.all([
      getCompanyDetail(cbe),
      getCompanyFinancials(cbe),
      getCompanyStructure(cbe),
    ])
      .then(async ([d, f, s]) => {
        setDetail(d as unknown as CompanyDetail);
        setFinancials(f as unknown as FinancialsData);
        setStructure(s as unknown as StructureData);
        setLoading(false);

        const fin = f as unknown as FinancialsData;
        const str = s as unknown as StructureData;
        const needsFinancials = fin && fin.summary && fin.summary.length === 0;
        const needsPublications = !str?.staatsblad_publications?.length;

        if ((needsFinancials || needsPublications) && !nbbAutoTriggered.current) {
          nbbAutoTriggered.current = true;

          // Build loading stages
          const stages: LoadStage[] = [];
          if (needsFinancials) {
            stages.push({ label: "Gathering financial data", status: "pending" });
            stages.push({ label: "Processing and storing data", status: "pending" });
          }
          if (needsPublications) {
            stages.push({ label: "Loading publications", status: "pending" });
          }
          stages.push({ label: "Done", status: "pending" });

          setLoadStages(stages);
          setLoadOverlay(true);
          setLoadStartTime(Date.now());
          setNbbLoading(true);

          let stageIdx = 0;
          const advance = (status: "done" | "error" = "done") => {
            setLoadStages((prev) => {
              const next = [...prev];
              next[stageIdx] = { ...next[stageIdx], status };
              if (stageIdx + 1 < next.length) next[stageIdx + 1] = { ...next[stageIdx + 1], status: "active" };
              return next;
            });
            stageIdx++;
          };

          // Start first stage
          setLoadStages((prev) => { const n = [...prev]; n[0] = { ...n[0], status: "active" }; return n; });

          // Load financials
          if (needsFinancials) {
            try {
              const data = await loadCompanyNBB(cbe);
              advance();
              if (data.rubrics_loaded > 0) {
                // Refetch financials AND structure (admins, shareholders, subsidiaries)
                const [newF, newS] = await Promise.all([
                  getCompanyFinancials(cbe),
                  getCompanyStructure(cbe),
                ]);
                setFinancials(newF as unknown as FinancialsData);
                setStructure(newS as unknown as StructureData);
                setNbbResult("success");
              } else {
                setNbbResult("no-data");
              }
              advance();
            } catch {
              advance("error");
              advance("error");
              setNbbResult("error");
            }
          }

          // Load publications
          if (needsPublications) {
            try {
              await loadPublications(cbe);
              const newS = await getCompanyStructure(cbe);
              setStructure(newS as unknown as StructureData);
              advance();
            } catch {
              advance("error");
            }
          }

          // Mark done
          setLoadStages((prev) => {
            const n = [...prev];
            n[n.length - 1] = { ...n[n.length - 1], status: "done" };
            return n;
          });
          setNbbLoading(false);
          setLoadStartTime(null);

          // Auto-dismiss overlay after 3 seconds
          setTimeout(() => setLoadOverlay(false), 3000);
        }
      })
      .catch((err) => {
        console.error("Failed to load company data:", err);
        setLoading(false);
      });
  }, [cbe]);

  const toggleFavourite = useCallback(async () => {
    try {
      if (isFavourite) {
        await removeFavourite(cbe);
        setIsFavourite(false);
      } else {
        await addFavourite(cbe);
        setIsFavourite(true);
      }
    } catch {
      // Requires login — silently fail
    }
  }, [cbe, isFavourite]);

  const handleTabChange = useCallback(
    (value: any) => {
      if (typeof value === "string") {
        setActiveTab(value);
        // Lazy-load benchmark on first visit
        if (value === "benchmark") {
          if (!benchmark) {
            getSectorBenchmark(cbe).then(setBenchmark).catch(() => {});
          }
        }
        // Lazy-load similar companies on first visit
        if (value === "similar") {
          if (!similarCompanies) {
            getSimilarCompanies(cbe).then(setSimilarCompanies).catch(() => setSimilarCompanies([]));
          }
        }
      }
    },
    [cbe, benchmark, similarCompanies]
  );

  /* ── Full profile export handlers ── */
  const [exporting, setExporting] = useState(false);

  const buildExportData = useCallback((): ExportData | null => {
    if (!detail) return null;
    const summary = financials?.summary ?? [];
    return {
      detail: detail as unknown as ExportData["detail"],
      cbe,
      pnl: derivePnlData(summary as any),
      cashFlow: deriveCashFlowData(summary as any),
      balanceSheet: deriveBalanceSheetData(summary as any),
      credit: deriveCreditData(summary as any),
      administrators: (structure?.administrators ?? []) as any,
      shareholders: (structure?.shareholders ?? []) as any,
      participatingInterests: (structure?.participating_interests ?? []) as any,
      benchmark: benchmark as any,
    };
  }, [detail, financials, structure, benchmark, cbe]);

  const handleExportExcel = useCallback(async () => {
    const data = buildExportData();
    if (!data) return;
    setExporting(true);
    try {
      const { generateExcelReport } = await import("@/lib/export/excel");
      await generateExcelReport(data);
    } catch (err) {
      console.error("Excel export failed:", err);
    } finally {
      setExporting(false);
    }
  }, [buildExportData]);

  const handleExportPdf = useCallback(async () => {
    const data = buildExportData();
    if (!data) return;
    setExporting(true);
    try {
      const { generatePdfReport } = await import("@/lib/export/pdf");
      await generatePdfReport(data);
    } catch (err) {
      console.error("PDF export failed:", err);
    } finally {
      setExporting(false);
    }
  }, [buildExportData]);

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4">
        <HeaderSkeleton />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 py-16 text-center">
        <p className="text-lg font-medium text-slate-700">Company not found</p>
        <p className="mt-1 text-sm text-slate-500">
          CBE {fmtCbe(cbe)} could not be loaded.
        </p>
        <Link
          href="/company"
          className="mt-4 inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to search
        </Link>
      </div>
    );
  }

  const addressParts = [
    detail.street,
    detail.house_number,
    [detail.zipcode, detail.city].filter(Boolean).join(" "),
  ].filter(Boolean);
  const address = addressParts.length > 0 ? addressParts.join(", ") : null;

  /* Chart data */
  const chartData = (financials?.summary ?? []).map((r) => ({
    fy: String(r.fiscal_year),
    Revenue: r.revenue,
    EBITDA: r.ebitda,
  }));

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-4">
      {/* Back link */}
      <Link
        href="/company"
        className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-600"
      >
        <ArrowLeft className="h-3 w-3" /> Back to search
      </Link>

      {/* ━━━ Company Header ━━━ */}
      <div className="mb-6">
        {/* Top row: name + actions */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-slate-900">
              <SearchableText text={detail.name || fmtCbe(cbe)} mapsQuery={address || undefined}>
                {detail.name || fmtCbe(cbe)}
              </SearchableText>
            </h1>
            {/* Single info line: status dot + CBE | address | website | NACE */}
            <div className="mt-0.5 flex flex-wrap items-center text-xs text-slate-400">
              {(() => {
                const parts: React.ReactNode[] = [];
                // CBE with status dot
                parts.push(
                  <span key="cbe" className="inline-flex items-center gap-1.5">
                    <span className={`inline-block h-1.5 w-1.5 rounded-full ${detail.status === "AC" ? "bg-emerald-500" : "bg-red-400"}`} />
                    <span className="font-mono">CBE {fmtCbe(cbe)}</span>
                  </span>
                );
                if (address) parts.push(<GoogleSearchLink key="addr" query={address} type="maps">{address}</GoogleSearchLink>);
                // Website as clickable link
                if (detail.website) {
                  parts.push(
                    <a
                      key="web"
                      href={detail.website.startsWith("http") ? detail.website : `https://${detail.website}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-indigo-500 hover:text-indigo-700 transition-colors"
                    >
                      {detail.website.replace(/^https?:\/\//, "")}
                    </a>
                  );
                }
                if (detail.nace_code) {
                  parts.push(
                    <span key="nace">
                      NACE {detail.nace_code}{detail.nace_label && detail.nace_label !== detail.nace_code ? ` — ${detail.nace_label}` : ""}
                    </span>
                  );
                }
                return parts.map((part, idx) => (
                  <span key={idx} className="inline-flex items-center">
                    {part}
                    {idx < parts.length - 1 && <span className="mx-1.5 text-slate-300">|</span>}
                  </span>
                ));
              })()}
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0 no-print">
            <Button
              variant="outline"
              size="sm"
              onClick={toggleFavourite}
              title={isFavourite ? "Remove from favourites" : "Add to favourites"}
              className="h-9 w-9 md:h-7 md:w-7 p-0 text-slate-400 hover:text-yellow-500 border-slate-200"
            >
              <Star
                className={`h-4 w-4 md:h-3.5 md:w-3.5 ${
                  isFavourite
                    ? "fill-yellow-400 text-yellow-500"
                    : ""
                }`}
              />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                // Switch to similar tab and lazy-load if needed
                if (!similarCompanies) {
                  getSimilarCompanies(cbe).then(setSimilarCompanies).catch(() => setSimilarCompanies([]));
                }
                setActiveTab("similar");
              }}
              className="h-9 md:h-7 text-[11px] text-slate-500 border-slate-200 hover:border-slate-300 px-2.5 md:px-2"
            >
              <Users className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1" />
              Find similar
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const existing = JSON.parse(sessionStorage.getItem("compare_companies") || "[]");
                if (!existing.includes(cbe)) {
                  existing.push(cbe);
                  sessionStorage.setItem("compare_companies", JSON.stringify(existing));
                }
                router.push("/compare");
              }}
              className="h-9 md:h-7 text-[11px] text-slate-500 border-slate-200 hover:border-slate-300 px-2.5 md:px-2"
            >
              <Scale className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1" />
              Compare
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger
                disabled={exporting}
                className="inline-flex items-center h-9 md:h-7 text-[11px] text-slate-500 border border-slate-200 hover:border-slate-300 px-2.5 md:px-2 rounded-md bg-white cursor-pointer"
              >
                {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <FileDown className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1" />}
                Export
                <ChevronDown className="w-3 h-3 ml-0.5" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={handleExportExcel} className="text-xs cursor-pointer">
                  <FileSpreadsheet className="w-4 h-4 mr-2 text-emerald-600" />
                  Export to Excel
                </DropdownMenuItem>
                <DropdownMenuItem onClick={handleExportPdf} className="text-xs cursor-pointer">
                  <FileText className="w-4 h-4 mr-2 text-rose-500" />
                  Export to PDF
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* KPI cards */}
      </div>

      {/* ━━━ Auto-load overlay (centered) ━━━ */}
      {loadOverlay && (
        <>
          <div className="fixed inset-0 z-40 bg-black/10 backdrop-blur-[1px]" />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="w-full max-w-[380px] rounded-2xl border border-slate-200 bg-white shadow-2xl p-6">
              <div className="flex items-center gap-3 mb-4">
                {loadStages.some((s) => s.status === "active") ? (
                  <div className="h-10 w-10 rounded-full bg-indigo-50 flex items-center justify-center">
                    <Loader2 className="h-5 w-5 animate-spin text-indigo-500" />
                  </div>
                ) : (
                  <div className="h-10 w-10 rounded-full bg-emerald-50 flex items-center justify-center">
                    <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                  </div>
                )}
                <div>
                  <span className="text-sm font-semibold text-slate-800 block">
                    {loadStages.every((s) => s.status === "done") ? "Data loaded successfully" : "Gathering data & loading..."}
                  </span>
                  <p className="text-[11px] text-slate-400">
                    {loadStages.every((s) => s.status === "done")
                      ? "All data is now available."
                      : "This may take 30–60 seconds."}
                  </p>
                </div>
                <button onClick={() => setLoadOverlay(false)} className="ml-auto text-slate-400 hover:text-slate-600 text-lg leading-none">×</button>
              </div>
              <div className="space-y-2.5 mb-4">
                {loadStages.map((stage, i) => (
                  <div key={i} className="flex items-center gap-2.5">
                    {stage.status === "done" ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                    ) : stage.status === "active" ? (
                      <Loader2 className="h-4 w-4 animate-spin text-indigo-500 shrink-0" />
                    ) : stage.status === "error" ? (
                      <XCircle className="h-4 w-4 text-rose-400 shrink-0" />
                    ) : (
                      <div className="h-4 w-4 rounded-full border-2 border-slate-200 shrink-0" />
                    )}
                    <span className={`text-sm ${stage.status === "active" ? "text-indigo-600 font-medium" : stage.status === "done" ? "text-slate-500" : stage.status === "error" ? "text-rose-400" : "text-slate-400"}`}>
                      {stage.label}
                    </span>
                  </div>
                ))}
              </div>
              {loadStartTime && (
                <div className="pt-3 border-t border-slate-100">
                  <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                    <div className="h-full bg-indigo-500 rounded-full animate-pulse" style={{ width: `${Math.min(95, loadElapsed * 1.5)}%`, transition: "width 1s ease" }} />
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-slate-400 mt-1.5">
                    <span>{loadElapsed}s elapsed</span>
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-indigo-400 animate-pulse" />
                      Working...
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList variant="line" className="border-b border-slate-100 gap-0 overflow-x-auto scrollbar-none -mx-4 px-4 md:mx-0 md:px-0 md:flex-wrap no-print">
          <TabsTrigger value="summary" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Summary
          </TabsTrigger>
          <TabsTrigger value="pnl" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            P&L
          </TabsTrigger>
          <TabsTrigger value="cashflow" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Cash Flow
          </TabsTrigger>
          <TabsTrigger value="balancesheet" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Balance Sheet
          </TabsTrigger>
          <TabsTrigger value="credit" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Credit
          </TabsTrigger>
          <TabsTrigger value="administrators" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Administrators
          </TabsTrigger>
          <TabsTrigger value="structure" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Structure
          </TabsTrigger>
          <TabsTrigger value="network" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Network
          </TabsTrigger>
          <TabsTrigger value="publications" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Publications
          </TabsTrigger>
          <TabsTrigger value="benchmark" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Benchmark
          </TabsTrigger>
          <TabsTrigger value="similar" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Similar
          </TabsTrigger>
        </TabsList>

        {/* ===== Summary tab ===== */}
        <TabsContent value="summary" className="mt-6">
          {(() => {
            const sorted = [...(financials?.summary ?? [])].sort((a, b) => b.fiscal_year - a.fiscal_year);
            const latest = sorted[0] ?? null;
            const prev = sorted[1] ?? null;

            const currentAdmins = (structure?.administrators || []).filter(
              (a) => !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > new Date()
            );

            // YoY change helper
            function yoyChange(curr: number | null, previous: number | null): { pct: number; direction: "up" | "down" | "flat" } | null {
              if (curr == null || previous == null || previous === 0) return null;
              const pct = ((curr - previous) / Math.abs(previous)) * 100;
              return { pct, direction: pct > 0.5 ? "up" : pct < -0.5 ? "down" : "flat" };
            }

            function changeArrow(change: { pct: number; direction: "up" | "down" | "flat" } | null, goodIfUp = true) {
              if (!change) return null;
              const isGood = (change.direction === "up" && goodIfUp) || (change.direction === "down" && !goodIfUp);
              const color = change.direction === "flat" ? "text-slate-400" : isGood ? "text-emerald-500" : "text-rose-400";
              const arrow = change.direction === "up" ? "\u2191" : change.direction === "down" ? "\u2193" : "\u2192";
              return (
                <span className={`text-xs font-medium ${color}`}>
                  {arrow} {Math.abs(change.pct).toFixed(1)}%
                </span>
              );
            }

            // Credit ratios
            let netDebtEbitda: number | null = null;
            if (latest) {
              const grossDebt = (latest.lt_financial_debt ?? 0) + (latest.st_financial_debt ?? 0);
              const netDebt = grossDebt - (latest.cash ?? 0) - (latest.current_investments ?? 0);
              netDebtEbitda = latest.ebitda && latest.ebitda !== 0 ? netDebt / latest.ebitda : null;
            }

            // Margin color
            function marginColorClass(v: number | null): string {
              if (v == null) return "text-slate-900";
              if (v >= 15) return "text-emerald-600";
              if (v >= 5) return "text-amber-600";
              if (v < 0) return "text-rose-400";
              return "text-slate-900";
            }

            // Health pill color
            function pillColor(type: "leverage" | "margin" | "growth", value: number | null): string {
              if (value == null) return "bg-slate-50 text-slate-400 border-slate-100";
              if (type === "leverage") {
                if (value < 3) return "bg-emerald-50 text-emerald-700 border-emerald-100";
                if (value <= 5) return "bg-amber-50 text-amber-700 border-amber-100";
                return "bg-rose-50 text-rose-500 border-rose-100";
              }
              if (type === "margin") {
                if (value >= 15) return "bg-emerald-50 text-emerald-700 border-emerald-100";
                if (value >= 5) return "bg-amber-50 text-amber-700 border-amber-100";
                return "bg-rose-50 text-rose-500 border-rose-100";
              }
              // growth
              if (value > 2) return "bg-emerald-50 text-emerald-700 border-emerald-100";
              if (value >= -2) return "bg-slate-50 text-slate-500 border-slate-100";
              return "bg-rose-50 text-rose-500 border-rose-100";
            }

            const revenueYoy = yoyChange(latest?.revenue ?? null, prev?.revenue ?? null);
            const ebitdaYoy = yoyChange(latest?.ebitda ?? null, prev?.ebitda ?? null);
            const fteYoy = yoyChange(latest?.fte_total ?? null, prev?.fte_total ?? null);

            // Sparkline data (last 5 years)
            const sparkData = sorted.slice(0, 5).reverse().map((r) => ({
              fy: String(r.fiscal_year),
              Revenue: r.revenue,
              EBITDA: r.ebitda,
            }));

            return (
              <div className="space-y-6">
                {/* Row 1: KPIs (left) + Trend chart (right) */}
                {latest && (
                  <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                    {/* Left: compact KPI list */}
                    <div className="lg:col-span-2 rounded-xl border border-slate-100 bg-white p-4">
                      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                        <BarChart3 className="h-3 w-3" /> Key Financials
                        {latest.fiscal_year && <span className="text-slate-300 font-mono">FY{latest.fiscal_year}</span>}
                      </h3>
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <DollarSign className="h-3.5 w-3.5 text-slate-400" /> Revenue
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-slate-900 font-mono">{fmtEur(latest.revenue)}</span>
                            {changeArrow(revenueYoy)}
                          </div>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <TrendingUp className="h-3.5 w-3.5 text-slate-400" /> EBITDA
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-slate-900 font-mono">{fmtEur(latest.ebitda)}</span>
                            {changeArrow(ebitdaYoy)}
                          </div>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <Percent className="h-3.5 w-3.5 text-slate-400" /> Margin
                          </div>
                          <span className={`text-sm font-semibold font-mono ${marginColorClass(latest.ebitda_margin_pct)}`}>{fmtPct(latest.ebitda_margin_pct)}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <Users className="h-3.5 w-3.5 text-slate-400" /> Employees
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-slate-900 font-mono">{latest.fte_total != null ? fmtNumber(latest.fte_total) : "\u2014"}</span>
                            {changeArrow(fteYoy)}
                          </div>
                        </div>
                      </div>
                      {/* Health pills */}
                      <div className="flex flex-wrap gap-1.5 mt-4 pt-3 border-t border-slate-50">
                        <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${pillColor("leverage", netDebtEbitda)}`}>
                          {netDebtEbitda != null && isFinite(netDebtEbitda) ? `${netDebtEbitda.toFixed(1)}x leverage` : "— leverage"}
                        </span>
                        <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${pillColor("growth", revenueYoy?.pct ?? null)}`}>
                          {revenueYoy ? `${revenueYoy.pct > 0 ? "+" : ""}${revenueYoy.pct.toFixed(0)}% growth` : "— growth"}
                        </span>
                      </div>
                    </div>

                    {/* Right: sparkline chart */}
                    <div className="lg:col-span-3 rounded-xl border border-slate-100 bg-white p-4">
                      <div className="flex items-baseline justify-between mb-2">
                        <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                          <Activity className="h-3 w-3" /> Trend
                        </h3>
                        <button type="button" onClick={() => setActiveTab("pnl")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                          Full P&L →
                        </button>
                      </div>
                      {sparkData.length >= 2 ? (
                        <>
                          <ResponsiveContainer width="100%" height={130}>
                            <LineChart data={sparkData} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                              <XAxis dataKey="fy" tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                              <YAxis hide />
                              <Tooltip content={<ChartTooltip />} />
                              <Line type="monotone" dataKey="Revenue" stroke="#6366f1" strokeWidth={2} dot={{ r: 2, fill: "#6366f1" }} />
                              <Line type="monotone" dataKey="EBITDA" stroke="#06b6d4" strokeWidth={2} dot={{ r: 2, fill: "#06b6d4" }} strokeDasharray="4 2" />
                            </LineChart>
                          </ResponsiveContainer>
                          <div className="flex items-center gap-4 mt-1">
                            <div className="flex items-center gap-1.5">
                              <span className="inline-block h-0.5 w-4 rounded bg-indigo-500" />
                              <span className="text-[10px] text-slate-400">Revenue</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <span className="inline-block h-0.5 w-4 rounded bg-cyan-500" />
                              <span className="text-[10px] text-slate-400">EBITDA</span>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="flex items-center justify-center h-[130px] text-xs text-slate-300">Not enough years for a trend</div>
                      )}
                    </div>
                  </div>
                )}

                {/* Key People + Shareholders + Publications + Subsidiaries — 4 columns */}
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                  {/* Key People */}
                  <div className="rounded-xl border border-slate-100 bg-white p-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                        <UserCheck className="h-3 w-3" /> Key People
                        {currentAdmins.length > 0 && <span className="text-slate-300">({currentAdmins.length})</span>}
                      </h3>
                      {currentAdmins.length > 0 && (
                        <button type="button" onClick={() => setActiveTab("administrators")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                          View all →
                        </button>
                      )}
                    </div>
                    {currentAdmins.length === 0 ? (
                      <div className="flex items-center justify-center py-6 text-xs text-slate-300">
                        <Users className="h-4 w-4 mr-2" /> No administrator data
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {currentAdmins.slice(0, 6).map((a, i) => {
                          function shortDate(d: string | null): string {
                            if (!d) return "";
                            const date = new Date(d);
                            return date.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
                          }
                          const adminCbe = cleanCbe(a.identifier);
                          return (
                            <div key={`${a.name}-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                              <div className="h-8 w-8 rounded-full bg-indigo-50 flex items-center justify-center text-[10px] font-bold text-indigo-600 shrink-0">
                                {(a.name || "?").slice(0, 2).toUpperCase()}
                              </div>
                              <div className="min-w-0 flex-1">
                                {adminCbe ? (
                                  <Link href={`/company/${adminCbe}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                                    {a.name}
                                  </Link>
                                ) : (
                                  <Link href={`/people?q=${encodeURIComponent(a.name)}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                                    {a.name}
                                  </Link>
                                )}
                                <div className="text-[10px] text-slate-400">
                                  {a.role_label || a.role || "—"}
                                </div>
                                {a.mandate_start && (
                                  <div className="text-[10px] text-slate-400">
                                    Since {shortDate(a.mandate_start)}
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        })}
                        {currentAdmins.length > 6 && (
                          <button type="button" onClick={() => setActiveTab("administrators")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                            + {currentAdmins.length - 6} more people →
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Recent Publications */}
                  <div className="rounded-xl border border-slate-100 bg-white p-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                        <Newspaper className="h-3 w-3" /> Recent Publications
                        {(structure?.staatsblad_publications?.length ?? 0) > 0 && (
                          <span className="text-slate-300">({structure?.staatsblad_publications?.length})</span>
                        )}
                      </h3>
                      {(structure?.staatsblad_publications?.length ?? 0) > 0 && (
                        <button type="button" onClick={() => setActiveTab("publications")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                          View all →
                        </button>
                      )}
                    </div>
                    {!structure?.staatsblad_publications?.length ? (
                      <div className="flex items-center justify-center py-6 text-xs text-slate-300">
                        <FileText className="h-4 w-4 mr-2" /> No publications yet
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        {structure.staatsblad_publications.slice(0, 6).map((pub, i) => (
                          <div key={`pub-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                            <div className="h-8 w-8 rounded-full bg-slate-50 flex items-center justify-center shrink-0">
                              <FileText className="h-3.5 w-3.5 text-slate-400" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="text-xs text-slate-700 truncate">{pub.pub_type || "Publication"}</div>
                              <div className="text-[10px] text-slate-400 flex items-center gap-0.5">
                                <Calendar className="h-2.5 w-2.5" /> {pub.pub_date}
                                {pub.reference && <span className="text-slate-200 ml-1">· #{pub.reference}</span>}
                              </div>
                            </div>
                          </div>
                        ))}
                        {structure.staatsblad_publications.length > 6 && (
                          <button type="button" onClick={() => setActiveTab("publications")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                            + {structure.staatsblad_publications.length - 6} more →
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  {/* Key Shareholders */}
                  <div className="rounded-xl border border-slate-100 bg-white p-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                        <Briefcase className="h-3 w-3" /> Key Shareholders
                        {(structure?.shareholders?.length ?? 0) > 0 && <span className="text-slate-300">({structure?.shareholders?.length})</span>}
                      </h3>
                      {(structure?.shareholders?.length ?? 0) > 0 && (
                        <button type="button" onClick={() => setActiveTab("structure")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                          View all →
                        </button>
                      )}
                    </div>
                    {!structure?.shareholders?.length ? (
                      <div className="flex items-center justify-center py-6 text-xs text-slate-300">
                        <Briefcase className="h-4 w-4 mr-2" /> No shareholder data
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {structure.shareholders.slice(0, 5).map((sh, i) => {
                          const shCbe = cleanCbe(sh.identifier);
                          return (
                          <div key={`sh-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                            <div className="h-8 w-8 rounded-full bg-amber-50 flex items-center justify-center text-[10px] font-bold text-amber-600 shrink-0">
                              {(sh.name || "?").slice(0, 2).toUpperCase()}
                            </div>
                            <div className="min-w-0 flex-1">
                              {shCbe ? (
                                <Link href={`/company/${shCbe}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                                  {sh.name}
                                </Link>
                              ) : (
                                <Link href={`/people?q=${encodeURIComponent(sh.name)}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                                  {sh.name}
                                </Link>
                              )}
                              <div className="flex items-center gap-2 text-[10px] text-slate-400">
                                <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4 border-slate-200">
                                  {sh.shareholder_type === "entity" || sh.shareholder_type === "Entity" ? "Entity" : "Individual"}
                                </Badge>
                                {sh.fiscal_year && <span className="text-[10px] text-slate-400">Since FY{sh.fiscal_year}</span>}
                              </div>
                            </div>
                            {sh.ownership_pct != null && (
                              <span className="text-xs font-semibold font-mono text-indigo-600 shrink-0">{sh.ownership_pct.toFixed(1)}%</span>
                            )}
                          </div>
                          );
                        })}
                        {structure.shareholders.length > 5 && (
                          <button type="button" onClick={() => setActiveTab("structure")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                            + {structure.shareholders.length - 5} more shareholders →
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Key Subsidiaries */}
                  <div className="rounded-xl border border-slate-100 bg-white p-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                        <GitBranch className="h-3 w-3" /> Key Subsidiaries
                        {(structure?.participating_interests?.length ?? 0) > 0 && <span className="text-slate-300">({structure?.participating_interests?.length})</span>}
                      </h3>
                      {(structure?.participating_interests?.length ?? 0) > 0 && (
                        <button type="button" onClick={() => setActiveTab("structure")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                          View all →
                        </button>
                      )}
                    </div>
                    {!structure?.participating_interests?.length ? (
                      <div className="flex items-center justify-center py-6 text-xs text-slate-300">
                        <GitBranch className="h-4 w-4 mr-2" /> No subsidiary data
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {structure.participating_interests.slice(0, 5).map((sub, i) => {
                          const subCbe = cleanCbe(sub.identifier);
                          return (
                          <div key={`sub-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                            <div className="h-8 w-8 rounded-full bg-cyan-50 flex items-center justify-center text-[10px] font-bold text-cyan-600 shrink-0">
                              {(sub.name || "?").slice(0, 2).toUpperCase()}
                            </div>
                            <div className="min-w-0 flex-1">
                              {subCbe ? (
                                <Link href={`/company/${subCbe}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                                  {sub.name}
                                </Link>
                              ) : (
                                <Link href={`/people?q=${encodeURIComponent(sub.name)}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                                  {sub.name}
                                </Link>
                              )}
                              <div className="flex items-center gap-2 text-[10px] text-slate-400">
                                {sub.country && <span>{sub.country}</span>}
                                {sub.fiscal_year && <span className="text-[10px] text-slate-400">Since FY{sub.fiscal_year}</span>}
                              </div>
                            </div>
                            {sub.ownership_pct != null && (
                              <span className="text-xs font-semibold font-mono text-indigo-600 shrink-0">{sub.ownership_pct.toFixed(1)}%</span>
                            )}
                          </div>
                          );
                        })}
                        {structure.participating_interests.length > 5 && (
                          <button type="button" onClick={() => setActiveTab("structure")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                            + {structure.participating_interests.length - 5} more subsidiaries →
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Financial History Mini Table (last 5 years) */}
                {sorted.length > 1 && (
                  <div className="rounded-xl border border-slate-100 bg-white overflow-hidden">
                    <div className="px-5 pt-4 pb-2">
                      <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Financial History</h3>
                    </div>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-t border-slate-50">
                          <th className="px-5 py-2 text-left text-slate-400 font-medium">Year</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">Revenue</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">EBITDA</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">Margin</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">Net Profit</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">FTE</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(() => {
                          const chronoMini = sorted.slice(0, 5).reverse();
                          return chronoMini.map((r, i) => {
                            const prevRow = i > 0 ? chronoMini[i - 1] : null;
                            const isLatest = i === chronoMini.length - 1;
                            return (
                              <tr key={r.fiscal_year} className={isLatest ? "bg-indigo-50/30 font-medium" : "border-t border-slate-50"}>
                                <td className="px-5 py-2 font-mono text-slate-700">{r.fiscal_year}</td>
                                <td className="px-3 py-2 text-right font-mono text-slate-700">
                                  {fmtEur(r.revenue)}
                                  {renderDelta(r.revenue, prevRow?.revenue ?? null)}
                                </td>
                                <td className="px-3 py-2 text-right font-mono text-slate-700">
                                  {fmtEur(r.ebitda)}
                                  {renderDelta(r.ebitda, prevRow?.ebitda ?? null)}
                                </td>
                                <td className={`px-3 py-2 text-right font-mono ${marginColorClass(r.ebitda_margin_pct)}`}>{fmtPct(r.ebitda_margin_pct)}</td>
                                <td className={`px-3 py-2 text-right font-mono ${(r.net_profit ?? 0) < 0 ? "text-rose-400" : "text-slate-700"}`}>
                                  {fmtEur(r.net_profit)}
                                  {renderDelta(r.net_profit, prevRow?.net_profit ?? null)}
                                </td>
                                <td className="px-3 py-2 text-right font-mono text-slate-700">
                                  {r.fte_total != null ? fmtNumber(r.fte_total) : "\u2014"}
                                  {renderDelta(r.fte_total, prevRow?.fte_total ?? null)}
                                </td>
                              </tr>
                            );
                          });
                        })()}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Quick navigation links */}
                <div className="flex flex-wrap gap-3 pt-2">
                  {sorted.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveTab("pnl")}
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
                    >
                      P&L details <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                  {sorted.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveTab("credit")}
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
                    >
                      Credit analysis <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                  {currentAdmins.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveTab("administrators")}
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
                    >
                      {currentAdmins.length} administrator{currentAdmins.length !== 1 ? "s" : ""} <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                  {(structure?.shareholders?.length ?? 0) > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveTab("structure")}
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
                    >
                      Structure <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                </div>

                {/* AI Enrichment Section */}
                <div className="rounded-xl border border-indigo-100 bg-indigo-50/30 p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Sparkles className="h-4 w-4 text-indigo-500" />
                    <h3 className="text-xs font-medium text-slate-600 uppercase tracking-wider">AI Company Summary</h3>
                    <span className="inline-flex items-center rounded-full bg-indigo-100 text-indigo-700 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider">Premium</span>
                  </div>
                  {aiSummary ? (
                    <p className="text-sm text-slate-700 leading-relaxed">{aiSummary}</p>
                  ) : aiLoading ? (
                    <div className="flex items-center gap-2 py-2">
                      <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
                      <span className="text-sm text-slate-500">Generating AI summary...</span>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <button
                        type="button"
                        onClick={async () => {
                          setAiLoading(true);
                          setAiError(null);
                          try {
                            const result = await enrichCompany(cbe);
                            if (result?.summary) {
                              setAiSummary(result.summary);
                            } else {
                              setAiError("No summary returned. The AI service may be temporarily unavailable.");
                            }
                          } catch (err: unknown) {
                            const msg = err instanceof Error ? err.message : "Unknown error";
                            if (msg.includes("401") || msg.includes("403")) {
                              setAiError("Please sign in to use AI enrichment.");
                            } else if (msg.includes("503")) {
                              setAiError("AI service unavailable. Please check your API key configuration.");
                            } else {
                              setAiError(`AI enrichment failed: ${msg}`);
                            }
                          } finally {
                            setAiLoading(false);
                          }
                        }}
                        className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors shadow-sm"
                      >
                        <Sparkles className="h-4 w-4" />
                        Enrich with AI
                      </button>
                      {aiError && (
                        <p className="text-xs text-red-500">{aiError}</p>
                      )}
                    </div>
                  )}
                </div>

                {/* AI Insights: Web & LinkedIn */}
                <div className="rounded-xl border border-slate-200 bg-slate-50/30 p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Globe className="h-4 w-4 text-slate-500" />
                    <h3 className="text-xs font-medium text-slate-600 uppercase tracking-wider">Web Enrichment</h3>
                    <span className="inline-flex items-center rounded-full bg-amber-100 text-amber-700 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider">Premium</span>
                  </div>

                  <div className="flex flex-wrap gap-2 mb-3">
                    {/* AI Insights: Website button */}
                    {!websiteScrape && (
                      <div className="space-y-1">
                        <button
                          type="button"
                          disabled={websiteScrapeLoading}
                          onClick={async () => {
                            setWebsiteScrapeLoading(true);
                            setWebsiteError(null);
                            try {
                              const result = await scrapeCompanyWebsite(cbe);
                              if (result) setWebsiteScrape(result);
                            } catch (err: unknown) {
                              const msg = err instanceof Error ? err.message : "Unknown error";
                              if (msg.includes("404")) {
                                setWebsiteError("No website found for this company.");
                              } else if (msg.includes("401") || msg.includes("403")) {
                                setWebsiteError("Please sign in to use this feature.");
                              } else {
                                setWebsiteError(`Website insights failed: ${msg}`);
                              }
                            } finally {
                              setWebsiteScrapeLoading(false);
                            }
                          }}
                          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:border-slate-400 transition-colors disabled:opacity-50"
                        >
                          {websiteScrapeLoading ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
                          ) : (
                            <Globe className="h-3.5 w-3.5 text-slate-400" />
                          )}
                          AI Insights: Website
                        </button>
                        {websiteError && <p className="text-[10px] text-red-500">{websiteError}</p>}
                      </div>
                    )}

                    {/* AI Insights: LinkedIn button */}
                    {!linkedinScrape && (
                      <div className="space-y-1">
                        <button
                          type="button"
                          disabled={linkedinScrapeLoading}
                          onClick={async () => {
                            setLinkedinScrapeLoading(true);
                            setLinkedinError(null);
                            try {
                              const result = await scrapeCompanyLinkedIn(cbe);
                              if (result) setLinkedinScrape(result);
                            } catch (err: unknown) {
                              const msg = err instanceof Error ? err.message : "Unknown error";
                              if (msg.includes("404")) {
                                setLinkedinError("No LinkedIn profile found for this company.");
                              } else if (msg.includes("401") || msg.includes("403")) {
                                setLinkedinError("Please sign in to use this feature.");
                              } else {
                                setLinkedinError(`LinkedIn insights failed: ${msg}`);
                              }
                            } finally {
                              setLinkedinScrapeLoading(false);
                            }
                          }}
                          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:border-slate-400 transition-colors disabled:opacity-50"
                        >
                          {linkedinScrapeLoading ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
                          ) : (
                            <svg className="h-3.5 w-3.5 text-[#0A66C2]" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" /></svg>
                          )}
                          AI Insights: LinkedIn
                        </button>
                        {linkedinError && <p className="text-[10px] text-red-500">{linkedinError}</p>}
                      </div>
                    )}
                  </div>

                  {/* Website AI Insights result */}
                  {websiteScrape && (
                    <div className="mb-3 rounded-lg border border-slate-200 bg-white p-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <Globe className="h-3.5 w-3.5 text-slate-400" />
                        <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">Website</span>
                        {websiteScrape.website_url && (
                          <a href={websiteScrape.website_url} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-500 hover:underline ml-auto flex items-center gap-1">
                            Visit <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                      {websiteScrape.summary && <p className="text-sm text-slate-700 leading-relaxed">{websiteScrape.summary}</p>}
                      {websiteScrape.products && (
                        <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Products:</span> {websiteScrape.products}</p>
                      )}
                      {websiteScrape.key_people && (
                        <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Key people:</span> {websiteScrape.key_people}</p>
                      )}
                    </div>
                  )}

                  {/* LinkedIn AI Insights result */}
                  {linkedinScrape && (
                    <div className="rounded-lg border border-slate-200 bg-white p-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <svg className="h-3.5 w-3.5 text-[#0A66C2]" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" /></svg>
                        <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">LinkedIn</span>
                        {linkedinScrape.linkedin_url && (
                          <a href={linkedinScrape.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-500 hover:underline ml-auto flex items-center gap-1">
                            View profile <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                      {linkedinScrape.summary && <p className="text-sm text-slate-700 leading-relaxed">{linkedinScrape.summary}</p>}
                      <div className="flex flex-wrap gap-x-4 gap-y-1">
                        {linkedinScrape.industry && (
                          <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Industry:</span> {linkedinScrape.industry}</p>
                        )}
                        {linkedinScrape.employee_count && (
                          <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Employees:</span> {linkedinScrape.employee_count}</p>
                        )}
                        {linkedinScrape.specialties && (
                          <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Specialties:</span> {linkedinScrape.specialties}</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Both buttons hidden, no results yet -- show nothing extra */}
                  {websiteScrape && linkedinScrape && !websiteScrapeLoading && !linkedinScrapeLoading && (
                    <div />
                  )}
                </div>
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== P&L tab ===== */}
        <TabsContent value="pnl" className="mt-3">
          {!financials || financials.summary.length === 0 ? (
            <div className="py-8 text-center">
              {nbbLoading ? (
                <div className="flex flex-col items-center gap-2">
                  <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                  <p className="text-sm text-slate-500 animate-pulse">
                    Loading financial data from NBB... This may take a minute.
                  </p>
                </div>
              ) : (
                <>
                  <p className="text-sm text-slate-500 mb-4">
                    {nbbResult === "no-data"
                      ? "No NBB filings found for this company."
                      : "No financial data available for this company."}
                  </p>
                  <Button
                    variant="outline"
                    disabled={nbbLoading}
                    onClick={async () => {
                      setNbbLoading(true);
                      setNbbResult(null);
                      try {
                        const data = await loadCompanyNBB(cbe);
                        if (data.rubrics_loaded > 0) {
                          setNbbResult("success");
                          getCompanyFinancials(cbe).then(f => setFinancials(f as unknown as FinancialsData));
                        } else {
                          setNbbResult("no-data");
                        }
                      } catch {
                        setNbbResult("error");
                      } finally {
                        setNbbLoading(false);
                      }
                    }}
                    className={`text-indigo-600 border-indigo-300 hover:bg-indigo-50 ${nbbLoading ? "opacity-70 cursor-not-allowed" : ""}`}
                  >
                    <Download className="w-4 h-4 mr-2" />
                    {nbbResult === "no-data" ? "Retry from NBB" : "Load from NBB"}
                  </Button>
                  {nbbResult === "success" && (
                    <div className="mt-3 flex items-center justify-center gap-1.5 text-xs text-emerald-600">
                      <CheckCircle2 className="w-4 h-4" />
                      Data loaded successfully.
                    </div>
                  )}
                  {nbbResult === "error" && (
                    <div className="mt-3 flex items-center justify-center gap-1.5 text-xs text-rose-400">
                      <XCircle className="w-4 h-4" />
                      Failed to load data. The company may not have filings available.
                    </div>
                  )}
                </>
              )}
            </div>
          ) : (
            (() => {
              const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);
              const chronological = [...sorted].reverse();

              // Derive P&L line items per year
              const pnlData = sorted.map((row) => {
                const revenue = row.revenue;
                const grossMargin = row.gross_margin;
                const costOfSales = revenue != null && grossMargin != null ? -(revenue - grossMargin) : null;
                const personnel = row.personnel_costs != null ? -Math.abs(row.personnel_costs) : null;
                const da = row.da != null ? -Math.abs(row.da) : null;
                const ebit = row.ebit;
                const otherOpCosts = grossMargin != null && ebit != null
                  ? -(grossMargin - (ebit) - Math.abs(row.personnel_costs ?? 0) - Math.abs(row.da ?? 0))
                  : null;
                const finCharges = row.financial_charges != null ? -Math.abs(row.financial_charges) : null;
                const pbt = ebit != null && row.financial_charges != null ? ebit - Math.abs(row.financial_charges) : null;
                const netProfit = row.net_profit;
                const tax = pbt != null && netProfit != null ? -(pbt - netProfit) : null;
                return {
                  fiscal_year: row.fiscal_year,
                  revenue,
                  costOfSales,
                  grossMargin,
                  personnel,
                  da,
                  otherOpCosts: otherOpCosts != null && Math.abs(otherOpCosts) > 0.5 ? otherOpCosts : null,
                  ebit,
                  finCharges,
                  pbt,
                  tax,
                  netProfit,
                  ebitda: row.ebitda,
                  ebitdaMarginPct: row.ebitda_margin_pct,
                };
              });

              // Helper: format accounting cell
              // isCost: show in parentheses but normal color (costs are expected to be negative)
              // isKeyMetric: show rose only if negative (EBITDA, EBIT, Net Profit)
              const fmtAcct = (v: number | null, isCost = false, isKeyMetric = false) => {
                if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
                if (isCost && v < 0) {
                  return <span className="text-slate-500">({fmtEur(Math.abs(v))})</span>;
                }
                if (isKeyMetric && v < 0) {
                  return <span className="text-rose-400">({fmtEur(Math.abs(v))})</span>;
                }
                if (v < 0) {
                  return <span className="text-slate-500">({fmtEur(Math.abs(v))})</span>;
                }
                return <>{fmtEur(v)}</>;
              };

              type PnlLine = {
                label: string;
                key: keyof (typeof pnlData)[0];
                isCost?: boolean;
                isKeyMetric?: boolean;
                bold?: boolean;
                topBorder?: boolean;
                doubleBorder?: boolean;
                section?: string;
                indent?: boolean;
                isPct?: boolean;
                group?: string;
              };

              const chronologicalPnl = [...pnlData].reverse();

              const lines: PnlLine[] = [
                { label: "Revenue", key: "revenue", section: "REVENUE" },
                { label: "Cost of Sales", key: "costOfSales", isCost: true, indent: true },
                { label: "Gross Profit", key: "grossMargin", bold: true, topBorder: true },
                { label: "Personnel Costs", key: "personnel", isCost: true, section: "OPERATING COSTS", indent: true, group: "pnl_opex" },
                { label: "Depreciation & Amortization", key: "da", isCost: true, indent: true, group: "pnl_opex" },
                { label: "Other Operating Costs", key: "otherOpCosts", isCost: true, indent: true, group: "pnl_opex" },
                { label: "EBIT (Operating Profit)", key: "ebit", bold: true, topBorder: true, isKeyMetric: true },
                { label: "Financial Charges", key: "finCharges", isCost: true, section: "FINANCIAL", indent: true },
                { label: "Profit Before Tax", key: "pbt", bold: true, topBorder: true, isKeyMetric: true },
                { label: "Tax", key: "tax", isCost: true, indent: true },
                { label: "Net Profit", key: "netProfit", bold: true, doubleBorder: true, isKeyMetric: true },
                { label: "EBITDA", key: "ebitda", bold: true, section: "EBITDA", topBorder: true, isKeyMetric: true },
                { label: "EBITDA Margin", key: "ebitdaMarginPct", isPct: true },
              ];

              let lastSection = "";

              function exportPnlCsv() {
                const headers = ["Line Item", ...sorted.map(r => `FY${r.fiscal_year}`)];
                const csvLines = lines.map(line => {
                  const cells = pnlData.map(r => {
                    const v = r[line.key];
                    if (v == null) return "";
                    if (line.isPct) return `${(v as number).toFixed(1)}%`;
                    return String(v);
                  });
                  return [line.label, ...cells].join(",");
                });
                const blob = new Blob([headers.join(",") + "\n" + csvLines.join("\n")], { type: "text/csv" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `${detail?.name || cbe}_pnl.csv`;
                a.click();
                URL.revokeObjectURL(url);
              }

              // Core metrics summary
              const latestPnl = pnlData.find((_, i) => i === 0); // newest
              const prevPnl = pnlData.length > 1 ? pnlData[1] : null;

              const revGrowth = latestPnl?.revenue != null && prevPnl?.revenue != null && prevPnl.revenue !== 0
                ? ((latestPnl.revenue - prevPnl.revenue) / Math.abs(prevPnl.revenue)) * 100 : null;
              const grossMarginPct = latestPnl?.revenue != null && latestPnl?.grossMargin != null && latestPnl.revenue !== 0
                ? (latestPnl.grossMargin / latestPnl.revenue) * 100 : null;
              const ebitdaPct = latestPnl?.ebitdaMarginPct ?? null;
              const ebitdaGrowth = latestPnl?.ebitda != null && prevPnl?.ebitda != null && prevPnl.ebitda !== 0
                ? ((latestPnl.ebitda - prevPnl.ebitda) / Math.abs(prevPnl.ebitda)) * 100 : null;
              const ebitPct = latestPnl?.revenue != null && latestPnl?.ebit != null && latestPnl.revenue !== 0
                ? (latestPnl.ebit / latestPnl.revenue) * 100 : null;
              const ebitGrowth = latestPnl?.ebit != null && prevPnl?.ebit != null && prevPnl.ebit !== 0
                ? ((latestPnl.ebit - prevPnl.ebit) / Math.abs(prevPnl.ebit)) * 100 : null;

              const growthPill = (v: number | null) => {
                if (v == null) return null;
                const color = v > 2 ? "text-emerald-600" : v < -2 ? "text-rose-400" : "text-slate-500";
                const arrow = v > 0.5 ? "↑" : v < -0.5 ? "↓" : "→";
                return <span className={`text-[10px] font-medium ${color}`}>{arrow} {Math.abs(v).toFixed(1)}%</span>;
              };

              const marginPill = (v: number | null) => {
                if (v == null) return <span className="text-slate-300 text-xs font-mono">—</span>;
                const color = v >= 15 ? "text-emerald-600" : v >= 5 ? "text-amber-600" : "text-rose-400";
                return <span className={`text-xs font-mono font-semibold ${color}`}>{v.toFixed(1)}%</span>;
              };

              return (
                <div className="space-y-4">
                  {/* ── Core Metrics Summary ── */}
                  {latestPnl && (
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2">
                      {[
                        { label: "Revenue", value: fmtEur(latestPnl.revenue), sub: growthPill(revGrowth), icon: <DollarSign className="h-3 w-3" /> },
                        { label: "Gross Margin", value: marginPill(grossMarginPct), sub: null, icon: <Percent className="h-3 w-3" /> },
                        { label: "EBITDA", value: fmtEur(latestPnl.ebitda), sub: growthPill(ebitdaGrowth), icon: <BarChart3 className="h-3 w-3" /> },
                        { label: "EBITDA %", value: marginPill(ebitdaPct), sub: null, icon: <Percent className="h-3 w-3" /> },
                        { label: "EBIT", value: fmtEur(latestPnl.ebit), sub: growthPill(ebitGrowth), icon: <Activity className="h-3 w-3" /> },
                        { label: "EBIT %", value: marginPill(ebitPct), sub: null, icon: <Percent className="h-3 w-3" /> },
                        { label: "Net Profit", value: fmtEur(latestPnl.netProfit), sub: null, icon: <DollarSign className="h-3 w-3" /> },
                      ].map((m, i) => (
                        <div key={i} className="rounded-lg border border-slate-100 bg-white p-2.5 text-center">
                          <div className="flex items-center justify-center gap-1 text-[9px] text-slate-400 uppercase tracking-wider mb-1">
                            {m.icon} {m.label}
                          </div>
                          <div className="text-sm font-semibold text-slate-800 font-mono">{m.value}</div>
                          {m.sub && <div className="mt-0.5">{m.sub}</div>}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* ── Income Statement ── */}
                  <div>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
                      Income Statement
                    </h3>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => toggleSection("pnl_opex")}
                        className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${collapsedSections.pnl_opex ? "bg-indigo-50 border-indigo-200 text-indigo-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}
                      >
                        {collapsedSections.pnl_opex ? "▸ OpEx grouped" : "▾ OpEx expanded"}
                      </button>
                      <ExportButtons
                        onExportCSV={exportPnlCsv}
                        onPrint={() => window.print()}
                      />
                    </div>
                  </div>
                  <div className="rounded-lg border overflow-x-auto bg-white">
                    <table className="w-full">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200">
                          <th className="px-4 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider min-w-[160px] md:min-w-[240px]">Line Item</th>
                          {renderDeltaHeaders(chronological.map(r => r.fiscal_year))}
                        </tr>
                      </thead>
                      <tbody>
                        {lines.map((line) => {
                          // Skip lines in collapsed groups
                          if (line.group && collapsedSections[line.group]) return null;

                          const showSection = line.section && line.section !== lastSection;
                          if (line.section) lastSection = line.section;
                          return (
                            <React.Fragment key={line.key}>
                              {showSection && (
                                <tr>
                                  <td colSpan={chronological.length * 2} className="px-4 pt-3 pb-1">
                                    <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-widest">{line.section}</span>
                                  </td>
                                </tr>
                              )}
                              <tr className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}>
                                <td className={`px-4 py-1 text-xs ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-8" : ""}`}>
                                  {line.label}
                                </td>
                                {chronologicalPnl.map((r, colIdx) => {
                                  const prevRow = colIdx > 0 ? chronologicalPnl[colIdx - 1] : null;
                                  const currentVal = r[line.key] as number | null;
                                  const prevVal = prevRow ? (prevRow[line.key] as number | null) : null;
                                  return (
                                    <React.Fragment key={`cell-${r.fiscal_year}-${line.key}`}>
                                      {colIdx > 0 && (
                                        <td className="px-1 py-1 text-center align-top">
                                          {!line.isPct ? renderDelta(currentVal, prevVal) : null}
                                        </td>
                                      )}
                                      <td className={`px-3 py-1 text-right text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
                                        {line.isPct
                                          ? (currentVal != null
                                              ? <span className={`${(currentVal as number) >= 15 ? "text-emerald-600" : (currentVal as number) >= 5 ? "text-amber-600" : "text-rose-400"}`}>{(currentVal as number).toFixed(1)}%</span>
                                              : <span className="text-slate-300">{"\u2014"}</span>)
                                          : fmtAcct(currentVal, line.isCost, line.isKeyMetric)}
                                      </td>
                                    </React.Fragment>
                                  );
                                })}
                              </tr>
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-1 text-[10px] text-slate-400 italic">
                    Gross Profit = rubric 9900. EBIT = rubric 9901. Net Profit = rubric 9904. Cost of Sales = Revenue - Gross Profit. Other Op. Costs = Gross Profit - Personnel - D&A - EBIT.
                  </p>
                  </div>

                  {/* Revenue & EBITDA Chart */}
                  {chartData.length >= 2 && (
                    <Card className="mt-4">
                      <CardContent className="pt-3 pb-3">
                        <h3 className="mb-3 text-xs font-semibold text-slate-700">
                          Revenue & EBITDA trend
                        </h3>
                        <ResponsiveContainer width="100%" height={320}>
                          <LineChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                            <XAxis dataKey="fy" tick={{ fontSize: 12, fill: "#64748b" }} />
                            <YAxis tick={{ fontSize: 12, fill: "#64748b" }} tickFormatter={(v: number) => fmtEur(v)} />
                            <Tooltip content={<ChartTooltip />} />
                            <Legend wrapperStyle={{ fontSize: "12px" }} />
                            <Line type="monotone" dataKey="Revenue" stroke="#4f46e5" strokeWidth={2} dot={{ r: 4, fill: "#4f46e5" }} />
                            <Line type="monotone" dataKey="EBITDA" stroke="#06b6d4" strokeWidth={2} dot={{ r: 4, fill: "#06b6d4" }} />
                          </LineChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  )}
                </div>
              );
            })()
          )}
        </TabsContent>

        {/* ===== Cash Flow tab ===== */}
        <TabsContent value="cashflow" className="mt-3">
          {!financials || financials.summary.length < 2 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              Need at least two years of financial data to derive cash flow.
            </p>
          ) : (() => {
            const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);

            // Helper: format value, red if negative
            const fmtCell = (v: number | null) => {
              if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
              const formatted = fmtEur(v);
              return v < 0 ? <span className="text-rose-400">{formatted}</span> : <>{formatted}</>;
            };

            const cfRowsDesc = sorted.slice(0, -1).map((row, idx) => {
              const prev = sorted[idx + 1];

              const ebitda = row.ebitda;

              // Working capital deltas (increase in asset = cash outflow = negative)
              const deltaInv = -((row.inventories ?? 0) - (prev.inventories ?? 0));
              const deltaRec = -((row.trade_receivables ?? 0) - (prev.trade_receivables ?? 0));
              const deltaPay = (row.trade_payables ?? 0) - (prev.trade_payables ?? 0);
              const wcChange = deltaInv + deltaRec + deltaPay;

              // Cash from Operations
              const cashFromOps = ebitda != null ? ebitda + wcChange : null;

              // Investing: CapEx estimated as delta fixed assets + D&A
              const capex = -Math.abs((row.fixed_assets ?? 0) - (prev.fixed_assets ?? 0) + Math.abs(row.da ?? 0));
              const cashFromInvesting = capex;

              // Financing
              const deltaLtDebt = (row.lt_financial_debt ?? 0) - (prev.lt_financial_debt ?? 0);
              const deltaStDebt = (row.st_financial_debt ?? 0) - (prev.st_financial_debt ?? 0);
              const deltaEquity = (row.equity ?? 0) - (prev.equity ?? 0);
              const cashFromFinancing = deltaLtDebt + deltaStDebt + deltaEquity;

              // Net cash change
              const netCashChange = cashFromOps != null ? cashFromOps + cashFromInvesting + cashFromFinancing : null;
              const cashStart = (prev.cash ?? 0) + (prev.current_investments ?? 0);
              const cashEnd = (row.cash ?? 0) + (row.current_investments ?? 0);

              return {
                fiscal_year: row.fiscal_year,
                ebitda,
                deltaInv: deltaInv !== 0 ? deltaInv : null,
                deltaRec: deltaRec !== 0 ? deltaRec : null,
                deltaPay: deltaPay !== 0 ? deltaPay : null,
                wcChange: wcChange !== 0 ? wcChange : null,
                cashFromOps,
                capex: capex !== 0 ? capex : null,
                cashFromInvesting,
                deltaLtDebt: deltaLtDebt !== 0 ? deltaLtDebt : null,
                deltaStDebt: deltaStDebt !== 0 ? deltaStDebt : null,
                deltaEquity: deltaEquity !== 0 ? deltaEquity : null,
                cashFromFinancing: cashFromFinancing !== 0 ? cashFromFinancing : null,
                netCashChange,
                cashStart: cashStart || null,
                cashEnd: cashEnd || null,
              };
            });
            const cfRows = [...cfRowsDesc].reverse();

            type CFLine = {
              label: string;
              key: keyof (typeof cfRows)[0];
              bold?: boolean;
              indent?: boolean;
              topBorder?: boolean;
              doubleBorder?: boolean;
              section?: string;
              group?: string;
            };

            const lines: CFLine[] = [
              { label: "EBITDA", key: "ebitda", section: "OPERATING ACTIVITIES" },
              { label: "Δ Inventories", key: "deltaInv", indent: true, group: "cf_wc" },
              { label: "Δ Trade Receivables", key: "deltaRec", indent: true, group: "cf_wc" },
              { label: "Δ Trade Payables", key: "deltaPay", indent: true, group: "cf_wc" },
              { label: "Change in Working Capital", key: "wcChange", bold: true, topBorder: true },
              { label: "Cash from Operations", key: "cashFromOps", bold: true, topBorder: true },
              { label: "CapEx (est.: Δ Fixed Assets + D&A)", key: "capex", indent: true, section: "INVESTING ACTIVITIES" },
              { label: "Cash from Investing", key: "cashFromInvesting", bold: true, topBorder: true },
              { label: "Δ Long-term Debt", key: "deltaLtDebt", indent: true, section: "FINANCING ACTIVITIES", group: "cf_fin" },
              { label: "Δ Short-term Debt", key: "deltaStDebt", indent: true, group: "cf_fin" },
              { label: "Δ Equity", key: "deltaEquity", indent: true, group: "cf_fin" },
              { label: "Cash from Financing", key: "cashFromFinancing", bold: true, topBorder: true },
              { label: "NET CASH CHANGE", key: "netCashChange", bold: true, doubleBorder: true },
              { label: "Cash at Start of Year", key: "cashStart", indent: true },
              { label: "Cash at End of Year", key: "cashEnd", indent: true },
            ];

            let lastSection = "";

            function exportCfCsv() {
              const headers = ["Line Item", ...cfRows.map(r => `FY${r.fiscal_year}`)];
              const csvLines = lines.map(line => {
                const cells = cfRowsDesc.map(r => {
                  const v = r[line.key];
                  if (v == null) return "";
                  return String(v);
                });
                return [line.label, ...cells].join(",");
              });
              const blob = new Blob([headers.join(",") + "\n" + csvLines.join("\n")], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `${detail?.name || cbe}_cash_flow.csv`;
              a.click();
              URL.revokeObjectURL(url);
            }

            return (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-cyan-500 pl-2">
                    Derived Cash Flow Statement
                  </h3>
                  <div className="flex items-center gap-2">
                    <button onClick={() => toggleSection("cf_wc")} className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${collapsedSections.cf_wc ? "bg-cyan-50 border-cyan-200 text-cyan-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
                      {collapsedSections.cf_wc ? "▸ WC grouped" : "▾ WC expanded"}
                    </button>
                    <button onClick={() => toggleSection("cf_fin")} className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${collapsedSections.cf_fin ? "bg-cyan-50 border-cyan-200 text-cyan-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
                      {collapsedSections.cf_fin ? "▸ Financing grouped" : "▾ Financing expanded"}
                    </button>
                    <ExportButtons onExportCSV={exportCfCsv} onPrint={() => window.print()} />
                  </div>
                </div>
                <div className="rounded-lg border overflow-x-auto bg-white">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200">
                        <th className="px-4 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider min-w-[160px] md:min-w-[260px]">Line Item</th>
                        {renderDeltaHeaders(cfRows.map(r => r.fiscal_year))}
                      </tr>
                    </thead>
                    <tbody>
                      {lines.map((line) => {
                        if (line.group && collapsedSections[line.group]) return null;

                        const showSection = line.section && line.section !== lastSection;
                        if (line.section) lastSection = line.section;
                        return (
                          <React.Fragment key={line.key}>
                            {showSection && (
                              <tr>
                                <td colSpan={cfRows.length * 2} className="px-4 pt-3 pb-1">
                                  <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-widest">{line.section}</span>
                                </td>
                              </tr>
                            )}
                            <tr className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}>
                              <td className={`px-4 py-1 text-xs ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-8" : ""}`}>
                                {line.label}
                              </td>
                              {cfRows.map((r, colIdx) => {
                                const prevRow = colIdx > 0 ? cfRows[colIdx - 1] : null;
                                const currentVal = r[line.key] as number | null;
                                const prevVal = prevRow ? (prevRow[line.key] as number | null) : null;
                                return (
                                  <React.Fragment key={`cf-${r.fiscal_year}-${line.key}`}>
                                    {colIdx > 0 && (
                                      <td className="px-1 py-1 text-center align-top">
                                        {renderDelta(currentVal, prevVal)}
                                      </td>
                                    )}
                                    <td className={`px-3 py-1 text-right text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
                                      {fmtCell(r[line.key] as number | null)}
                                    </td>
                                  </React.Fragment>
                                );
                              })}
                            </tr>
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-1 text-[10px] text-slate-400 italic">
                  All values derived. WC: increase in assets = cash outflow (negative), increase in payables = cash inflow (positive).
                  CapEx estimated as |delta fixed assets + D&A|. Cash = cash + short-term investments.
                </p>
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== Balance Sheet tab ===== */}
        <TabsContent value="balancesheet" className="mt-3">
          {!financials || financials.summary.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No financial data available for this company.
            </p>
          ) : (() => {
            const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);
            const chronological = [...sorted].reverse();

            // Helper: format value, red if negative
            const fmtCell = (v: number | null) => {
              if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
              const formatted = fmtEur(v);
              return v < 0 ? <span className="text-rose-400">{formatted}</span> : <>{formatted}</>;
            };

            // Build derived rows per year
            const bsRows = sorted.map((row) => {
              const fixedAssets = row.fixed_assets ?? null;
              const totalAssets = row.total_assets ?? null;
              const currentAssets = totalAssets != null && fixedAssets != null ? totalAssets - fixedAssets : null;
              const inventories = row.inventories ?? null;
              const tradeReceivables = row.trade_receivables ?? null;
              const cash = row.cash ?? null;
              const currentInvestments = row.current_investments ?? null;
              const otherCurrentAssets = currentAssets != null
                ? currentAssets - (inventories ?? 0) - (tradeReceivables ?? 0) - (cash ?? 0) - (currentInvestments ?? 0)
                : null;

              const equity = row.equity ?? null;
              const ltDebt = row.lt_debt ?? null;
              const ltFinDebt = row.lt_financial_debt ?? null;
              const totalLE = totalAssets; // must balance
              const totalNonCurrentLiab = ltDebt;
              const totalCurrentLiab = totalLE != null && equity != null && ltDebt != null
                ? totalLE - equity - ltDebt
                : null;
              const stFinDebt = row.st_financial_debt ?? null;
              const tradePayables = row.trade_payables ?? null;
              const otherCurrentLiab = totalCurrentLiab != null
                ? totalCurrentLiab - (stFinDebt ?? 0) - (tradePayables ?? 0)
                : null;

              return {
                fiscal_year: row.fiscal_year,
                fixedAssets,
                totalNonCurrentAssets: fixedAssets,
                currentAssets,
                inventories,
                tradeReceivables,
                cash,
                currentInvestments,
                otherCurrentAssets: otherCurrentAssets != null && Math.abs(otherCurrentAssets) > 0.5 ? otherCurrentAssets : null,
                totalCurrentAssets: currentAssets,
                totalAssets,
                equity,
                ltDebt,
                ltFinDebt,
                totalNonCurrentLiab,
                tradePayables,
                stFinDebt,
                otherCurrentLiab: otherCurrentLiab != null && Math.abs(otherCurrentLiab) > 0.5 ? otherCurrentLiab : null,
                totalCurrentLiab,
                totalLE: totalAssets,
              };
            });
            const chronologicalBs = [...bsRows].reverse();

            type BSLine = {
              label: string;
              key: keyof (typeof bsRows)[0];
              bold?: boolean;
              indent?: boolean;
              topBorder?: boolean;
              doubleBorder?: boolean;
              section?: string;
              subIndent?: boolean;
              group?: string;
            };

            const lines: BSLine[] = [
              // ASSETS
              { label: "Tangible Fixed Assets", key: "fixedAssets", indent: true, section: "NON-CURRENT ASSETS" },
              { label: "Total Non-Current Assets (20/28)", key: "totalNonCurrentAssets", bold: true, topBorder: true },
              { label: "Inventories (3)", key: "inventories", indent: true, section: "CURRENT ASSETS", group: "bs_ca" },
              { label: "Trade Receivables (40/41)", key: "tradeReceivables", indent: true, group: "bs_ca" },
              { label: "Cash & Cash Equivalents (54/58)", key: "cash", indent: true, group: "bs_ca" },
              { label: "Short-term Investments (50/53)", key: "currentInvestments", indent: true, group: "bs_ca" },
              { label: "Other Current Assets", key: "otherCurrentAssets", indent: true, group: "bs_ca" },
              { label: "Total Current Assets", key: "totalCurrentAssets", bold: true, topBorder: true },
              { label: "TOTAL ASSETS (20/58)", key: "totalAssets", bold: true, doubleBorder: true },
              // EQUITY & LIABILITIES
              { label: "Total Equity (10/15)", key: "equity", bold: true, section: "EQUITY" },
              { label: "Long-term Debt (17)", key: "ltDebt", indent: true, section: "NON-CURRENT LIABILITIES" },
              { label: "of which: Financial Debt (170/4)", key: "ltFinDebt", subIndent: true },
              { label: "Total Non-Current Liabilities", key: "totalNonCurrentLiab", bold: true, topBorder: true },
              { label: "Trade Payables (44)", key: "tradePayables", indent: true, section: "CURRENT LIABILITIES", group: "bs_cl" },
              { label: "Short-term Financial Debt (43)", key: "stFinDebt", indent: true, group: "bs_cl" },
              { label: "Other Current Liabilities", key: "otherCurrentLiab", indent: true, group: "bs_cl" },
              { label: "Total Current Liabilities", key: "totalCurrentLiab", bold: true, topBorder: true },
              { label: "TOTAL EQUITY + LIABILITIES", key: "totalLE", bold: true, doubleBorder: true },
            ];

            let lastSection = "";

            function exportBsCsv() {
              const headers = ["Line Item", ...sorted.map(r => `FY${r.fiscal_year}`)];
              const csvLines = lines.map(line => {
                const cells = bsRows.map(r => {
                  const v = r[line.key];
                  if (v == null) return "";
                  return String(v);
                });
                return [line.label, ...cells].join(",");
              });
              const blob = new Blob([headers.join(",") + "\n" + csvLines.join("\n")], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `${detail?.name || cbe}_balance_sheet.csv`;
              a.click();
              URL.revokeObjectURL(url);
            }

            return (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
                    Balance Sheet
                  </h3>
                  <div className="flex items-center gap-2">
                    <button onClick={() => toggleSection("bs_ca")} className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${collapsedSections.bs_ca ? "bg-indigo-50 border-indigo-200 text-indigo-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
                      {collapsedSections.bs_ca ? "▸ Current Assets grouped" : "▾ Current Assets expanded"}
                    </button>
                    <button onClick={() => toggleSection("bs_cl")} className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${collapsedSections.bs_cl ? "bg-indigo-50 border-indigo-200 text-indigo-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
                      {collapsedSections.bs_cl ? "▸ Current Liab. grouped" : "▾ Current Liab. expanded"}
                    </button>
                    <ExportButtons
                      onExportCSV={exportBsCsv}
                      onPrint={() => window.print()}
                    />
                  </div>
                </div>
                <div className="rounded-lg border overflow-x-auto bg-white">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-slate-50 border-b border-slate-200">
                        <th className="px-4 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider min-w-[160px] md:min-w-[260px]">Line Item</th>
                        {renderDeltaHeaders(chronological.map(r => r.fiscal_year))}
                      </tr>
                    </thead>
                    <tbody>
                      {lines.map((line) => {
                        if (line.group && collapsedSections[line.group]) return null;

                        const showSection = line.section && line.section !== lastSection;
                        if (line.section) lastSection = line.section;
                        return (
                          <React.Fragment key={line.key + (line.section || "")}>
                            {showSection && (
                              <tr>
                                <td colSpan={chronological.length * 2} className="px-4 pt-3 pb-1">
                                  <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-widest">{line.section}</span>
                                </td>
                              </tr>
                            )}
                            <tr className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}>
                              <td className={`px-4 py-1 text-xs ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-8" : ""} ${line.subIndent ? "pl-12 text-slate-400 italic" : ""}`}>
                                {line.label}
                              </td>
                              {chronologicalBs.map((r, colIdx) => {
                                const prevRow = colIdx > 0 ? chronologicalBs[colIdx - 1] : null;
                                const currentVal = r[line.key] as number | null;
                                const prevVal = prevRow ? (prevRow[line.key] as number | null) : null;
                                return (
                                  <React.Fragment key={`bs-${r.fiscal_year}-${line.key}`}>
                                    {colIdx > 0 && (
                                      <td className="px-1 py-1 text-center align-top">
                                        {renderDelta(currentVal, prevVal)}
                                      </td>
                                    )}
                                    <td className={`px-3 py-1 text-right text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
                                      {fmtCell(r[line.key] as number | null)}
                                    </td>
                                  </React.Fragment>
                                );
                              })}
                            </tr>
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-1 text-[10px] text-slate-400 italic">
                  Rubric references in parentheses per Belgian GAAP. Current Liabilities = Total - Equity - LT Debt. Other items are residual calculations.
                </p>
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== Administrators tab ===== */}
        <TabsContent value="administrators" className="mt-3">
          {(() => {
            const currentAdmins = (structure?.administrators || []).filter(
              (a) => !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > new Date()
            );
            const pastAdmins = (structure?.administrators || []).filter(
              (a) => a.mandate_end && a.mandate_end !== "" && new Date(a.mandate_end) <= new Date()
            );

            if (currentAdmins.length === 0 && pastAdmins.length === 0) {
              return (
                <p className="py-8 text-center text-sm text-slate-500">
                  No administrator data available for this company.
                </p>
              );
            }

            function exportAdminsCsv() {
              const all = [...currentAdmins, ...pastAdmins];
              const headers = ["Name", "Role", "Status", "Start", "End", "Identifier"];
              const now = new Date();
              const rows = all.map(a => {
                const active = !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > now;
                return [a.name, a.role_label || a.role, active ? "Active" : "Ended", a.mandate_start || "", a.mandate_end || "", a.identifier || ""];
              });
              downloadCsv(`${detail?.name || cbe}_administrators.csv`, headers, rows);
            }

            return (
              <div className="space-y-4">
                <div className="flex items-center justify-end">
                  <ExportButtons onExportCSV={exportAdminsCsv} onPrint={() => window.print()} />
                </div>
                {/* Current Administrators */}
                {currentAdmins.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
                      Current Administrators ({currentAdmins.length})
                    </h3>
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                      {currentAdmins.map((admin, i) => {
                        const adminCbe = cleanCbe(admin.identifier);
                        const pe = personEnrichments[admin.name];
                        return (
                          <Card key={`current-${admin.name}-${admin.role}-${i}`}>
                            <CardContent className="p-3">
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-green-500" />
                                    {adminCbe ? (
                                      <GoogleSearchLink query={admin.name}>
                                        <Link
                                          href={`/company/${adminCbe}`}
                                          className="font-bold text-sm text-indigo-600 hover:underline truncate"
                                        >
                                          {admin.name}
                                        </Link>
                                      </GoogleSearchLink>
                                    ) : (
                                      <GoogleSearchLink query={admin.name}>
                                        <Link
                                          href={`/people?q=${encodeURIComponent(admin.name)}`}
                                          className="font-bold text-sm text-indigo-600 hover:underline truncate"
                                        >
                                          {admin.name}
                                        </Link>
                                      </GoogleSearchLink>
                                    )}
                                  </div>
                                  <p className="mt-1 text-sm font-medium text-slate-700">
                                    {admin.role_label}
                                  </p>
                                  {admin.mandate_start && (
                                    <p className="mt-1 text-xs text-slate-500">
                                      Since {admin.mandate_start}
                                    </p>
                                  )}
                                  {adminCbe && (
                                    <p className="mt-1 text-xs text-slate-400 font-mono">
                                      {fmtCbe(adminCbe)}
                                    </p>
                                  )}
                                </div>
                                <div className="flex items-center gap-1 shrink-0">
                                  <button
                                    onClick={async (e) => {
                                      e.stopPropagation();
                                      if (pe?.summary || pe?.loading) return;
                                      setPersonEnrichments((prev) => ({
                                        ...prev,
                                        [admin.name]: { summary: "", loading: true },
                                      }));
                                      try {
                                        // Check for existing enrichment first
                                        const existing = await getPersonEnrichment(admin.name);
                                        if (existing?.summary) {
                                          setPersonEnrichments((prev) => ({
                                            ...prev,
                                            [admin.name]: { summary: existing.summary, loading: false },
                                          }));
                                          return;
                                        }
                                        const result = await enrichPerson(admin.name);
                                        setPersonEnrichments((prev) => ({
                                          ...prev,
                                          [admin.name]: { summary: result?.summary || "", loading: false },
                                        }));
                                      } catch {
                                        setPersonEnrichments((prev) => ({
                                          ...prev,
                                          [admin.name]: { summary: "", loading: false },
                                        }));
                                      }
                                    }}
                                    title="Enrich with AI"
                                    className={`h-6 w-6 flex items-center justify-center rounded transition-colors ${
                                      pe?.summary
                                        ? "text-indigo-500"
                                        : "text-slate-300 hover:text-indigo-500"
                                    }`}
                                  >
                                    {pe?.loading ? (
                                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    ) : (
                                      <Sparkles className="h-3.5 w-3.5" />
                                    )}
                                  </button>
                                  <button
                                    onClick={async (e) => {
                                      e.stopPropagation();
                                      try {
                                        await addPeopleFavourite(admin.name);
                                        const btn = e.currentTarget;
                                        btn.classList.add("text-yellow-500");
                                        btn.title = "Saved!";
                                      } catch {}
                                    }}
                                    title="Save person to favourites"
                                    className="h-6 w-6 flex items-center justify-center rounded text-slate-300 hover:text-yellow-500 transition-colors"
                                  >
                                    <Star className="h-3.5 w-3.5" />
                                  </button>
                                  <Badge
                                    variant="secondary"
                                    className="text-[10px] bg-green-50 text-green-700 border-green-200"
                                  >
                                    Active
                                  </Badge>
                                </div>
                              </div>
                              {pe?.summary && (
                                <div className="mt-2 pt-2 border-t border-indigo-100">
                                  <div className="flex items-start gap-1.5">
                                    <Sparkles className="h-3 w-3 text-indigo-400 mt-0.5 shrink-0" />
                                    <p className="text-xs text-slate-600 leading-relaxed">{pe.summary}</p>
                                  </div>
                                </div>
                              )}
                            </CardContent>
                          </Card>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Past Administrators */}
                {pastAdmins.length > 0 && (
                  <div>
                    <button
                      type="button"
                      className="mb-3 flex items-center gap-1 text-xs font-bold uppercase tracking-wider text-slate-400 border-l-[3px] border-slate-300 pl-2 hover:text-slate-600 transition-colors"
                      onClick={(e) => {
                        const content = (e.currentTarget as HTMLElement).nextElementSibling;
                        const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                        if (content) {
                          content.classList.toggle("hidden");
                        }
                        if (chevron) {
                          chevron.classList.toggle("rotate-180");
                        }
                      }}
                    >
                      Past Administrators ({pastAdmins.length})
                      <ChevronDown data-chevron className="h-3.5 w-3.5 transition-transform" />
                    </button>
                    <div className="hidden">
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {pastAdmins.map((admin, i) => {
                          const adminCbe = cleanCbe(admin.identifier);
                          const pe = personEnrichments[admin.name];
                          return (
                            <Card key={`past-${admin.name}-${admin.role}-${i}`} className="opacity-75">
                              <CardContent className="p-3">
                                <div className="flex items-start justify-between gap-2">
                                  <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-slate-300" />
                                      {adminCbe ? (
                                        <Link
                                          href={`/company/${adminCbe}`}
                                          className="font-bold text-sm text-slate-500 hover:underline truncate"
                                        >
                                          {admin.name}
                                        </Link>
                                      ) : (
                                        <Link
                                          href={`/people?q=${encodeURIComponent(admin.name)}`}
                                          className="font-bold text-sm text-slate-500 hover:underline truncate"
                                        >
                                          {admin.name}
                                        </Link>
                                      )}
                                    </div>
                                    <p className="mt-1 text-sm text-slate-500">
                                      {admin.role_label}
                                    </p>
                                    <p className="mt-1 text-xs text-slate-400">
                                      {admin.mandate_start ?? "?"} - {admin.mandate_end}
                                    </p>
                                    {adminCbe && (
                                      <p className="mt-1 text-xs text-slate-400 font-mono">
                                        {fmtCbe(adminCbe)}
                                      </p>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-1 shrink-0">
                                    <button
                                      onClick={async (e) => {
                                        e.stopPropagation();
                                        if (pe?.summary || pe?.loading) return;
                                        setPersonEnrichments((prev) => ({
                                          ...prev,
                                          [admin.name]: { summary: "", loading: true },
                                        }));
                                        try {
                                          const existing = await getPersonEnrichment(admin.name);
                                          if (existing?.summary) {
                                            setPersonEnrichments((prev) => ({
                                              ...prev,
                                              [admin.name]: { summary: existing.summary, loading: false },
                                            }));
                                            return;
                                          }
                                          const result = await enrichPerson(admin.name);
                                          setPersonEnrichments((prev) => ({
                                            ...prev,
                                            [admin.name]: { summary: result?.summary || "", loading: false },
                                          }));
                                        } catch {
                                          setPersonEnrichments((prev) => ({
                                            ...prev,
                                            [admin.name]: { summary: "", loading: false },
                                          }));
                                        }
                                      }}
                                      title="Enrich with AI"
                                      className={`h-6 w-6 flex items-center justify-center rounded transition-colors ${
                                        pe?.summary
                                          ? "text-indigo-500"
                                          : "text-slate-300 hover:text-indigo-500"
                                      }`}
                                    >
                                      {pe?.loading ? (
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                      ) : (
                                        <Sparkles className="h-3.5 w-3.5" />
                                      )}
                                    </button>
                                    <Badge
                                      variant="secondary"
                                      className="text-[10px] shrink-0 bg-slate-50 text-slate-400 border-slate-200"
                                    >
                                      Ended
                                    </Badge>
                                  </div>
                                </div>
                                {pe?.summary && (
                                  <div className="mt-2 pt-2 border-t border-indigo-100">
                                    <div className="flex items-start gap-1.5">
                                      <Sparkles className="h-3 w-3 text-indigo-400 mt-0.5 shrink-0" />
                                      <p className="text-xs text-slate-600 leading-relaxed">{pe.summary}</p>
                                    </div>
                                  </div>
                                )}
                              </CardContent>
                            </Card>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== Structure tab ===== */}
        <TabsContent value="structure" className="mt-3">
          {!structure ||
          (structure.shareholders.length === 0 &&
            structure.participating_interests.length === 0) ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No structure data available for this company.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-end">
                <ExportButtons onExportCSV={() => {
                  const headers = ["Type", "Name", "Ownership %", "Country/Type", "Identifier", "Fiscal Year"];
                  const rows = [
                    ...structure.shareholders.map(s => ["Shareholder", s.name, s.ownership_pct != null ? s.ownership_pct.toFixed(1) : "", s.shareholder_type || "", s.identifier || "", s.fiscal_year || ""]),
                    ...structure.participating_interests.map(p => ["Subsidiary", p.name, p.ownership_pct != null ? p.ownership_pct.toFixed(1) : "", p.country || "", p.identifier || "", p.fiscal_year || ""]),
                  ];
                  downloadCsv(`${detail?.name || cbe}_structure.csv`, headers, rows);
                }} onPrint={() => window.print()} />
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
              {/* Left column: collapsible cards */}
              <div className="space-y-3">
                  {/* Shareholders (collapsible) */}
                  {structure.shareholders.length > 0 && (
                    <Card>
                      <CardContent>
                        <button
                          type="button"
                          onClick={(e) => {
                            const content = (e.currentTarget as HTMLElement).nextElementSibling;
                            const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                            if (content) content.classList.toggle("hidden");
                            if (chevron) chevron.classList.toggle("rotate-180");
                          }}
                          className="w-full flex items-center justify-between mb-2"
                        >
                          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
                            Shareholders ({structure.shareholders.length})
                          </h3>
                          <ChevronDown data-chevron className="h-4 w-4 text-slate-400 transition-transform" />
                        </button>
                        <div className="space-y-1.5">
                          {structure.shareholders.map((sh, i) => {
                            const shCbe = cleanCbe(sh.identifier);
                            return (
                              <div
                                key={`${sh.name}-${i}`}
                                className="rounded-md border px-3 py-2"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  {shCbe ? (
                                    <Link
                                      href={`/company/${shCbe}`}
                                      className="font-semibold text-sm text-indigo-600 hover:underline"
                                    >
                                      {sh.name}
                                    </Link>
                                  ) : (
                                    <Link
                                      href={`/people?q=${encodeURIComponent(sh.name)}`}
                                      className="font-semibold text-sm text-indigo-600 hover:underline"
                                    >
                                      {sh.name}
                                    </Link>
                                  )}
                                  <div className="flex items-center gap-2 shrink-0">
                                    {sh.ownership_pct != null && (
                                      <span className="font-mono text-xs font-medium text-slate-700">
                                        {sh.ownership_pct.toFixed(1)}%
                                      </span>
                                    )}
                                    {sh.shareholder_type && (
                                      <Badge
                                        variant="secondary"
                                        className="text-[10px]"
                                      >
                                        {sh.shareholder_type}
                                      </Badge>
                                    )}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {/* Participating Interests (collapsible) */}
                  {structure.participating_interests.length > 0 && (
                    <Card>
                      <CardContent>
                        <button
                          type="button"
                          onClick={(e) => {
                            const content = (e.currentTarget as HTMLElement).nextElementSibling;
                            const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                            if (content) content.classList.toggle("hidden");
                            if (chevron) chevron.classList.toggle("rotate-180");
                          }}
                          className="w-full flex items-center justify-between mb-2"
                        >
                          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-orange-500 pl-2">
                            Participating Interests ({structure.participating_interests.length})
                          </h3>
                          <ChevronDown data-chevron className="h-4 w-4 text-slate-400 transition-transform" />
                        </button>
                        <div className="space-y-1.5">
                          {structure.participating_interests.map((pi, i) => {
                            const piCbe = cleanCbe(pi.identifier);
                            return (
                              <div
                                key={`${pi.name}-${i}`}
                                className="rounded-md border px-3 py-2"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  {piCbe ? (
                                    <Link
                                      href={`/company/${piCbe}`}
                                      className="font-semibold text-sm text-indigo-600 hover:underline"
                                    >
                                      {pi.name}
                                    </Link>
                                  ) : (
                                    <Link
                                      href={`/people?q=${encodeURIComponent(pi.name)}`}
                                      className="font-semibold text-sm text-indigo-600 hover:underline"
                                    >
                                      {pi.name}
                                    </Link>
                                  )}
                                  <div className="flex items-center gap-2 shrink-0">
                                    {pi.ownership_pct != null && (
                                      <span className="font-mono text-xs font-medium text-slate-700">
                                        {pi.ownership_pct.toFixed(1)}%
                                      </span>
                                    )}
                                    {pi.country && (
                                      <Badge
                                        variant="secondary"
                                        className="text-[10px]"
                                      >
                                        {pi.country}
                                      </Badge>
                                    )}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </CardContent>
                    </Card>
                  )}
              </div>

              {/* Right column: visual timelines */}
              <div className="space-y-3">
                {/* Shareholder Timeline */}
                {structure.shareholders.filter(sh => sh.fiscal_year).length > 0 && (
                  <Card>
                    <CardContent className="pt-3 pb-3">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2 mb-3">
                        Shareholder Timeline
                      </h3>
                      <div className="relative pl-6">
                        <div className="absolute left-2 top-0 bottom-0 w-px bg-green-200" />
                        {structure.shareholders
                          .filter(sh => sh.fiscal_year)
                          .sort((a, b) => String(b.fiscal_year).localeCompare(String(a.fiscal_year)))
                          .map((sh, i) => (
                            <div key={i} className="relative mb-3 last:mb-0">
                              <div className="absolute -left-4 top-1 w-2.5 h-2.5 rounded-full bg-green-500 border-2 border-white" />
                              <div className="text-xs font-mono text-slate-400 mb-0.5">{sh.fiscal_year}</div>
                              <div className="text-sm font-medium text-slate-900">{sh.name}</div>
                              {sh.ownership_pct != null && (
                                <div className="text-xs text-slate-500">{sh.ownership_pct}% ownership</div>
                              )}
                            </div>
                          ))}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Subsidiary Timeline */}
                {structure.participating_interests.filter(pi => pi.fiscal_year).length > 0 && (
                  <Card>
                    <CardContent className="pt-3 pb-3">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-orange-500 pl-2 mb-3">
                        Subsidiary Timeline
                      </h3>
                      <div className="relative pl-6">
                        <div className="absolute left-2 top-0 bottom-0 w-px bg-orange-200" />
                        {structure.participating_interests
                          .filter(pi => pi.fiscal_year)
                          .sort((a, b) => String(b.fiscal_year).localeCompare(String(a.fiscal_year)))
                          .map((pi, i) => (
                            <div key={i} className="relative mb-3 last:mb-0">
                              <div className="absolute -left-4 top-1 w-2.5 h-2.5 rounded-full bg-orange-500 border-2 border-white" />
                              <div className="text-xs font-mono text-slate-400 mb-0.5">{pi.fiscal_year}</div>
                              <div className="text-sm font-medium text-slate-900">{pi.name}</div>
                              {pi.ownership_pct != null && (
                                <div className="text-xs text-slate-500">{pi.ownership_pct}% ownership</div>
                              )}
                            </div>
                          ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
            </div>
          )}
        </TabsContent>

        {/* ===== Network tab ===== */}
        <TabsContent value="network" className="mt-3">
          <NetworkGraph cbe={cbe} companyName={detail?.name || cbe} />
        </TabsContent>

        {/* ===== Credit Analysis tab ===== */}
        <TabsContent value="credit" className="mt-3">
          {!financials || financials.summary.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No financial data available for credit analysis.
            </p>
          ) : (() => {
            const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);
            const chronological = [...sorted].reverse();

            // Compute ratios for each year
            const ratios = sorted.map((row) => {
              const grossDebt = (row.lt_financial_debt ?? 0) + (row.st_financial_debt ?? 0);
              const netDebt = grossDebt - (row.cash ?? 0) - (row.current_investments ?? 0);
              const ebitda = row.ebitda;
              const ebit = row.ebit;
              const equity = row.equity;
              const netProfit = row.net_profit;
              const revenue = row.revenue;
              const finCharges = row.financial_charges;
              const tradeRec = row.trade_receivables;
              const tradePay = row.trade_payables;
              const stDebt = row.st_financial_debt;

              const totalAssets = row.total_assets;
              const netDebtEbitda = ebitda && ebitda !== 0 ? netDebt / ebitda : null;
              const debtEquity = equity && equity !== 0 ? grossDebt / equity : null;
              const equityRatio = totalAssets && totalAssets !== 0 ? (equity ?? 0) / totalAssets * 100 : null;
              const interestCoverage = finCharges && finCharges !== 0 ? (ebit ?? 0) / Math.abs(finCharges) : null;
              const cashStDebt = stDebt && stDebt !== 0 ? ((row.cash ?? 0) + (row.current_investments ?? 0)) / stDebt : null;
              const roe = equity && equity !== 0 ? ((netProfit ?? 0) / equity) * 100 : null;
              const ebitdaMargin = revenue && revenue > 0 ? ((ebitda ?? 0) / revenue) * 100 : null;
              const dso = revenue && revenue > 0 ? ((tradeRec ?? 0) / revenue) * 365 : null;
              const dpo = revenue && revenue > 0 ? ((tradePay ?? 0) / revenue) * 365 : null;
              const dscr = (finCharges || stDebt) ? (ebitda ?? 0) / (Math.abs(finCharges ?? 0) + (stDebt ?? 0)) : null;

              return {
                fiscal_year: row.fiscal_year,
                netDebtEbitda,
                debtEquity,
                equityRatio,
                interestCoverage,
                cashStDebt,
                roe,
                ebitdaMargin,
                dso,
                dpo,
                netDebt,
                grossDebt,
                dscr,
              };
            });
            const chronologicalRatios = [...ratios].reverse();

            const latest = ratios[0];
            const latestRow = sorted[0];

            // Color thresholds
            function leverageColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v < 3) return "bg-green-50 border-green-200 text-green-800";
              if (v <= 5) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function debtEquityColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v < 1) return "bg-green-50 border-green-200 text-green-800";
              if (v <= 2) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function coverageColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 3) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 1.5) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function cashRatioColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 1) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 0.5) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function marginColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 15) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 8) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function roeColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 15) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 8) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function fmtRatio(v: number | null, suffix = "x"): string {
              if (v == null || !isFinite(v)) return "\u2014";
              return `${v.toFixed(1)}${suffix}`;
            }
            function fmtDays(v: number | null): string {
              if (v == null || !isFinite(v)) return "\u2014";
              return `${Math.round(v)}d`;
            }

            function equityRatioColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 40) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 20) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function dscrColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 2) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 1.2) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }

            const lr = latestRow; // shorthand for formula details
            const metricCards = [
              { label: "Net Debt / EBITDA", value: fmtRatio(latest.netDebtEbitda), colorFn: leverageColor, raw: latest.netDebtEbitda, formula: "(LT Fin Debt + ST Fin Debt − Cash − Investments) / EBITDA", detail: `(${fmtEur(lr.lt_financial_debt)} + ${fmtEur(lr.st_financial_debt)} − ${fmtEur(lr.cash)} − ${fmtEur(lr.current_investments)}) / ${fmtEur(lr.ebitda)}` },
              { label: "Debt / Equity", value: fmtRatio(latest.debtEquity), colorFn: debtEquityColor, raw: latest.debtEquity, formula: "(LT Fin Debt + ST Fin Debt) / Equity", detail: `(${fmtEur(lr.lt_financial_debt)} + ${fmtEur(lr.st_financial_debt)}) / ${fmtEur(lr.equity)}` },
              { label: "Equity Ratio", value: fmtRatio(latest.equityRatio, "%"), colorFn: equityRatioColor, raw: latest.equityRatio, formula: "Equity / Total Assets × 100", detail: `${fmtEur(lr.equity)} / ${fmtEur(lr.total_assets)}` },
              { label: "Interest Coverage", value: fmtRatio(latest.interestCoverage), colorFn: coverageColor, raw: latest.interestCoverage, formula: "EBIT / |Financial Charges|", detail: `${fmtEur(lr.ebit)} / ${fmtEur(lr.financial_charges)}` },
              { label: "Cash / ST Debt", value: fmtRatio(latest.cashStDebt), colorFn: cashRatioColor, raw: latest.cashStDebt, formula: "(Cash + Investments) / ST Financial Debt", detail: `(${fmtEur(lr.cash)} + ${fmtEur(lr.current_investments)}) / ${fmtEur(lr.st_financial_debt)}` },
              { label: "Debt Service", value: fmtRatio(latest.dscr), colorFn: dscrColor, raw: latest.dscr, formula: "EBITDA / (|Fin Charges| + ST Fin Debt)", detail: `${fmtEur(lr.ebitda)} / (${fmtEur(lr.financial_charges)} + ${fmtEur(lr.st_financial_debt)})` },
              { label: "ROE", value: fmtRatio(latest.roe, "%"), colorFn: roeColor, raw: latest.roe, formula: "Net Profit / Equity × 100", detail: `${fmtEur(lr.net_profit)} / ${fmtEur(lr.equity)}` },
            ];

            function exportCreditCsv() {
              const headers = ["Metric", ...chronologicalRatios.map(r => `FY${r.fiscal_year}`)];
              const lines = [
                { label: "Net Debt / EBITDA", key: "netDebtEbitda" },
                { label: "Debt / Equity", key: "debtEquity" },
                { label: "Equity Ratio %", key: "equityRatio" },
                { label: "Interest Coverage", key: "interestCoverage" },
                { label: "Cash / ST Debt", key: "cashStDebt" },
                { label: "DSCR", key: "dscr" },
                { label: "ROE %", key: "roe" },
                { label: "EBITDA Margin %", key: "ebitdaMargin" },
                { label: "DSO (days)", key: "dso" },
                { label: "DPO (days)", key: "dpo" },
              ];
              const rows = lines.map(l => [l.label, ...chronologicalRatios.map(r => {
                const v = (r as any)[l.key];
                return v != null && isFinite(v) ? v.toFixed(1) : "";
              })]);
              downloadCsv(`${detail?.name || cbe}_credit.csv`, headers, rows);
            }

            return (
              <div className="space-y-6">
                {/* Key Metrics Cards */}
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-purple-500 pl-2">
                      Key Ratios (FY{latest.fiscal_year})
                    </h3>
                    <ExportButtons onExportCSV={exportCreditCsv} onPrint={() => window.print()} />
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-2">
                    {metricCards.map((m) => (
                      <FormulaTooltip key={m.label} formula={m.formula} detail={m.detail}>
                        <div className={`rounded-lg border p-2 text-center cursor-default ${m.colorFn(m.raw)}`}>
                          <div className="text-[10px] font-medium uppercase tracking-wider opacity-70">{m.label}</div>
                          <div className="mt-1 text-base font-bold">{m.value}</div>
                        </div>
                      </FormulaTooltip>
                    ))}
                  </div>
                </div>

                {/* Leverage Ratios Table */}
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-red-500 pl-2">
                    Leverage
                  </h3>
                  <div className="rounded-lg border overflow-x-auto bg-white">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-slate-50">
                          <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                          {chronologicalRatios.map((r) => (
                            <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="(LT Fin Debt + ST Fin Debt − Cash − Investments) / EBITDA">Net Debt / EBITDA</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.netDebtEbitda)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="(LT Fin Debt + ST Fin Debt) / Equity">Debt / Equity</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.debtEquity)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow className="bg-slate-50/50">
                          <TableCell className="text-xs text-slate-600 py-1 font-medium"><FormulaTooltip formula="Equity / Total Assets × 100">Equity Ratio (Equity / Assets)</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className={`text-right font-mono text-xs py-1 font-medium ${r.equityRatio != null && r.equityRatio >= 40 ? "text-green-700" : r.equityRatio != null && r.equityRatio >= 20 ? "text-amber-700" : r.equityRatio != null ? "text-rose-500" : ""}`}>{fmtRatio(r.equityRatio, "%")}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="EBIT / |Financial Charges|">Interest Coverage</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.interestCoverage)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="LT Fin Debt + ST Fin Debt − Cash − Investments">Net Debt</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(r.netDebt)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow className="bg-slate-50/50">
                          <TableCell className="text-xs text-slate-600 py-1 font-medium"><FormulaTooltip formula="EBITDA / (|Financial Charges| + ST Financial Debt)">Debt Service (DSCR)</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className={`text-right font-mono text-xs py-1 font-medium ${r.dscr != null && r.dscr >= 2 ? "text-green-700" : r.dscr != null && r.dscr >= 1.2 ? "text-amber-700" : r.dscr != null ? "text-rose-500" : ""}`}>{fmtRatio(r.dscr)}</TableCell>
                          ))}
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </div>

                {/* Liquidity */}
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-amber-500 pl-2">
                    Liquidity
                  </h3>
                  <div className="rounded-lg border overflow-x-auto bg-white">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-slate-50">
                          <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                          {chronologicalRatios.map((r) => (
                            <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="(Cash + Investments) / ST Financial Debt">Cash / ST Debt</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.cashStDebt)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="Cash (54/58) + Current Investments (50/53)">Cash & Investments</FormulaTooltip></TableCell>
                          {chronological.map((row) => (
                            <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">
                              {fmtEur(((row.cash ?? 0) + (row.current_investments ?? 0)) || null)}
                            </TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">ST Financial Debt</TableCell>
                          {chronological.map((row) => (
                            <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.st_financial_debt)}</TableCell>
                          ))}
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </div>

                {/* Profitability */}
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
                    Profitability
                  </h3>
                  <div className="rounded-lg border overflow-x-auto bg-white">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-slate-50">
                          <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                          {chronologicalRatios.map((r) => (
                            <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="EBITDA / Revenue × 100">EBITDA Margin</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.ebitdaMargin, "%")}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="Net Profit / Total Equity × 100">ROE</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.roe, "%")}</TableCell>
                          ))}
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </div>

                {/* Working Capital */}
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-blue-500 pl-2">
                    Working Capital
                  </h3>
                  <div className="rounded-lg border overflow-x-auto bg-white">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-slate-50">
                          <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                          {chronologicalRatios.map((r) => (
                            <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="Trade Receivables / Revenue × 365">DSO (days)</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(r.dso)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="Trade Payables / Revenue × 365">DPO (days)</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(r.dpo)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="DSO − DPO (lower is better)">Cash Conversion (DSO - DPO)</FormulaTooltip></TableCell>
                          {chronologicalRatios.map((r) => {
                            const ccc = r.dso != null && r.dpo != null ? r.dso - r.dpo : null;
                            return (
                              <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(ccc)}</TableCell>
                            );
                          })}
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </div>

                <p className="text-[10px] text-slate-400 italic">
                  Thresholds: Net Debt/EBITDA &lt;3x green, 3-5x amber, &gt;5x red. Interest Coverage &gt;3x green, 1.5-3x amber, &lt;1.5x red. DSCR &ge;2x green, 1.2-2x amber, &lt;1.2x red.
                </p>
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== Publications tab ===== */}
        <TabsContent value="publications" className="mt-3">
          {!structure ||
          structure.staatsblad_publications.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-sm text-slate-500 mb-4">No Staatsblad publications available.</p>
              <button
                onClick={async () => {
                  setNbbLoading(true);
                  try {
                    const res = await fetch(`/api/staatsblad/${cbe}/load`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                    });
                    const data = await res.json();
                    if (data.publications_stored > 0) {
                      // Refetch structure to get new publications
                      getCompanyStructure(cbe).then((s) =>
                        setStructure(s as unknown as StructureData)
                      );
                    }
                    setNbbResult(data.publications_stored > 0 ? "success" : "no-data");
                  } catch {
                    setNbbResult("error");
                  } finally {
                    setNbbLoading(false);
                  }
                }}
                disabled={nbbLoading}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-medium text-indigo-600 border border-indigo-300 rounded-lg hover:bg-indigo-50 disabled:opacity-50 transition-colors"
              >
                {nbbLoading ? (
                  <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading publications...</>
                ) : (
                  <><Download className="w-3.5 h-3.5" /> Load from Staatsblad</>
                )}
              </button>
              {nbbResult === "no-data" && (
                <p className="text-xs text-slate-400 mt-2">No publications found for this company.</p>
              )}
            </div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-slate-400 pl-2">
                  Staatsblad Publications ({structure.staatsblad_publications.length})
                </h3>
                <ExportButtons onExportCSV={() => {
                  const headers = ["Date", "Type", "Reference", "PDF URL"];
                  const rows = structure.staatsblad_publications.map(p => [p.pub_date, p.pub_type || "", p.reference || "", p.pdf_url ? `https://www.ejustice.just.fgov.be${p.pdf_url}` : ""]);
                  downloadCsv(`${detail?.name || cbe}_publications.csv`, headers, rows);
                }} onPrint={() => window.print()} />
              </div>
              <div className="rounded-lg border overflow-x-auto bg-white">
                <table className="w-full">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-200">
                      <th className="px-3 py-1.5 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[90px]">Date</th>
                      <th className="px-3 py-1.5 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[90px]">Type</th>
                      <th className="px-3 py-1.5 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider">Summary</th>
                      <th className="px-3 py-1.5 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[100px]">Reference</th>
                      <th className="px-3 py-1.5 text-center text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[40px]">PDF</th>
                    </tr>
                  </thead>
                  <tbody>
                    {structure.staatsblad_publications.slice(0, 50).map((pub, i) => {
                      const typeInfo = pub.pub_type
                        ? PUB_TYPE_MAP[pub.pub_type.toUpperCase()] ??
                          Object.entries(PUB_TYPE_MAP).find(([key]) =>
                            pub.pub_type!.toUpperCase().includes(key)
                          )?.[1] ??
                          null
                        : null;

                      return (
                        <tr key={`${pub.pub_date}-${i}`} className="border-t border-slate-100 hover:bg-slate-50/50">
                          <td className="px-3 py-1 text-xs font-mono text-slate-600">{pub.pub_date}</td>
                          <td className="px-3 py-1">
                            {typeInfo ? (
                              <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${typeInfo.color}`}>
                                {typeInfo.label}
                              </span>
                            ) : pub.pub_type ? (
                              <span className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-semibold bg-slate-100 text-slate-500">
                                {pub.pub_type.length > 15 ? pub.pub_type.slice(0, 15) + "..." : pub.pub_type}
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-1 text-xs text-slate-600 truncate max-w-[300px]">
                            {typeInfo
                              ? typeInfo.summary
                              : pub.pub_type ?? "Publication in the Belgian Official Gazette"}
                          </td>
                          <td className="px-3 py-1 text-xs font-mono text-slate-400">
                            {pub.reference ? `#${pub.reference}` : "\u2014"}
                          </td>
                          <td className="px-3 py-1 text-center">
                            {pub.pdf_url ? (
                              <a
                                href={
                                  pub.pdf_url.startsWith("http")
                                    ? pub.pdf_url
                                    : `https://www.ejustice.just.fgov.be${pub.pdf_url}`
                                }
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-indigo-50 text-indigo-500 hover:text-indigo-700 transition-colors"
                                title="View PDF"
                              >
                                <FileText className="h-3.5 w-3.5" />
                              </a>
                            ) : (
                              <span className="text-slate-200">{"\u2014"}</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {structure.staatsblad_publications.length > 50 && (
                <p className="mt-1 text-[10px] text-slate-400 italic">
                  Showing 50 of {structure.staatsblad_publications.length} publications.
                </p>
              )}
            </div>
          )}
        </TabsContent>

        {/* ===== Benchmark tab ===== */}
        <TabsContent value="benchmark" className="mt-3">
          {!benchmark ? (
            <div className="py-8 text-center">
              <Loader2 className="w-6 h-6 animate-spin text-indigo-500 mx-auto mb-2" />
              <p className="text-sm text-slate-400">Loading sector benchmarks...</p>
            </div>
          ) : benchmark.error ? (
            <p className="py-8 text-center text-sm text-slate-500">
              {benchmark.error === "no_nace" ? "No NACE code assigned to this company." : "No financial data available for benchmarking."}
            </p>
          ) : (() => {
            const fmtBenchVal = (v: number | null, format: string) => {
              if (v == null) return "—";
              if (format === "pct") return `${v.toFixed(1)}%`;
              if (format === "num") return v.toLocaleString("en-GB", { maximumFractionDigits: 0 });
              if (Math.abs(v) >= 1_000_000) return `€${(v / 1_000_000).toFixed(1)}M`;
              if (Math.abs(v) >= 1_000) return `€${(v / 1_000).toFixed(0)}K`;
              return `€${v.toFixed(0)}`;
            };

            const getQuartileLabel = (pct: number) => {
              if (pct >= 75) return { label: "Top quartile", color: "text-emerald-600 bg-emerald-50 border-emerald-200", dot: "bg-emerald-500" };
              if (pct >= 50) return { label: "Above median", color: "text-indigo-600 bg-indigo-50 border-indigo-200", dot: "bg-indigo-500" };
              if (pct >= 25) return { label: "Below median", color: "text-amber-600 bg-amber-50 border-amber-200", dot: "bg-amber-500" };
              return { label: "Bottom quartile", color: "text-rose-500 bg-rose-50 border-rose-200", dot: "bg-rose-400" };
            };

            // Score: average percentile across all metrics
            const avgPercentile = benchmark.benchmarks.length > 0
              ? benchmark.benchmarks.reduce((sum, b) => sum + (b.percentile ?? 0), 0) / benchmark.benchmarks.length
              : 0;
            const overallQuartile = getQuartileLabel(avgPercentile);

            return (
              <div className="space-y-5">
                {/* Header card */}
                <div className="rounded-xl border border-slate-200 bg-gradient-to-r from-slate-50 to-white p-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <BarChart3 className="h-4 w-4 text-amber-500" />
                        <h3 className="text-sm font-semibold text-slate-800">Sector Performance</h3>
                      </div>
                      <p className="text-xs text-slate-500">
                        vs. <span className="font-medium text-slate-700">{benchmark.peer_count.toLocaleString()}</span> companies in{" "}
                        <span className="font-medium text-slate-700">{benchmark.nace_label}</span>
                      </p>
                      <p className="text-[10px] text-slate-400 mt-0.5">NACE {benchmark.nace_code} · FY{benchmark.fiscal_year}</p>
                    </div>
                    <div className="text-right">
                      <div className="text-2xl font-bold text-slate-800 font-mono">P{avgPercentile.toFixed(0)}</div>
                      <span className={`inline-flex items-center gap-1.5 text-[10px] font-medium rounded-full border px-2 py-0.5 mt-1 ${overallQuartile.color}`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${overallQuartile.dot}`} />
                        {overallQuartile.label} overall
                      </span>
                    </div>
                  </div>
                </div>

                {/* Metric cards — 2-column grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {benchmark.benchmarks.map((b) => {
                    const pct = b.percentile ?? 0;
                    const q = getQuartileLabel(pct);
                    const barColor = pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-indigo-500" : pct >= 25 ? "bg-amber-500" : "bg-rose-400";

                    return (
                      <div key={b.metric} className="rounded-xl border border-slate-100 bg-white p-4 hover:shadow-sm transition-shadow">
                        {/* Metric header */}
                        <div className="flex items-center justify-between mb-3">
                          <span className="text-xs font-semibold text-slate-700">{b.metric}</span>
                          <span className={`inline-flex items-center gap-1 text-[10px] font-semibold rounded-full border px-2 py-0.5 ${q.color}`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${q.dot}`} />
                            P{pct.toFixed(0)}
                          </span>
                        </div>

                        {/* Company value — prominent */}
                        <div className="text-lg font-bold text-slate-900 font-mono mb-3">
                          {fmtBenchVal(b.value, b.format)}
                        </div>

                        {/* Percentile bar */}
                        <div className="relative h-2.5 bg-slate-100 rounded-full overflow-hidden mb-2">
                          <div className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${pct}%` }} />
                          {/* Quartile markers */}
                          <div className="absolute top-0 bottom-0 left-1/4 w-px bg-slate-200" />
                          <div className="absolute top-0 bottom-0 left-1/2 w-px bg-slate-300" />
                          <div className="absolute top-0 bottom-0 left-3/4 w-px bg-slate-200" />
                          {/* Company marker */}
                          <div className="absolute top-[-3px] bottom-[-3px] w-0.5 bg-slate-800 rounded-full" style={{ left: `${pct}%` }} />
                        </div>

                        {/* Peer distribution */}
                        <div className="grid grid-cols-3 gap-2 text-center">
                          <div className="rounded-md bg-slate-50 py-1.5 px-1">
                            <div className="text-[9px] text-slate-400 uppercase tracking-wider">P25</div>
                            <div className="text-[11px] font-mono font-medium text-slate-600">{fmtBenchVal(b.p25, b.format)}</div>
                          </div>
                          <div className="rounded-md bg-slate-50 py-1.5 px-1">
                            <div className="text-[9px] text-slate-400 uppercase tracking-wider">Median</div>
                            <div className="text-[11px] font-mono font-medium text-slate-600">{fmtBenchVal(b.median, b.format)}</div>
                          </div>
                          <div className="rounded-md bg-slate-50 py-1.5 px-1">
                            <div className="text-[9px] text-slate-400 uppercase tracking-wider">P75</div>
                            <div className="text-[11px] font-mono font-medium text-slate-600">{fmtBenchVal(b.p75, b.format)}</div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <p className="text-[10px] text-slate-400 italic flex items-center gap-1.5">
                  <Shield className="h-3 w-3" />
                  Percentile rankings within NACE {benchmark.nace_code}. P75 means outperforming 75% of peers. Overall score is the average percentile across all metrics.
                </p>
              </div>
            );
          })()}

        </TabsContent>

        {/* ===== Similar Companies tab ===== */}
        <TabsContent value="similar" className="mt-3">
          {similarCompanies === null ? (
            <div className="py-6 text-center">
              <Loader2 className="w-5 h-5 animate-spin text-indigo-400 mx-auto mb-1" />
              <p className="text-xs text-slate-400">Loading similar companies...</p>
            </div>
          ) : similarCompanies.length > 0 ? (() => {
            const maxRevenue = Math.max(...similarCompanies.slice(0, 10).map((sc) => sc.revenue ?? 0), 1);
            const thisRevenue = financials?.summary?.length
              ? [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year)[0]?.revenue ?? 0
              : 0;
            const barMax = Math.max(maxRevenue, thisRevenue, 1);
            return (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2">Similar Companies</h3>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-[11px] text-indigo-600 border-indigo-200 hover:bg-indigo-50 px-3"
                  onClick={() => {
                    const cbes = similarCompanies.slice(0, 10).map((sc) => sc.enterprise_number);
                    if (!cbes.includes(cbe)) cbes.unshift(cbe);
                    sessionStorage.setItem("compare_companies", JSON.stringify(cbes));
                    router.push("/compare");
                  }}
                >
                  <Scale className="w-3 h-3 mr-1" />
                  Compare all
                </Button>
              </div>
              <div className="rounded-xl border border-slate-200 overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-slate-50/80">
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 py-2">Company</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 py-2">City</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 py-2 min-w-[180px]">Revenue</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 py-2 text-right">EBITDA</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 py-2 text-right">FTE</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {similarCompanies.slice(0, 10).map((sc) => {
                      const revPct = sc.revenue != null ? Math.max(0, (sc.revenue / barMax) * 100) : 0;
                      return (
                      <TableRow key={sc.enterprise_number} className="hover:bg-slate-50/50">
                        <TableCell className="py-2">
                          <Link href={`/company/${sc.enterprise_number}`} className="text-xs font-medium text-indigo-600 hover:text-indigo-800 hover:underline">
                            {sc.name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-xs text-slate-500 py-2">{sc.city || "\u2014"}</TableCell>
                        <TableCell className="py-2">
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-4 bg-slate-50 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-indigo-100 rounded-full transition-all duration-500"
                                style={{ width: `${revPct}%` }}
                              />
                            </div>
                            <span className="text-xs text-slate-700 font-mono shrink-0 min-w-[60px] text-right">
                              {sc.revenue != null ? fmtEur(sc.revenue) : "\u2014"}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{sc.ebitda != null ? fmtEur(sc.ebitda) : "\u2014"}</TableCell>
                        <TableCell className="text-xs text-slate-700 font-mono text-right py-2">{sc.fte_total != null ? fmtNumber(sc.fte_total) : "\u2014"}</TableCell>
                      </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </div>
            );
          })() : (
            <div className="py-12 text-center">
              <Users className="w-8 h-8 text-slate-300 mx-auto mb-2" />
              <p className="text-sm font-medium text-slate-400">No similar companies found in this sector</p>
              <p className="text-xs text-slate-300 mt-1">This company may have a unique NACE code or no peers with comparable revenue</p>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
