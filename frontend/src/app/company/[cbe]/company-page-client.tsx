"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
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
  extractAdminsFromStaatsblad,
  getSectorBenchmark,
  addPeopleFavourite,
  enrichCompany,
  getEnrichment,
  enrichPerson,
  getPersonEnrichment,
  scrapeCompanyWebsite,
  scrapeCompanyLinkedIn,
  generateAiInsights,
  submitInsightsFeedback,
  apiFetch,
} from "@/lib/api";
import type { SectorBenchmark, AiInsights } from "@/lib/api";
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
  Sparkles,
  BarChart3,
  Copy,
  Check,
  Share2,
} from "lucide-react";
import { useTranslation } from "@/components/language-provider";
import { SearchableText, GoogleSearchLink } from "@/components/google-search-link";
import PrintLogo from "@/components/print-logo";
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
import { FinancialsSection } from "./financials-section";

/* ---------- Tab components ---------- */

import { SummaryTab } from "./_tabs/summary-tab";
import { PnlTab } from "./_tabs/pnl-tab";
import { CashFlowTab } from "./_tabs/cash-flow-tab";
import { BalanceSheetTab } from "./_tabs/balance-sheet-tab";
import { CreditTab } from "./_tabs/credit-tab";
import { ValuationTab } from "./_tabs/valuation-tab";
import { AdministratorsTab } from "./_tabs/administrators-tab";
import { StructureTab } from "./_tabs/structure-tab";
import { PublicationsTab } from "./_tabs/publications-tab";
import { BenchmarkTab } from "./_tabs/benchmark-tab";
import { SimilarTab } from "./_tabs/similar-tab";
import { InsightsOverlay } from "./_tabs/insights-overlay";

const NetworkSunburst = dynamic(() => import("@/components/network-sunburst"), {
  ssr: false,
  loading: () => (
    <div className="py-8 text-center text-sm text-slate-400">Loading sunburst…</div>
  ),
});

const NetworkPyramid = dynamic(() => import("@/components/network-pyramid"), {
  ssr: false,
  loading: () => (
    <div className="py-8 text-center text-sm text-slate-400">Loading pyramid…</div>
  ),
});

