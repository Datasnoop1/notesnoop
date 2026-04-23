"use client";

import Link from "next/link";
import { Database, FileText, RefreshCw, Rocket } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
  AdminStats,
  PipelineData,
} from "@/components/admin/admin-types";
import { KpiCard } from "@/components/admin/kpi-card";
import { Meter, ReadinessGauge } from "@/components/admin/meter";
import {
  SectionCard,
  SurfaceEmptyState,
  SurfaceFrame,
  SurfaceLoadingState,
  SurfaceStatGrid,
} from "@/components/admin/surface-frame";
import {
  adminFetch,
  formatNumber,
  formatPercent,
  toBelgianDateTime,
  useAdminResource,
} from "@/lib/admin-fetch";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
export default function PipelineSurface({
  enabled,
  stats,
}: {
  enabled: boolean;
  stats: AdminStats | null;
}) {
  const pipeline = useAdminResource<PipelineData>({
    enabled,
    intervalMs: 60_000,
    fetcher: async () => {
      const [financialsByYear, nbb, staatsblad] = await Promise.all([
        adminFetch<PipelineData["financialsByYear"]>(
          "/api/admin/financials-by-year",
        ).catch(() => []),
        adminFetch<PipelineData["nbb"]>("/api/admin/nbb-backload").catch(
          () => null,
        ),
        adminFetch<PipelineData["staatsblad"]>(
          "/api/admin/staatsblad-backload",
        ).catch(() => null),
      ]);

      return { financialsByYear, nbb, staatsblad };
    },
  });

  const completeness =
    stats == null
      ? 0
      : (stats.fully_loaded_companies / Math.max(stats.target_companies, 1)) * 100;

  return (
    <SurfaceFrame
      title="Data Pipeline"
      description="Coverage and operational backfills, without burying the operator in one giant admin wall."
      actions={
        <Button variant="outline" size="sm" onClick={() => void pipeline.refresh()}>
          <RefreshCw className="mr-2 size-4" />
          Refresh pipeline
        </Button>
      }
    >
      <Tabs defaultValue="coverage" className="w-full">
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-2 rounded-2xl bg-transparent p-0">
          <TabsTrigger value="coverage">Coverage</TabsTrigger>
          <TabsTrigger value="nbb">NBB</TabsTrigger>
          <TabsTrigger value="staatsblad">Staatsblad</TabsTrigger>
          <TabsTrigger value="enrichment">Enrichment</TabsTrigger>
        </TabsList>

        <TabsContent value="coverage" className="mt-5 space-y-5">
          {stats ? (
            <>
              <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
                <SectionCard
                  title="Coverage Score"
                  description="A simple measure of how close the Belgian company universe is to being deeply usable."
                >
                  <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
                    <ReadinessGauge score={completeness} />
                    <div className="flex-1 space-y-4">
                      <Meter label="Financial latest" value={(stats.companies_with_latest_financials / Math.max(stats.target_companies, 1)) * 100} toneClass="bg-sky-500" />
                      <Meter label="Admins" value={(stats.companies_with_admins / Math.max(stats.target_companies, 1)) * 100} toneClass="bg-emerald-500" />
                      <Meter label="Publications" value={(stats.companies_with_publications / Math.max(stats.target_companies, 1)) * 100} toneClass="bg-amber-500" />
                      <Meter label="Shareholders" value={(stats.companies_with_shareholders / Math.max(stats.target_companies, 1)) * 100} toneClass="bg-indigo-500" />
                    </div>
                  </div>
                </SectionCard>

                <SectionCard
                  title="Loaded Footprint"
                  description="Quick operator-level numbers instead of cross-referencing several old tabs."
                >
                  <SurfaceStatGrid className="xl:grid-cols-2">
                    <KpiCard
                      label="Fully Loaded"
                      value={formatNumber(stats.fully_loaded_companies)}
                      hint={`${formatPercent(completeness)} of target companies`}
                      icon={Database}
                    />
                    <KpiCard
                      label="Publications"
                      value={formatNumber(stats.companies_with_publications)}
                      hint={`${formatNumber(stats.companies_with_staatsblad)} companies with Staatsblad rows`}
                      icon={FileText}
                      accentClass="text-amber-700"
                    />
                  </SurfaceStatGrid>
                </SectionCard>
              </div>

              <SectionCard
                title="Financials By Year"
                description="A simple year view is more useful here than another chart-heavy admin wall."
              >
                {pipeline.isLoading && !pipeline.data ? (
                  <SurfaceLoadingState label="Loading year coverage…" />
                ) : pipeline.data?.financialsByYear.length ? (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Fiscal Year</TableHead>
                          <TableHead>Companies</TableHead>
                          <TableHead>Filings</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {pipeline.data.financialsByYear.map((row) => (
                          <TableRow key={row.fiscal_year}>
                            <TableCell className="font-medium">{row.fiscal_year}</TableCell>
                            <TableCell>{formatNumber(row.companies)}</TableCell>
                            <TableCell>{formatNumber(row.filings)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <SurfaceEmptyState
                    title="No financial year breakdown yet"
                    description="This panel fills in once the backfill breakdown is available."
                  />
                )}
              </SectionCard>
            </>
          ) : (
            <SurfaceLoadingState label="Loading coverage data…" />
          )}
        </TabsContent>

        <TabsContent value="nbb" className="mt-5 space-y-5">
          {pipeline.data?.nbb ? (
            <>
              <SurfaceStatGrid>
                <KpiCard
                  label="Financial History"
                  value={formatNumber(pipeline.data.nbb.companies_with_financial_history)}
                  hint={`${formatNumber(pipeline.data.nbb.financial_year_rows)} year rows`}
                  icon={Database}
                />
                <KpiCard
                  label="FY2024 Remaining"
                  value={formatNumber(pipeline.data.nbb.fy2024_remaining)}
                  hint={`${formatNumber(pipeline.data.nbb.fy2023_remaining)} still missing FY2023`}
                  icon={Database}
                  accentClass="text-sky-700"
                />
                <KpiCard
                  label="Rows 24h"
                  value={formatNumber(pipeline.data.nbb.rows_24h)}
                  hint={`${formatNumber(pipeline.data.nbb.real_filings_24h)} real filings in the last day`}
                  icon={RefreshCw}
                  accentClass="text-emerald-700"
                />
                <KpiCard
                  label="Last Checkpoint"
                  value={pipeline.data.nbb.last_checkpoint ?? "—"}
                  hint={
                    pipeline.data.nbb.eta_days_from_24h_pace == null
                      ? "ETA unavailable"
                      : `${pipeline.data.nbb.eta_days_from_24h_pace} days at current pace`
                  }
                  icon={FileText}
                />
              </SurfaceStatGrid>

              <SectionCard
                title="Recent Real Filings"
                description="The last successful real filings are usually the fastest sanity-check."
              >
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>CBE</TableHead>
                        <TableHead>Deposit Key</TableHead>
                        <TableHead>Rubrics</TableHead>
                        <TableHead>Loaded</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {pipeline.data.nbb.recent_real_filings.slice(0, 10).map((row) => (
                        <TableRow key={`${row.enterprise_number}-${row.loaded_at}`}>
                          <TableCell className="font-mono text-xs">
                            {row.enterprise_number}
                          </TableCell>
                          <TableCell>{row.deposit_key}</TableCell>
                          <TableCell>{formatNumber(row.rubric_count)}</TableCell>
                          <TableCell>{toBelgianDateTime(row.loaded_at)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </SectionCard>
            </>
          ) : (
            <SurfaceLoadingState label="Loading NBB progress…" />
          )}
        </TabsContent>

        <TabsContent value="staatsblad" className="mt-5 space-y-5">
          {pipeline.data?.staatsblad ? (
            <>
              <SurfaceStatGrid>
                <KpiCard
                  label="Final Goal Progress"
                  value={`${formatNumber(pipeline.data.staatsblad.done)} / ${formatNumber(pipeline.data.staatsblad.final_goal)}`}
                  hint={`${formatPercent(pipeline.data.staatsblad.completion_pct, 2)} done`}
                  icon={FileText}
                />
                <KpiCard
                  label="Resolved"
                  value={formatNumber(pipeline.data.staatsblad.resolved)}
                  hint={`${formatPercent(pipeline.data.staatsblad.resolved_pct, 2)} resolved`}
                  icon={FileText}
                  accentClass="text-emerald-700"
                />
                <KpiCard
                  label="Processed 24h"
                  value={formatNumber(pipeline.data.staatsblad.processed_24h)}
                  hint={`${formatNumber(pipeline.data.staatsblad.pubs_found_24h)} publications found`}
                  icon={RefreshCw}
                  accentClass="text-sky-700"
                />
                <KpiCard
                  label="Queue Still Pending"
                  value={formatNumber(pipeline.data.staatsblad.pending)}
                  hint={`${formatNumber(pipeline.data.staatsblad.failed)} failed`}
                  icon={Database}
                  accentClass="text-amber-700"
                />
              </SurfaceStatGrid>

              <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
                <SectionCard
                  title="Progress"
                  description="A straightforward read on how close the queue is to fully processed."
                >
                  <div className="space-y-4">
                    <Meter
                      label="Completion"
                      value={pipeline.data.staatsblad.completion_pct}
                      toneClass="bg-sky-500"
                    />
                    <Meter
                      label="Resolved"
                      value={pipeline.data.staatsblad.resolved_pct}
                      toneClass="bg-emerald-500"
                    />
                    <div className="rounded-2xl bg-slate-50 p-4">
                      <div className="text-sm font-medium text-slate-900">
                        Last completion
                      </div>
                      <div className="mt-1 body text-slate-600">
                        {toBelgianDateTime(pipeline.data.staatsblad.last_completed_at)}
                      </div>
                    </div>
                  </div>
                </SectionCard>

                <SectionCard
                  title="Recent Completions"
                  description="A small sample is usually enough for operator spot checks."
                >
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>CBE</TableHead>
                          <TableHead>Publications</TableHead>
                          <TableHead>Attempts</TableHead>
                          <TableHead>Completed</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {pipeline.data.staatsblad.recent_completions
                          .slice(0, 10)
                          .map((row) => (
                            <TableRow key={`${row.cbe}-${row.completed_at}`}>
                              <TableCell className="font-mono text-xs">{row.cbe}</TableCell>
                              <TableCell>{row.pubs_found ?? "—"}</TableCell>
                              <TableCell>{formatNumber(row.attempts)}</TableCell>
                              <TableCell>{toBelgianDateTime(row.completed_at)}</TableCell>
                            </TableRow>
                          ))}
                      </TableBody>
                    </Table>
                  </div>
                </SectionCard>
              </div>
            </>
          ) : (
            <SurfaceLoadingState label="Loading Staatsblad progress…" />
          )}
        </TabsContent>

        <TabsContent value="enrichment" className="mt-5">
          <SectionCard
            title="Dedicated Enrichment Cockpit"
            description="The enrichment dashboard stays its own tool so we keep the main admin clean and the password-gated flow intact."
          >
            <div className="rounded-3xl border border-sky-200 bg-sky-50 p-5">
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex items-start gap-3">
                  <div className="rounded-2xl bg-white p-3 text-sky-700 shadow-sm">
                    <Rocket className="size-5" />
                  </div>
                  <div className="space-y-1">
                    <div className="text-base font-semibold text-slate-900">
                      Semantic enrichment operations
                    </div>
                    <div className="body text-slate-600">
                      Pause or resume the worker, inspect dead letters, manage the skip-list, and monitor budget without overloading the main admin.
                    </div>
                  </div>
                </div>
                <Link href="/admin/enrichment">
                  <Button size="sm">Open enrichment cockpit</Button>
                </Link>
              </div>
            </div>
          </SectionCard>
        </TabsContent>
      </Tabs>
    </SurfaceFrame>
  );
}
