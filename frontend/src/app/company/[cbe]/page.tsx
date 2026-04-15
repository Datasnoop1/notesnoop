"use client";

import React, { useState, useEffect, useCallback, useMemo, use } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
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
  generateAiInsights,
  submitInsightsFeedback,
} from "@/lib/api";
import type { SectorBenchmark, SimilarCompany, AiInsights } from "@/lib/api";
import { fmtCbe } from "@/lib/format";
import { useRouter } from "next/navigation";
import {
  Star,
  ArrowLeft,
  ChevronDown,
  Users,
  FileText,
  FileDown,
  FileSpreadsheet,
  Loader2,
  CheckCircle2,
  XCircle,
  Scale,
  Sparkles,
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

import type { CompanyDetail, FinancialsData, StructureData } from "./types";

/* ---------- Tab components ---------- */

import { SummaryTab } from "./_tabs/summary-tab";
import { PnlTab } from "./_tabs/pnl-tab";
import { CashFlowTab } from "./_tabs/cash-flow-tab";
import { BalanceSheetTab } from "./_tabs/balance-sheet-tab";
import { CreditTab } from "./_tabs/credit-tab";
import { AdministratorsTab } from "./_tabs/administrators-tab";
import { StructureTab } from "./_tabs/structure-tab";
import { PublicationsTab } from "./_tabs/publications-tab";
import { BenchmarkTab } from "./_tabs/benchmark-tab";
import { SimilarTab } from "./_tabs/similar-tab";
import { InsightsOverlay } from "./_tabs/insights-overlay";

const NetworkGraph = dynamic(() => import("@/components/network-graph"), {
  ssr: false,
  loading: () => <div className="py-8 text-center text-sm text-slate-400">Loading graph...</div>,
});

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

/* ---------- main component ---------- */

export default function CompanyDetailPage(props: {
  params: Promise<{ cbe: string }>;
}) {
  const { cbe } = use(props.params);

  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [financials, setFinancials] = useState<FinancialsData | null>(null);
  const [structure, setStructure] = useState<StructureData | null>(null);
  const [benchmark, setBenchmark] = useState<SectorBenchmark | null>(null);
  const [similarCompanies, setSimilarCompanies] = useState<SimilarCompany[] | null>(null);
  const [similarSort, setSimilarSort] = useState<{ key: "name" | "revenue" | "ebitda" | "fte_total" | "ebit" | "net_profit" | "equity" | "total_assets" | "personnel_costs" | "ebitda_margin" | "equity_ratio"; direction: "asc" | "desc" }>({ key: "revenue", direction: "desc" });
  const [loading, setLoading] = useState(true);
  const [isFavourite, setIsFavourite] = useState(false);
  const [activeTab, setActiveTab] = useState("summary");
  const [nbbLoading, setNbbLoading] = useState(false);
  const [nbbResult, setNbbResult] = useState<"success" | "error" | "no-data" | null>(null);
  const nbbAutoTriggered = React.useRef(false);
  const router = useRouter();

  /* -- Auto-load overlay state -- */
  type LoadStage = { label: string; status: "pending" | "active" | "done" | "error" };
  const [loadOverlay, setLoadOverlay] = useState(false);
  const [loadStages, setLoadStages] = useState<LoadStage[]>([]);
  const [loadStartTime, setLoadStartTime] = useState<number | null>(null);
  const [loadElapsed, setLoadElapsed] = useState(0);

  /* -- AI Enrichment state -- */
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [personEnrichments, setPersonEnrichments] = useState<Record<string, { summary: string; loading: boolean }>>({});

  /* -- Website & LinkedIn AI Insights state -- */
  const [websiteScrape, setWebsiteScrape] = useState<{ summary: string; products: string; employees: string; key_people: string; website_url: string } | null>(null);
  const [websiteScrapeLoading, setWebsiteScrapeLoading] = useState(false);
  const [websiteError, setWebsiteError] = useState<string | null>(null);
  const [linkedinScrape, setLinkedinScrape] = useState<{ summary: string; employee_count: string; industry: string; specialties: string; linkedin_url: string } | null>(null);
  const [linkedinScrapeLoading, setLinkedinScrapeLoading] = useState(false);
  const [linkedinError, setLinkedinError] = useState<string | null>(null);

  /* -- AI Insights overlay state -- */
  const [aiInsights, setAiInsights] = useState<AiInsights | null>(null);
  const [aiInsightsLoading, setAiInsightsLoading] = useState(false);
  const [showInsightsOverlay, setShowInsightsOverlay] = useState(false);

  /* -- Collapsible section state -- */
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const toggleSection = (key: string) =>
    setCollapsedSections((prev) => ({ ...prev, [key]: !prev[key] }));

  /* Elapsed timer for load overlay */
  useEffect(() => {
    if (!loadStartTime) return;
    const interval = setInterval(() => setLoadElapsed(Math.floor((Date.now() - loadStartTime) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [loadStartTime]);

  /* -- Check for existing AI enrichment on load -- */
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
            // website_summary wasn't valid JSON -- skip
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
            // linkedin_summary wasn't valid JSON -- skip
          }
        }
        // Restore existing AI insights
        if (data && data.ai_insights) {
          try {
            const parsed = typeof data.ai_insights === "string"
              ? JSON.parse(data.ai_insights)
              : data.ai_insights;
            if (parsed && typeof parsed === "object") {
              setAiInsights(parsed as AiInsights);
            }
          } catch {
            // ai_insights wasn't valid JSON -- skip
          }
        }
      })
      .catch(() => {});
  }, [cbe]);

  /* -- Load company detail, financials, structure -- */
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

  /* -- Callbacks -- */

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
      // Requires login -- silently fail
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

  /* -- AI enrichment callbacks (passed to tabs) -- */

  const handleEnrichCompany = useCallback(async () => {
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
  }, [cbe]);

  const handleScrapeWebsite = useCallback(async () => {
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
  }, [cbe]);

  const handleScrapeLinkedIn = useCallback(async () => {
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
  }, [cbe]);

  const handleGenerateInsights = useCallback(async () => {
    setAiInsightsLoading(true);
    setShowInsightsOverlay(true);
    try {
      const result = await generateAiInsights(cbe);
      setAiInsights(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      console.error("AI insights generation failed:", msg);
    } finally {
      setAiInsightsLoading(false);
    }
  }, [cbe]);

  const handleRegenerateInsights = useCallback(async () => {
    setAiInsights(null);
    setAiInsightsLoading(true);
    try {
      const result = await generateAiInsights(cbe);
      setAiInsights(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      console.error("AI insights regeneration failed:", msg);
    } finally {
      setAiInsightsLoading(false);
    }
  }, [cbe]);

  const handleInsightsFeedback = useCallback(async (feedback: { overall: "up" | "down"; websiteCorrect?: boolean; linkedinCorrect?: boolean; insightCorrect?: boolean; comment?: string }) => {
    try {
      await submitInsightsFeedback(cbe, feedback);
    } catch (err: unknown) {
      console.error("Failed to submit insights feedback:", err instanceof Error ? err.message : err);
    }
  }, [cbe]);

  const handleEnrichPerson = useCallback(async (name: string) => {
    if (personEnrichments[name]?.summary || personEnrichments[name]?.loading) return;
    setPersonEnrichments((prev) => ({
      ...prev,
      [name]: { summary: "", loading: true },
    }));
    try {
      // Check for existing enrichment first
      const existing = await getPersonEnrichment(name);
      if (existing?.summary) {
        setPersonEnrichments((prev) => ({
          ...prev,
          [name]: { summary: existing.summary, loading: false },
        }));
        return;
      }
      const result = await enrichPerson(name);
      setPersonEnrichments((prev) => ({
        ...prev,
        [name]: { summary: result?.summary || "", loading: false },
      }));
    } catch {
      setPersonEnrichments((prev) => ({
        ...prev,
        [name]: { summary: "", loading: false },
      }));
    }
  }, [personEnrichments]);

  const handleAddPeopleFavourite = useCallback(async (name: string) => {
    try {
      await addPeopleFavourite(name);
    } catch {
      // silently fail
    }
  }, []);

  /* -- Full profile export handlers -- */
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

  /* Sorted similar companies -- must be before early returns (rules of hooks) */
  const sortedSimilar = useMemo(() => {
    if (!similarCompanies) return null;
    const list = similarCompanies.slice(0, 100);
    const computeValue = (row: SimilarCompany, key: string): number | null => {
      if (key === "ebitda_margin") {
        return row.ebitda != null && row.revenue ? (row.ebitda / row.revenue) * 100 : null;
      }
      if (key === "equity_ratio") {
        return row.equity != null && row.total_assets ? (row.equity / row.total_assets) * 100 : null;
      }
      return (row as unknown as Record<string, number | null>)[key] ?? null;
    };
    return [...list].sort((a, b) => {
      const { key, direction } = similarSort;
      const dir = direction === "asc" ? 1 : -1;
      if (key === "name") {
        return dir * (a.name ?? "").localeCompare(b.name ?? "");
      }
      const aVal = computeValue(a, key) ?? -Infinity;
      const bVal = computeValue(b, key) ?? -Infinity;
      return dir * (aVal - bVal);
    });
  }, [similarCompanies, similarSort]);

  /* -- Early returns -- */

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

  /* -- Derived data -- */

  const addressParts = [
    detail.street,
    detail.house_number,
    [detail.zipcode, detail.city].filter(Boolean).join(" "),
  ].filter(Boolean);
  const address = addressParts.length > 0 ? addressParts.join(", ") : null;

  const chartData = (financials?.summary ?? []).map((r) => ({
    fy: String(r.fiscal_year),
    Revenue: r.revenue,
    EBITDA: r.ebitda,
  }));

  /* -- Render -- */

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-4">
      {/* Back link */}
      <Link
        href="/company"
        className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-600"
      >
        <ArrowLeft className="h-3 w-3" /> Back to search
      </Link>

      {/* Company Header */}
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
                      NACE {detail.nace_code}{detail.nace_label && detail.nace_label !== detail.nace_code ? ` \u2014 ${detail.nace_label}` : ""}
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
              onClick={() => aiInsights ? setShowInsightsOverlay(true) : handleGenerateInsights()}
              title="AI Insights"
              className={`h-9 md:h-7 text-[11px] px-2.5 md:px-2 border-indigo-300 text-indigo-600 hover:bg-indigo-50 hover:border-indigo-400 ${aiInsights ? "bg-indigo-50 border-indigo-400" : ""}`}
            >
              {aiInsightsLoading ? (
                <Loader2 className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1 animate-spin" />
              ) : (
                <Sparkles className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1" />
              )}
              <span className="hidden sm:inline">AI Insights</span>
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

      {/* AI Insights overlay */}
      <InsightsOverlay
        open={showInsightsOverlay}
        onClose={() => setShowInsightsOverlay(false)}
        insights={aiInsights}
        loading={aiInsightsLoading}
        companyName={detail.name || fmtCbe(cbe)}
        onGenerate={handleGenerateInsights}
        onRegenerate={handleRegenerateInsights}
        onFeedback={handleInsightsFeedback}
      />

      {/* Auto-load overlay (centered) */}
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
                      : "This may take 30\u201360 seconds."}
                  </p>
                </div>
                <button onClick={() => setLoadOverlay(false)} className="ml-auto text-slate-400 hover:text-slate-600 text-lg leading-none">&times;</button>
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

        {/* ===== Summary ===== */}
        <TabsContent value="summary" className="mt-6">
          <SummaryTab
            detail={detail}
            financials={financials}
            structure={structure}
            cbe={cbe}
            activeTab={activeTab}
            aiSummary={aiSummary}
            aiLoading={aiLoading}
            aiError={aiError}
            onEnrichCompany={handleEnrichCompany}
            websiteScrape={websiteScrape}
            websiteScrapeLoading={websiteScrapeLoading}
            websiteError={websiteError}
            onScrapeWebsite={handleScrapeWebsite}
            linkedinScrape={linkedinScrape}
            linkedinScrapeLoading={linkedinScrapeLoading}
            linkedinError={linkedinError}
            onScrapeLinkedIn={handleScrapeLinkedIn}
            collapsedSections={collapsedSections}
            toggleSection={toggleSection}
            setActiveTab={setActiveTab}
          />
        </TabsContent>

        {/* ===== P&L ===== */}
        <TabsContent value="pnl" className="mt-3">
          <PnlTab
            financials={financials}
            nbbLoading={nbbLoading}
            nbbResult={nbbResult}
            setNbbLoading={setNbbLoading}
            setNbbResult={setNbbResult}
            setFinancials={setFinancials as (v: FinancialsData) => void}
            cbe={cbe}
            companyName={detail.name}
            collapsedSections={collapsedSections}
            toggleSection={toggleSection}
            chartData={chartData}
          />
        </TabsContent>

        {/* ===== Cash Flow ===== */}
        <TabsContent value="cashflow" className="mt-3">
          <CashFlowTab
            financials={financials}
            cbe={cbe}
            companyName={detail.name}
            collapsedSections={collapsedSections}
            toggleSection={toggleSection}
          />
        </TabsContent>

        {/* ===== Balance Sheet ===== */}
        <TabsContent value="balancesheet" className="mt-3">
          <BalanceSheetTab
            financials={financials}
            cbe={cbe}
            companyName={detail.name}
            collapsedSections={collapsedSections}
            toggleSection={toggleSection}
          />
        </TabsContent>

        {/* ===== Credit ===== */}
        <TabsContent value="credit" className="mt-3">
          <CreditTab
            financials={financials}
            detail={detail}
            cbe={cbe}
          />
        </TabsContent>

        {/* ===== Administrators ===== */}
        <TabsContent value="administrators" className="mt-3">
          <AdministratorsTab
            detail={detail}
            structure={structure}
            cbe={cbe}
            personEnrichments={personEnrichments}
            onEnrichPerson={handleEnrichPerson}
            onAddPeopleFavourite={handleAddPeopleFavourite}
          />
        </TabsContent>

        {/* ===== Structure ===== */}
        <TabsContent value="structure" className="mt-3">
          <StructureTab
            detail={detail}
            structure={structure}
            cbe={cbe}
            collapsedSections={collapsedSections}
            toggleSection={toggleSection}
          />
        </TabsContent>

        {/* ===== Network ===== */}
        <TabsContent value="network" className="mt-3">
          <NetworkGraph cbe={cbe} companyName={detail?.name || cbe} />
        </TabsContent>

        {/* ===== Publications ===== */}
        <TabsContent value="publications" className="mt-3">
          <PublicationsTab
            structure={structure}
            cbe={cbe}
            detail={detail}
            nbbLoading={nbbLoading}
            setNbbLoading={setNbbLoading}
            nbbResult={nbbResult}
            setNbbResult={setNbbResult}
            setStructure={setStructure as (s: StructureData) => void}
          />
        </TabsContent>

        {/* ===== Benchmark ===== */}
        <TabsContent value="benchmark" className="mt-3">
          <BenchmarkTab
            benchmark={benchmark}
            detail={detail}
          />
        </TabsContent>

        {/* ===== Similar ===== */}
        <TabsContent value="similar" className="mt-3">
          <SimilarTab
            sortedSimilar={sortedSimilar}
            similarSort={similarSort}
            setSimilarSort={setSimilarSort}
            cbe={cbe}
            financials={financials}
            similarCompanies={similarCompanies}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