const NetworkGraph = dynamic(() => import("@/components/network-graph"), {
  ssr: false,
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

interface CompanyPageClientProps {
  cbe: string;
  initialDetail: CompanyDetail | null;
  initialFinancials: FinancialsData | null;
  initialStructure: StructureData | null;
}

export function CompanyPageClient({
  cbe,
  initialDetail,
  initialFinancials,
  initialStructure,
}: CompanyPageClientProps) {
  const { t, locale } = useTranslation();

  const [detail, setDetail] = useState<CompanyDetail | null>(initialDetail);
  const [financials, setFinancials] = useState<FinancialsData | null>(initialFinancials);
  const [structure, setStructure] = useState<StructureData | null>(initialStructure);
  const [benchmark, setBenchmark] = useState<SectorBenchmark | null>(null);
  const [loading, setLoading] = useState(!initialDetail);
  const [isFavourite, setIsFavourite] = useState(false);
  const [activeTab, setActiveTab] = useState("summary");
  const [nbbLoading, setNbbLoading] = useState(false);
  const [nbbResult, setNbbResult] = useState<"success" | "error" | "no-data" | "pdf-only" | null>(null);
  const nbbAutoTriggered = React.useRef(false);
  const nbbAutoInFlight = React.useRef(false);
  const adminExtractTriggered = React.useRef(false);
  const aiPreloadTriggered = React.useRef(false);
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
  const [aiInsightsError, setAiInsightsError] = useState<string | null>(null);
  const [showInsightsOverlay, setShowInsightsOverlay] = useState(false);
  // "cached" means we timed out but have a cached version to show
  const [aiInsightsCachedFallback, setAiInsightsCachedFallback] = useState(false);
  // "timedOutNoCache" means the 15 s deadline fired with NO cached data available
  const [aiInsightsTimedOutNoCache, setAiInsightsTimedOutNoCache] = useState(false);
  // Ref so the AI enrichment useEffect can read the latest cached insights
  // without a stale-closure problem
  const aiInsightsRef = React.useRef<AiInsights | null>(null);
  // AbortController for the in-flight AI insights fetch — cleaned up on
  // unmount / locale change / CBE change so rapid navigation doesn't
  // leak slow OpenRouter calls (security review MEDIUM finding).
  const aiAbortRef = React.useRef<AbortController | null>(null);

  /* -- Copy-CBE / BTW feedback -- */
  const [copiedCbe, setCopiedCbe] = useState(false);
  const [copiedBtw, setCopiedBtw] = useState(false);

  /* -- Collapsible section state -- */
  // Groups default-collapsed on load so the tabs feel lighter. User can
  // expand any group via its chip. P&L op-cost breakdown in particular
  // lives under the waterfall above it, so the table doesn't need to
  // repeat it by default.
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({
    pnl_opex: true,
  });
  const toggleSection = (key: string) =>
    setCollapsedSections((prev) => ({ ...prev, [key]: !prev[key] }));

  /* Elapsed timer for load overlay */
  useEffect(() => {
    if (!loadStartTime) return;
    const interval = setInterval(() => setLoadElapsed(Math.floor((Date.now() - loadStartTime) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [loadStartTime]);

  useEffect(() => {
    nbbAutoTriggered.current = false;
    nbbAutoInFlight.current = false;
    adminExtractTriggered.current = false;
    aiPreloadTriggered.current = false;
    aiInsightsRef.current = null;
    if (aiAbortRef.current) {
      aiAbortRef.current.abort();
      aiAbortRef.current = null;
    }
    setNbbLoading(false);
    setNbbResult(null);
    setLoadOverlay(false);
    setLoadStages([]);
    setLoadStartTime(null);
    setAiInsightsCachedFallback(false);
    setAiInsightsTimedOutNoCache(false);
    setAiInsightsLoading(false);
    setAiInsights(null);
  }, [cbe]);

  /* Track this profile in localStorage so the screener / dashboard can
     surface a "Recently viewed" panel. Only fires after we've resolved
     a real company name (skip 404s and the initial null state). */
  useEffect(() => {
    if (!detail || !detail.name) return;
    const name = detail.name;
    import("@/lib/recently-viewed").then((mod) => {
      mod.recordCompanyView({ cbe, name, city: detail.city ?? null });
    });
  }, [cbe, detail?.name, detail?.city]);

  /* "What changed since last visit" — fetch server-side history BEFORE
     recording this visit so the /since call compares to the PREVIOUS view.
     Then record the current view to shift prev → last. Fires only for
     authenticated users (backend silently no-ops for anonymous).
     Depends only on `cbe` so it fires exactly once per company, not on
     every `detail` refetch (AI enrichment, locale change, etc.). */
  type ChangesSinceResponse = {
    since: string | null;
    changes: { type: string; at: string | null; label: string; meta?: Record<string, unknown> }[];
  } | null;
  const [sinceLastVisit, setSinceLastVisit] = useState<ChangesSinceResponse>(null);
  const [sinceBannerDismissed, setSinceBannerDismissed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch<ChangesSinceResponse>(`/api/changes/${cbe}/since`);
        if (!cancelled) setSinceLastVisit(r);
        // Record AFTER fetching so the next visit compares to THIS one.
        await apiFetch(`/api/changes/${cbe}/view`, { method: "POST" });
      } catch {
        // silent — anonymous users hit this path too
      }
    })();
    return () => { cancelled = true; };
  }, [cbe]);

  /* -- AI enrichment load. Runs in PARALLEL with the main profile
     fetches (detail / financials / structure) instead of waiting for
     first paint via requestIdleCallback — operator-requested (#12)
     so the insights panel populates while the profile's loading too.
     Re-runs when `locale` changes so cached AI gets re-fetched
     translated to the user's new site language.

     15-second hard cap:
     - If the generation call completes in time → show result normally.
     - If it times out AND we already have cached insights → show cached +
       "showing cached version" badge; swap to fresh when it arrives.
     - If it times out with NO cache → show a "still generating" placeholder
       with a manual Retry button (no timeout on retry). */
  useEffect(() => {
    let cancelled = false;

    // Kick off the cache fetch AND the generation request in parallel.
    // On cache hit we discard the generation result (generator backend
    // de-duplicates requests for the same CBE anyway). On cache miss
    // the generation result populates the panel without a second
    // round-trip.
    const enrichP = getEnrichment(cbe).catch(() => null);
    if (!aiPreloadTriggered.current) {
      aiPreloadTriggered.current = true;
      setAiInsightsLoading(true);
      setAiInsightsCachedFallback(false);

      // Keep a reference to the in-flight generation promise so we can
      // attach a second .then() in the timeout branch without re-starting
      // the request (the backend deduplicates, but avoiding the extra fetch
      // is cheaper).
      // AbortController is wired so component unmount / locale-change /
      // CBE-change cancels the request — prevents accumulating long
      // OpenRouter calls when users navigate rapidly between profiles
      // (security review MEDIUM finding).
      const aiAbort = aiAbortRef.current;
      if (aiAbort) aiAbort.abort();
      const newAbort = new AbortController();
      aiAbortRef.current = newAbort;
      const generationP = generateAiInsights(cbe, newAbort.signal);

      // Race generation against a 15 s deadline
      const timeoutHandle: { id: ReturnType<typeof setTimeout> | null } = { id: null };
      const timeoutPromise = new Promise<"timeout">((resolve) => {
        timeoutHandle.id = setTimeout(() => resolve("timeout"), 15_000);
      });

      Promise.race([
        generationP.then((r) => ({ result: r })),
        timeoutPromise,
      ])
        .then((outcome) => {
          if (cancelled) return;
          if (outcome === "timeout") {
            // Check if we already have cached data from the enrichP race
            const cached = aiInsightsRef.current;
            if (cached) {
              // Show cached + badge; clear the "no-cache timeout" flag
              setAiInsightsCachedFallback(true);
              setAiInsightsTimedOutNoCache(false);
              setAiInsightsLoading(false);
            } else {
              // No cache yet — show "still generating" placeholder
              setAiInsightsCachedFallback(false);
              setAiInsightsTimedOutNoCache(true);
              setAiInsightsLoading(false);
            }
            // The original generationP is still in flight — attach to it
            // so when it resolves the UI swaps silently to fresh content.
            generationP
              .then((freshResult) => {
                if (!cancelled) {
                  setAiInsights(freshResult);
                  aiInsightsRef.current = freshResult;
                  setAiInsightsCachedFallback(false);
                  setAiInsightsTimedOutNoCache(false);
                }
              })
              .catch(() => {}); // silent — user can retry manually
          } else {
            setAiInsights(outcome.result);
            aiInsightsRef.current = outcome.result;
            setAiInsightsCachedFallback(false);
            setAiInsightsTimedOutNoCache(false);
            setAiInsightsLoading(false);
          }
        })
        .catch(() => {
          // fails silently for unauthenticated users + aborted fetches
          if (!cancelled) setAiInsightsLoading(false);
        })
        .finally(() => {
          if (timeoutHandle.id) clearTimeout(timeoutHandle.id);
        });
    }

    enrichP.then((data) => {
      if (cancelled || !data) return;
      if (data.summary) setAiSummary(data.summary);
      if (data.website_summary) {
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
        } catch {}
      }
      if (data.linkedin_summary) {
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
        } catch {}
      }
      // Cached insights: apply immediately — the parallel generation
      // will finish later and overwrite with the freshest version.
      // Also update the ref so the timeout branch can read it.
      if (data.ai_insights) {
        try {
          const parsed = typeof data.ai_insights === "string"
            ? JSON.parse(data.ai_insights)
            : data.ai_insights;
          if (parsed && typeof parsed === "object") {
            setAiInsights(parsed as AiInsights);
            aiInsightsRef.current = parsed as AiInsights;
          }
        } catch {}
      }
    });

    return () => {
      cancelled = true;
      // Abort the in-flight AI insights fetch so unmount / locale-change /
      // CBE-change doesn't leak a long-running OpenRouter call.
      if (aiAbortRef.current) {
        aiAbortRef.current.abort();
        aiAbortRef.current = null;
      }
    };
  }, [cbe, locale]);

  /* Phase 5 background-upgrade poll.
     ─────────────────────────────────
     When the initial fetch returns the bulk_summary or KBO skeleton, the
     server sets `upgrade_in_progress: true` and runs the qwen+kimi
     elaboration in the background. Re-fetch every 30 s (cap at 3 polls
     = 90 s total) until the response no longer says `upgrade_in_progress`,
     then silently swap in the upgraded narrative. This is the UX glue
     that makes "render fast, upgrade silently" feel seamless. */
  useEffect(() => {
    if (!aiInsights?.upgrade_in_progress) return;
    let cancelled = false;
    let attempt = 0;
    const maxAttempts = 3;
    const intervalMs = 30_000;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (cancelled) return;
      attempt += 1;
      try {
        const fresh = await generateAiInsights(cbe);
        if (cancelled) return;
        if (fresh && !fresh.upgrade_in_progress) {
          setAiInsights(fresh);
          aiInsightsRef.current = fresh;
          return; // upgrade landed — stop polling
        }
        if (attempt < maxAttempts) {
          timer = setTimeout(tick, intervalMs);
        }
      } catch {
        // Transient — retry on next tick if budget remains
        if (!cancelled && attempt < maxAttempts) {
          timer = setTimeout(tick, intervalMs);
        }
      }
    };

    timer = setTimeout(tick, intervalMs);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [cbe, aiInsights?.upgrade_in_progress]);

  /* -- Auto-load missing NBB data / publications -- */
  const runAutoLoad = useCallback(async (fin: FinancialsData | null, str: StructureData | null) => {
    const needsFinancials = !!(fin?.summary && fin.summary.length === 0);
    const hasNbbBackedAdmins = !!str?.administrators?.some(
      (admin) => admin.source === "nbb" || admin.source === "merged"
    );
    const needsNbbAdmins = !!str && !hasNbbBackedAdmins;
    const needsPublications = !!str && !str.staatsblad_publications?.length;

    if (nbbAutoTriggered.current) return;
    nbbAutoTriggered.current = true;
    nbbAutoInFlight.current = true;

    const shouldShowOverlay = needsFinancials || needsNbbAdmins || needsPublications;
    const stages: LoadStage[] = [];
    if (shouldShowOverlay) {
      stages.push({
        label: needsFinancials
          ? "Checking latest financials and NBB board data"
          : needsNbbAdmins
            ? "Checking NBB board data"
            : "Checking NBB for updates",
        status: "pending",
      });
      if (needsPublications) {
        stages.push({ label: "Loading publications", status: "pending" });
      }
      stages.push({ label: "Done", status: "pending" });
      setLoadStages(stages);
      setLoadOverlay(true);
      setLoadStartTime(Date.now());
    }
    setNbbLoading(true);

    let stageIdx = 0;
    const advance = (status: "done" | "error" = "done") => {
      if (!shouldShowOverlay) return;
      setLoadStages((prev) => {
        const next = [...prev];
        next[stageIdx] = { ...next[stageIdx], status };
        if (stageIdx + 1 < next.length) next[stageIdx + 1] = { ...next[stageIdx + 1], status: "active" };
        return next;
      });
      stageIdx++;
    };

    if (shouldShowOverlay) {
      setLoadStages((prev) => {
        const next = [...prev];
        next[0] = { ...next[0], status: "active" };
        return next;
      });
    }

    try {
      const data = await loadCompanyNBB(cbe);
      const governanceLoaded = (data.governance_loaded?.administrators ?? 0)
        + (data.governance_loaded?.shareholders ?? 0)
        + (data.governance_loaded?.participating_interests ?? 0)
        + (data.governance_loaded?.affiliations ?? 0);
      const loadedSomething = data.rubrics_loaded > 0
        || data.filings_loaded > 0
        || governanceLoaded > 0
        || data.status === "governance_backfilled";

      // Always refetch /financials and /structure after /load returns.
      // Two reasons:
      //   1. Promise.allSettled — if /structure 429s (rate-limited under
      //      burst), the /financials result must still apply. The previous
      //      Promise.all dropped the financials too, so the post-/load UI
      //      kept showing the empty state from the initial fetch.
      //   2. /load's heuristic (rubrics_loaded > 0 etc.) can lie when two
      //      effects fire /load in parallel — the second sees "already
      //      loaded" and reports no_new_data even though the DB now holds
      //      fresh rows. Trust the actual /financials state, not /load's
      //      after-the-fact summary. The endpoints are cheap (cached for
      //      5 min when populated) and idempotent.
      const [finResult, structResult] = await Promise.allSettled([
        getCompanyFinancials(cbe),
        getCompanyStructure(cbe),
      ]);
      if (finResult.status === "fulfilled") {
        setFinancials(finResult.value as unknown as FinancialsData);
      }
      if (structResult.status === "fulfilled") {
        setStructure(structResult.value as unknown as StructureData);
      }

      if (loadedSomething) {
        setNbbResult("success");
      } else if (data.pdf_only) {
        setNbbResult("pdf-only");
      } else {
        setNbbResult("no-data");
      }
      advance();
    } catch {
      advance("error");
      setNbbResult("error");
    }

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

    if (shouldShowOverlay) {
      setLoadStages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], status: "done" };
        return next;
      });
    }
    nbbAutoInFlight.current = false;
    setNbbLoading(false);
    setLoadStartTime(null);
    if (shouldShowOverlay) {
      setTimeout(() => setLoadOverlay(false), 3000);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cbe]);

  /* -- Load company detail, financials, structure --
     SSR now delivers detail + structure only (financials moved to
     FinancialsSection client component). We apply those directly and
     skip the historical client-side refetch. runAutoLoad is deferred
     until FinancialsSection calls onLoaded so it can inspect real data. */
  useEffect(() => {
    let cancelled = false;
    nbbAutoTriggered.current = false;
    if (initialDetail) {
      setDetail(initialDetail);
      // initialFinancials is always null (moved to client-side fetch)
      setFinancials(null);
      setStructure(initialStructure);
      setLoading(false);
      // runAutoLoad will be called from FinancialsSection.onLoaded once
      // financials arrive so it has real data to inspect.
      return () => { cancelled = true; };
    }

    setLoading(true);
    Promise.all([
      getCompanyDetail(cbe),
      getCompanyStructure(cbe),
    ])
      .then(async ([d, s]) => {
        if (cancelled) return;
        setDetail(d as unknown as CompanyDetail);
        setStructure(s as unknown as StructureData);
        setLoading(false);
        // runAutoLoad will be called from FinancialsSection.onLoaded
      })
      .catch((err) => {
        console.error("Failed to load company data:", err);
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cbe]);

  /* -- Auto-find admins on profile load when we have none. --
     Chain of cheap → expensive fallbacks:
       1) No Staatsblad pubs scraped yet?  Scrape first. Many companies
          have never been fetched, so this is what typically unblocks
          things (coverage today is ~2% of enterprises).
       2) Pubs exist and include an appointment/resignation notice?
          Run the LLM extractor.
     Both calls are fire-and-forget; each rate-limits itself server-side
     (the backend caches "recently tried empty" for 30 min, plus tier
     limits cap LLM-burning calls per day per IP). The Staatsblad scrape
     is essential profile data and runs for everyone; the extract-admins
     LLM step is tier-counted so anonymous abuse stays bounded. */
  useEffect(() => {
    if (!structure || adminExtractTriggered.current || nbbAutoInFlight.current) return;
    const hasAdmins = structure.administrators.length > 0;
    if (hasAdmins) return;

    const pubs = structure.staatsblad_publications ?? [];
    const hasAppointmentPubs = pubs.some((p) => p.pub_type === "ONTSLAGEN - BENOEMINGEN");

    adminExtractTriggered.current = true;

    const runExtract = () =>
      extractAdminsFromStaatsblad(cbe)
        .then((result) => {
          if (result.extracted > 0) {
            return getCompanyStructure(cbe).then((refreshed) =>
              setStructure(refreshed as unknown as StructureData)
            );
          }
        })
        .catch(() => {
          // Non-critical — silently ignore
        });

    if (hasAppointmentPubs) {
      runExtract();
    } else if (pubs.length === 0) {
      // No Staatsblad history loaded at all; scrape it then try extraction.
      loadPublications(cbe)
        .then(() => getCompanyStructure(cbe))
        .then((refreshed) => {
          setStructure(refreshed as unknown as StructureData);
          const newPubs = (refreshed as unknown as StructureData).staatsblad_publications ?? [];
          if (newPubs.some((p) => p.pub_type === "ONTSLAGEN - BENOEMINGEN")) {
            return runExtract();
          }
        })
        .catch(() => {
          // Non-critical — silently ignore
        });
    }
  }, [cbe, structure]);

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
      }
    },
    [cbe, benchmark]
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
      if (msg.includes("429")) {
        setAiError("You've hit the daily AI limit. Sign in for higher limits, or try again tomorrow.");
      } else if (msg.includes("503")) {
        setAiError("AI service unavailable. Please try again in a moment.");
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
      } else if (msg.includes("429")) {
        setWebsiteError("You've hit the daily AI limit. Sign in for higher limits, or try again tomorrow.");
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
      } else if (msg.includes("429")) {
        setLinkedinError("You've hit the daily AI limit. Sign in for higher limits, or try again tomorrow.");
      } else {
        setLinkedinError(`LinkedIn insights failed: ${msg}`);
      }
    } finally {
      setLinkedinScrapeLoading(false);
    }
  }, [cbe]);

  const handleGenerateInsights = useCallback(async () => {
    setAiInsightsError(null);
    setAiInsightsLoading(true);
    setShowInsightsOverlay(true);
    try {
      const result = await generateAiInsights(cbe);
      setAiInsights(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      console.error("AI insights generation failed:", msg);
      if (msg.includes("404")) {
        setAiInsightsError("AI insights are not available for this company yet. Please try again.");
      } else if (msg.includes("429")) {
        setAiInsightsError("You've hit the daily AI limit. Sign in for higher limits, or try again tomorrow.");
      } else if (msg.includes("503")) {
        setAiInsightsError("AI insights are temporarily unavailable. Please try again in a moment.");
      } else {
        setAiInsightsError(`AI insights failed: ${msg}`);
      }
    } finally {
      setAiInsightsLoading(false);
    }
  }, [cbe]);

  const handleRegenerateInsights = useCallback(async () => {
    setAiInsights(null);
    setAiInsightsError(null);
    setAiInsightsLoading(true);
    try {
      const result = await generateAiInsights(cbe);
      setAiInsights(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      console.error("AI insights regeneration failed:", msg);
      if (msg.includes("404")) {
        setAiInsightsError("AI insights are not available for this company yet. Please try again.");
      } else if (msg.includes("429")) {
        setAiInsightsError("You've hit the daily AI limit. Sign in for higher limits, or try again tomorrow.");
      } else if (msg.includes("503")) {
        setAiInsightsError("AI insights are temporarily unavailable. Please try again in a moment.");
      } else {
        setAiInsightsError(`AI insights failed: ${msg}`);
      }
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

  /* Auto re-fetch all already-loaded person summaries when the user
     switches site language. `getPersonEnrichment` threads ?lang= so
     the backend translates the cached entry. Untouched persons stay
     untouched (don't generate fresh enrichments out of nowhere). */
  useEffect(() => {
    const namesToRefresh = Object.entries(personEnrichments)
      .filter(([, v]) => v.summary && !v.loading)
      .map(([n]) => n);
    if (namesToRefresh.length === 0) return;
    let cancelled = false;
    namesToRefresh.forEach(async (name) => {
      try {
        const refreshed = await getPersonEnrichment(name);
        if (cancelled || !refreshed?.summary) return;
        setPersonEnrichments((prev) => ({
          ...prev,
          [name]: { summary: refreshed.summary, loading: false },
        }));
      } catch {
        // silently ignore — old text stays
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

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
        <p className="text-lg font-medium text-slate-700">{t("company.notFound")}</p>
        <p className="mt-1 text-sm text-slate-500">
          CBE {fmtCbe(cbe)} {t("company.couldNotLoad")}.
        </p>
        <Link
          href="/company"
          className="mt-4 inline-flex items-center gap-1 text-sm text-brand hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> {t("company.backToSearch")}
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

  // Belgian VAT numbers are the 10-digit CBE prefixed with "BE" — same digits,
  // different external system. Operators copy this when filing invoices /
  // looking up VAT in VIES, so it deserves its own copy affordance.
  // Display the dotted form for legibility; copy the raw `BE0123456789`
  // form so VIES / accounting tools accept the paste without manual cleanup.
  const btwDisplay = `BE ${fmtCbe(cbe)}`;
  const btwCopyValue = `BE${cbe.replace(/\D/g, "").padStart(10, "0")}`;

  const copyToClipboard = (value: string, onCopied: () => void) => {
    const fallback = () => {
      try {
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        onCopied();
      } catch {
        /* give up silently */
      }
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value).then(onCopied, fallback);
    } else {
      fallback();
    }
  };

  const chartData = (financials?.summary ?? []).map((r) => ({
    fy: String(r.fiscal_year),
    Revenue: r.revenue,
    EBITDA: r.ebitda,
  }));

  /* -- Render -- */

  return (
    <div className="mx-auto w-full max-w-[1200px] px-3 sm:px-4 py-3 sm:py-4">
      {/* Back link */}
      <Link
        href="/company"
        className="mb-3 sm:mb-4 inline-flex items-center gap-1.5 min-h-[36px] text-[12.5px] text-[#5F6B85] hover:text-[#1687E8] active:text-[#0A5BA0] transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> {t("company.backToSearch")}
      </Link>

      {/* Company Header */}
      <div className="mb-4 sm:mb-5 rounded-xl sm:rounded-2xl border border-[#E2E8F2] bg-white p-4 sm:p-6">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-3 sm:gap-4">
          {/* Left: name + CBE */}
          <div className="flex items-center gap-3 sm:gap-4 min-w-0 flex-1 w-full">
            {/* Initials badge — slightly smaller on mobile to save horizontal room. */}
            <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-xl sm:rounded-2xl bg-[#EAF5FF] flex items-center justify-center text-[#1687E8] font-bold text-base sm:text-lg shrink-0 select-none">
              {(detail.name || fmtCbe(cbe)).split(/\s+/).slice(0, 2).map((w: string) => w[0]?.toUpperCase() ?? "").join("")}
            </div>
            <div className="min-w-0 flex-1">
            <h1 className="text-[20px] sm:text-[26px] font-bold text-[#08132B] leading-tight break-words">
              <SearchableText text={detail.name || fmtCbe(cbe)} mapsQuery={address || undefined}>
                {detail.name || fmtCbe(cbe)}
              </SearchableText>
            </h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-[#5F6B85]">
              <span className="inline-flex items-center gap-1.5">
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${detail.status === "AC" ? "bg-emerald-500" : "bg-red-400"}`} />
                <span className="font-mono">CBE {fmtCbe(cbe)}</span>
                <button
                  type="button"
                  onClick={() => {
                    const value = fmtCbe(cbe);
                    const markCopied = () => {
                      setCopiedCbe(true);
                      window.setTimeout(() => setCopiedCbe(false), 1500);
                    };
                    const fallback = () => {
                      // HTTP staging + older browsers don't expose the async
                      // clipboard API; keep the button working via the old
                      // textarea + execCommand dance.
                      try {
                        const ta = document.createElement("textarea");
                        ta.value = value;
                        ta.setAttribute("readonly", "");
                        ta.style.position = "absolute";
                        ta.style.left = "-9999px";
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand("copy");
                        document.body.removeChild(ta);
                        markCopied();
                      } catch {
                        /* give up silently */
                      }
                    };
                    if (navigator.clipboard?.writeText) {
                      navigator.clipboard.writeText(value).then(markCopied, fallback);
                    } else {
                      fallback();
                    }
                  }}
                  aria-label={copiedCbe ? t("company.copied") : t("company.copyCbe")}
                  title={copiedCbe ? t("company.copied") : t("company.copyCbe")}
                  className="inline-flex h-5 w-5 items-center justify-center rounded hover:bg-[#EAF5FF] hover:text-[#1687E8] transition-colors"
                >
                  {copiedCbe ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                </button>
              </span>
              <span className="inline-flex items-center gap-1.5 before:content-['·'] before:text-slate-300 before:mr-1">
                <span className="font-mono">{btwDisplay}</span>
                <button
                  type="button"
                  onClick={() => {
                    copyToClipboard(btwCopyValue, () => {
                      setCopiedBtw(true);
                      window.setTimeout(() => setCopiedBtw(false), 1500);
                    });
                  }}
                  aria-label={copiedBtw ? t("company.copied") : t("company.copyBtw")}
                  title={copiedBtw ? t("company.copied") : t("company.copyBtw")}
                  className="inline-flex h-5 w-5 items-center justify-center rounded hover:bg-[#EAF5FF] hover:text-[#1687E8] transition-colors"
                >
                  {copiedBtw ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                </button>
              </span>
              {(detail.jf_short || detail.jf_label) && (
                <span className="inline-flex items-center gap-1 before:content-['\u00B7'] before:text-slate-300 before:mr-1">
                  <span
                    className="uppercase tracking-wide text-[10px] font-semibold text-slate-500"
                    title={detail.jf_label || detail.jf_code || undefined}
                  >
                    {detail.jf_short || detail.jf_label}
                  </span>
                </span>
              )}
            </div>
            </div>{/* closes min-w-0 flex-1 name wrapper */}
          </div>{/* closes flex items-center initials+name wrapper */}

          {/* Right: action buttons + website */}
          <div className="flex flex-col items-start md:items-end gap-2 shrink-0 w-full md:w-auto">
            {/* Print-only DataSnoop logo — uses current configured site logo */}
            <PrintLogo heightPx={28} />

            {/* Metadata: address + website + NACE stacked, right-aligned on desktop */}
            <div className="flex flex-col items-start md:items-end gap-0.5 text-[12px] text-[#5F6B85] max-w-full">
              {address && (
                <GoogleSearchLink query={address} type="maps">
                  <span className="truncate">{address}</span>
                </GoogleSearchLink>
              )}
              {detail.website && (
                <a
                  href={detail.website.startsWith("http") ? detail.website : `https://${detail.website}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-brand hover:text-[color:var(--brand-ink)] transition-colors truncate"
                >
                  {detail.website.replace(/^https?:\/\//, "")}
                </a>
              )}
              {detail.nace_code && (
                <span className="truncate">
                  NACE {detail.nace_code}{detail.nace_label && detail.nace_label !== detail.nace_code ? ` \u2014 ${detail.nace_label}` : ""}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* AI Insights overlay */}
      <InsightsOverlay
        open={showInsightsOverlay}
        onClose={() => setShowInsightsOverlay(false)}
        insights={aiInsights}
        loading={aiInsightsLoading}
        error={aiInsightsError}
        companyName={detail.name || fmtCbe(cbe)}
        onGenerate={handleGenerateInsights}
        onRegenerate={handleRegenerateInsights}
        onFeedback={handleInsightsFeedback}
        cachedFallback={aiInsightsCachedFallback}
        timedOutNoCache={aiInsightsTimedOutNoCache}
      />

      {/* Auto-load overlay (centered) */}
      {loadOverlay && (
        <>
          <div className="fixed inset-0 z-40 bg-black/10 backdrop-blur-[1px]" />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="w-full max-w-[380px] rounded-2xl border border-slate-200 bg-white shadow-2xl p-6">
              <div className="flex items-center gap-3 mb-4">
                {loadStages.some((s) => s.status === "active") ? (
                  <div className="h-10 w-10 rounded-full bg-brand-soft flex items-center justify-center">
                    <Loader2 className="h-5 w-5 animate-spin text-brand" />
                  </div>
                ) : (
                  <div className="h-10 w-10 rounded-full bg-emerald-50 flex items-center justify-center">
                    <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                  </div>
                )}
                <div>
                  <span className="text-sm font-semibold text-slate-800 block">
                    {loadStages.every((s) => s.status === "done") ? t("company.dataLoaded") : t("company.gatheringData")}
                  </span>
                  <p className="text-[11px] text-slate-400">
                    {loadStages.every((s) => s.status === "done")
                      ? t("company.allDataAvailable")
                      : t("company.mayTaketime")}
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
                      <Loader2 className="h-4 w-4 animate-spin text-brand shrink-0" />
                    ) : stage.status === "error" ? (
                      <XCircle className="h-4 w-4 text-rose-400 shrink-0" />
                    ) : (
                      <div className="h-4 w-4 rounded-full border-2 border-slate-200 shrink-0" />
                    )}
                    <span className={`text-sm ${stage.status === "active" ? "text-brand font-medium" : stage.status === "done" ? "text-slate-500" : stage.status === "error" ? "text-rose-400" : "text-slate-400"}`}>
                      {stage.label}
                    </span>
                  </div>
                ))}
              </div>
              {loadStartTime && (
                <div className="pt-3 border-t border-slate-100">
                  <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                    <div className="h-full bg-brand rounded-full animate-pulse" style={{ width: `${Math.min(95, loadElapsed * 1.5)}%`, transition: "width 1s ease" }} />
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-slate-400 mt-1.5">
                    <span>{loadElapsed}s elapsed</span>
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand/60 animate-pulse" />
                      Working...
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* "What changed since last visit" banner — only when the user
          has visited this company before AND there are new events. */}
      {!sinceBannerDismissed && sinceLastVisit && sinceLastVisit.since && sinceLastVisit.changes.length > 0 && (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 flex items-start gap-3">
          <div className="flex-1">
            <div className="font-semibold mb-1">
              {sinceLastVisit.changes.length} update{sinceLastVisit.changes.length === 1 ? "" : "s"} since your last visit ({new Date(sinceLastVisit.since).toLocaleDateString()})
            </div>
            <ul className="space-y-0.5">
              {sinceLastVisit.changes.slice(0, 5).map((c, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="inline-block w-16 text-[10px] uppercase tracking-wider text-amber-600 shrink-0 mt-0.5">
                    {c.type}
                  </span>
                  <span className="flex-1">{c.label}</span>
                  {c.at && (
                    <span className="text-[10px] text-amber-500 shrink-0">
                      {new Date(c.at).toLocaleDateString()}
                    </span>
                  )}
                </li>
              ))}
              {sinceLastVisit.changes.length > 5 && (
                <li className="text-[10px] text-amber-600">+{sinceLastVisit.changes.length - 5} more</li>
              )}
            </ul>
          </div>
          <button
            onClick={() => setSinceBannerDismissed(true)}
            className="text-amber-500 hover:text-amber-700 text-xs leading-none p-1"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {/* Financials loader — client-side, with 15 s deadline.
          Always fetches in the background so data is ready when the user
          navigates to any financial sub-tab. Only renders skeleton / error
          UI when the user is actually on a financial tab. */}
      {!financials && (
        <FinancialsSection
          cbe={cbe}
          onLoaded={(data) => {
            setFinancials(data);
            // Trigger the auto-load check now that we have financials
            if (!nbbAutoTriggered.current) {
              runAutoLoad(data, structure);
            }
          }}
          initialFinancials={initialFinancials}
          visible={["pnl", "cashflow", "balancesheet", "credit"].includes(activeTab)}
        />
      )}

      {/* Tabs — grouped primary + sub-nav pattern */}
      <Tabs value={activeTab} onValueChange={handleTabChange}>
        {(() => {
          const TAB_GROUPS: Array<{ id: string; label: string; subs: Array<{ value: string; label: string }> }> = [
            { id: "overview", label: t("company.tabs.summary") as string, subs: [{ value: "summary", label: "" }] },
            { id: "financials", label: "Financials", subs: [
              { value: "pnl", label: t("company.tabs.pnl") as string },
              { value: "cashflow", label: t("company.tabs.cashflow") as string },
              { value: "balancesheet", label: t("company.tabs.balanceSheet") as string },
              { value: "credit", label: t("company.tabs.credit") as string },
            ]},
            { id: "valuation", label: t("company.tabs.valuation") as string, subs: [{ value: "valuation", label: "" }] },
            { id: "network", label: t("company.tabs.network") as string, subs: [
              { value: "network", label: "Graph" },
              { value: "network-pyramid", label: "Pyramid" },
              { value: "network-sunburst", label: "Sunburst" },
            ]},
            { id: "people", label: "People & Ownership", subs: [
              { value: "administrators", label: t("company.tabs.administrators") as string },
              { value: "structure", label: t("company.tabs.structure") as string },
            ]},
            { id: "activity", label: t("company.tabs.publications") as string, subs: [{ value: "publications", label: "" }] },
          ];
          // When on benchmark/similar (action buttons), no primary group is active.
          const currentGroup = TAB_GROUPS.find((g) => g.subs.some((s) => s.value === activeTab)) ?? null;

          return (
            <>
              {/* Screen-reader-only flat tab list so base-ui keyboard/ARIA still works.
                  Visually hidden; the decorative buttons below drive interaction. */}
              <TabsList variant="line" className="sr-only">
                {TAB_GROUPS.flatMap((g) => g.subs).concat([
                  { value: "benchmark", label: "Benchmark" },
                  { value: "similar", label: "Similar" },
                ]).map((s) => (
                  <TabsTrigger key={s.value} value={s.value}>{s.label}</TabsTrigger>
                ))}
              </TabsList>

              <div className="border-b border-[#E2E8F2] flex flex-col md:flex-row md:items-end md:justify-between gap-2 md:gap-3 no-print">
                {/* Tabs — horizontal-scroll row on mobile so the 6
                    primary groups don't wrap. -mx-3 px-3 lets the row
                    extend edge-to-edge under the parent's padding while
                    keeping the first/last items visually inside. */}
                <div className="flex flex-nowrap overflow-x-auto md:flex-wrap md:overflow-visible -mx-3 px-3 md:mx-0 md:px-0 md:scrollbar-none">
                  {TAB_GROUPS.map((g) => {
                    const active = currentGroup?.id === g.id;
                    return (
                      <button
                        key={g.id}
                        type="button"
                        onClick={() => handleTabChange(g.subs[0].value)}
                        className={`text-[12px] md:text-[11px] uppercase tracking-wider font-medium px-3 py-2.5 md:py-2 whitespace-nowrap border-b-2 shrink-0 transition ${
                          active
                            ? "border-brand text-brand"
                            : "border-transparent text-[#5F6B85] hover:text-[#08132B] active:text-[#1687E8]"
                        }`}
                      >
                        {g.label}
                      </button>
                    );
                  })}
                </div>
                <div className="flex items-center gap-1.5 overflow-x-auto md:overflow-visible -mx-3 px-3 md:mx-0 md:px-0 pb-1.5 md:shrink-0 md:scrollbar-none">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={toggleFavourite}
                    title={isFavourite ? "Remove from favourites" : "Add to favourites"}
                    className="h-9 w-9 md:h-7 md:w-7 p-0 text-[#8791A6] hover:text-yellow-500 border-[#E2E8F2]"
                  >
                    <Star
                      className={`h-4 w-4 md:h-3.5 md:w-3.5 ${
                        isFavourite ? "fill-yellow-400 text-yellow-500" : ""
                      }`}
                    />
                  </Button>
                  {/* Primer PDF button removed — the existing Export PDF
                      covers this surface. Backend endpoint
                      /api/companies/{cbe}/primer.pdf still exists for any
                      script/automation that needs the programmatic form. */}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setShowInsightsOverlay(true);
                      if (!aiInsights && !aiInsightsLoading) handleGenerateInsights();
                    }}
                    title="AI Insights"
                    className={`h-9 md:h-7 text-[11px] px-2.5 md:px-2 border-brand/40 text-brand hover:bg-brand-soft/60 hover:border-brand/60 ${aiInsights ? "bg-brand-soft border-brand/60" : ""}`}
                  >
                    {aiInsightsLoading ? (
                      <Loader2 className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1 animate-spin" />
                    ) : (
                      <Sparkles className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1" />
                    )}
                    <span className="hidden sm:inline">{t("company.aiInsights")}</span>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleTabChange("benchmark")}
                    title="Benchmark"
                    className={`h-9 md:h-7 text-[11px] px-2.5 md:px-2 border-brand/40 text-brand hover:bg-brand-soft/60 hover:border-brand/60 ${activeTab === "benchmark" ? "bg-brand-soft border-brand/60" : ""}`}
                  >
                    <BarChart3 className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1" />
                    <span className="hidden sm:inline">{t("company.tabs.benchmark")}</span>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleTabChange("similar")}
                    title="Find similar"
                    className={`h-9 md:h-7 text-[11px] px-2.5 md:px-2 border-brand/40 text-brand hover:bg-brand-soft/60 hover:border-brand/60 ${activeTab === "similar" ? "bg-brand-soft border-brand/60" : ""}`}
                  >
                    <Sparkles className="w-3.5 h-3.5 md:w-3 md:h-3 mr-1" />
                    <span className="hidden sm:inline">{t("company.findSimilar")}</span>
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
                        {t("company.exportExcel")}
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={handleExportPdf} className="text-xs cursor-pointer">
                        <FileText className="w-4 h-4 mr-2 text-rose-500" />
                        {t("company.exportPdf")}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => {
                          // Navigate to the public no-auth share card. Users can
                          // then copy the URL (big Copy-link button on that page)
                          // or paste the page itself into email / Slack.
                          window.open(`/s/${cbe}`, "_blank", "noopener,noreferrer");
                        }}
                        className="text-xs cursor-pointer"
                      >
                        <Share2 className="w-4 h-4 mr-2 text-brand" />
                        Share card (public link)
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>

              {/* Sub-navigation — only when the current group has multiple
                  sections. The pill row scrolls horizontally on mobile so
                  the four financial sub-tabs don't wrap. */}
              {currentGroup && currentGroup.subs.length > 1 && (
                <div className="mt-3 -mx-3 px-3 md:mx-0 md:px-0 overflow-x-auto md:scrollbar-none no-print">
                  <div className="inline-flex rounded-lg bg-slate-100 p-1 max-w-full">
                    {currentGroup.subs.map((s) => {
                      const active = activeTab === s.value;
                      return (
                        <button
                          key={s.value}
                          type="button"
                          onClick={() => handleTabChange(s.value)}
                          className={`rounded-md px-3 py-2 md:py-1 text-[12px] md:text-[11px] font-medium whitespace-nowrap shrink-0 transition ${
                            active
                              ? "bg-white text-slate-800 shadow-sm"
                              : "text-slate-500 hover:text-slate-700 active:text-slate-900"
                          }`}
                        >
                          {s.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          );
        })()}

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

        {/* ===== Valuation ===== */}
        <TabsContent value="valuation" className="mt-3">
          <ValuationTab cbe={cbe} companyName={detail.name} />
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
          <React.Suspense fallback={<div className="py-8 text-center text-sm text-slate-400">{t("company.loadingGraph")}</div>}>
            <NetworkGraph cbe={cbe} companyName={detail?.name || cbe} />
          </React.Suspense>
        </TabsContent>

        {/* ===== Network · Sunburst ===== */}
        <TabsContent value="network-sunburst" className="mt-3">
          <React.Suspense fallback={<div className="py-8 text-center text-sm text-slate-400">Loading sunburst…</div>}>
            <NetworkSunburst
              cbe={cbe}
              companyName={detail?.name || cbe}
              vat={`BE ${cbe.replace(/^(\d)(\d{3})(\d{3})(\d{3})$/, "$1$2.$3.$4")}`}
            />
          </React.Suspense>
        </TabsContent>

        {/* ===== Network · Pyramid ===== */}
        <TabsContent value="network-pyramid" className="mt-3">
          <React.Suspense fallback={<div className="py-8 text-center text-sm text-slate-400">Loading pyramid…</div>}>
            <NetworkPyramid
              cbe={cbe}
              companyName={detail?.name || cbe}
              vat={`BE ${cbe.replace(/^(\d)(\d{3})(\d{3})(\d{3})$/, "$1$2.$3.$4")}`}
            />
          </React.Suspense>
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
          <SimilarTab cbe={cbe} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
