"use client";

import { BarChart3, Globe, TrendingUp, Users } from "lucide-react";
import type { AnalyticsData } from "@/components/admin/admin-types";
import { KpiCard } from "@/components/admin/kpi-card";
import {
  SectionCard,
  SurfaceEmptyState,
  SurfaceErrorState,
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function AnalyticsSurface({
  enabled,
}: {
  enabled: boolean;
}) {
  const analytics = useAdminResource<AnalyticsData>({
    enabled,
    intervalMs: 60_000,
    fetcher: async () => {
      const [insights, usage, adoption, traction, activity, activitySummary] =
        await Promise.all([
          adminFetch<AnalyticsData["insights"]>("/api/admin/insights").catch(
            () => null,
          ),
          adminFetch<AnalyticsData["usage"]>("/api/admin/usage").catch(
            () => null,
          ),
          adminFetch<AnalyticsData["adoption"]>("/api/admin/adoption").catch(
            () => null,
          ),
          adminFetch<AnalyticsData["traction"]>("/api/admin/traction").catch(
            () => null,
          ),
          adminFetch<AnalyticsData["activity"]>("/api/admin/activity").catch(
            () => [],
          ),
          adminFetch<AnalyticsData["activitySummary"]>(
            "/api/admin/activity/summary",
          ).catch(() => []),
        ]);

      return { insights, usage, adoption, traction, activity, activitySummary };
    },
  });

  if (analytics.isLoading && !analytics.data) {
    return <SurfaceLoadingState label="Loading analytics…" />;
  }

  if (analytics.error && !analytics.data) {
    return (
      <SurfaceErrorState
        message={analytics.error.message}
        onRetry={() => void analytics.refresh()}
      />
    );
  }

  const insights = analytics.data?.insights;
  const usage = analytics.data?.usage;
  const adoption = analytics.data?.adoption;
  const traction = analytics.data?.traction;

  return (
    <SurfaceFrame
      title="Analytics"
      description="Traffic, engagement, and operator-facing usage signals arranged so they answer questions quickly."
      actions={
        <Button variant="outline" size="sm" onClick={() => void analytics.refresh()}>
          Refresh analytics
        </Button>
      }
    >
      <SurfaceStatGrid>
        <KpiCard
          label="Total Users"
          value={formatNumber(insights?.total_users ?? 0)}
          hint={`${formatNumber(insights?.active_users_7d ?? 0)} active in the last 7 days`}
          icon={Users}
        />
        <KpiCard
          label="New Users 7d"
          value={formatNumber(insights?.new_users_7d ?? 0)}
          hint={`${formatNumber(insights?.new_users_prev_7d ?? 0)} in the prior 7-day window`}
          icon={TrendingUp}
          accentClass="text-emerald-700"
        />
        <KpiCard
          label="Requests 30d"
          value={formatNumber(usage?.totals.total_requests_30d ?? 0)}
          hint={`${formatNumber(usage?.totals.unique_registered_30d ?? 0)} registered + ${formatNumber(usage?.totals.unique_guests_30d ?? 0)} anonymous users`}
          icon={Globe}
          accentClass="text-sky-700"
        />
        <KpiCard
          label="Coverage"
          value={formatPercent(insights?.coverage_pct ?? 0)}
          hint={`${formatPercent(insights?.success_rate ?? 0)} load success rate`}
          icon={BarChart3}
          accentClass="text-amber-700"
        />
      </SurfaceStatGrid>

      <Tabs defaultValue="health" className="w-full">
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-2 rounded-2xl bg-transparent p-0">
          <TabsTrigger value="health">Health</TabsTrigger>
          <TabsTrigger value="traffic">Traffic</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
        </TabsList>

        <TabsContent value="health" className="mt-5 space-y-5">
          <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <SectionCard
              title="Top Companies"
              description="Most-viewed company profiles from the recent analytics window."
            >
              {insights?.top_companies?.length ? (
                <div className="space-y-3">
                  {insights.top_companies.slice(0, 8).map((company) => (
                    <div
                      key={company.cbe}
                      className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3"
                    >
                      <div>
                        <div className="text-sm font-medium text-slate-900">
                          {company.name}
                        </div>
                        <div className="body-sm font-mono text-slate-500">
                          {company.cbe}
                        </div>
                      </div>
                      <Badge variant="outline">
                        {formatNumber(company.view_count)} views
                      </Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No top-company signal yet"
                  description="This list appears once recent company activity is available."
                />
              )}
            </SectionCard>

            <SectionCard
              title="Feature Adoption"
              description="Which product surfaces signed-in users are actually spending time in."
            >
              {adoption?.features?.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Feature</TableHead>
                        <TableHead>Requests</TableHead>
                        <TableHead>Unique Users</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {adoption.features.map((row) => (
                        <TableRow key={row.feature}>
                          <TableCell>{row.feature}</TableCell>
                          <TableCell>{formatNumber(row.requests)}</TableCell>
                          <TableCell>{formatNumber(row.unique_users)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No feature adoption data"
                  description="The adoption endpoint did not return any feature rows."
                />
              )}
            </SectionCard>
          </div>
        </TabsContent>

        <TabsContent value="traffic" className="mt-5 space-y-5">
          <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <SectionCard
              title="Top Pages"
              description="The pages and API groupings that currently absorb the most attention."
            >
              {usage?.top_pages?.length ? (
                <div className="space-y-3">
                  {usage.top_pages.map((page) => (
                    <div
                      key={page.page}
                      className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3"
                    >
                      <div>
                        <div className="text-sm font-medium text-slate-900">
                          {page.page}
                        </div>
                        <div className="body-sm text-slate-500">
                          {formatNumber(page.unique_users)} unique users
                        </div>
                      </div>
                      <Badge variant="secondary">
                        {formatNumber(page.requests)} requests
                      </Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No top-page data"
                  description="Recent usage data will populate this section."
                />
              )}
            </SectionCard>

            <SectionCard
              title="Guest vs Registered"
              description="Traffic mix matters because free anonymous use is a deliberate product choice."
            >
              {traction ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <div className="body-sm text-slate-500">Guests 30d</div>
                    <div className="mt-2 text-3xl font-semibold text-slate-900">
                      {formatNumber(traction.kpis.guests_30d)}
                    </div>
                    <div className="body-sm text-slate-500">
                      {formatNumber(traction.kpis.requests_30d)} requests in 30 days
                    </div>
                  </div>
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <div className="body-sm text-slate-500">Registered 30d</div>
                    <div className="mt-2 text-3xl font-semibold text-slate-900">
                      {formatNumber(traction.kpis.registered_30d)}
                    </div>
                    <div className="body-sm text-slate-500">
                      Avg pages / guest: {formatNumber(traction.engagement.avg_pages_per_guest)}
                    </div>
                  </div>
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No traction snapshot"
                  description="The traction endpoint did not return a usable payload."
                />
              )}
            </SectionCard>
          </div>

          <SectionCard
            title="Top Registered Users"
            description="A quick sense of who is actually leaning on the product."
          >
            {usage?.top_registered?.length ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>User</TableHead>
                      <TableHead>Requests</TableHead>
                      <TableHead>Unique Pages</TableHead>
                      <TableHead>Last Seen</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {usage.top_registered.map((row) => (
                      <TableRow key={row.user_email}>
                        <TableCell>{row.user_email}</TableCell>
                        <TableCell>{formatNumber(row.requests)}</TableCell>
                        <TableCell>{formatNumber(row.unique_pages)}</TableCell>
                        <TableCell>{toBelgianDateTime(row.last_seen)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <SurfaceEmptyState
                title="No registered-user ranking yet"
                description="This list fills in once recent usage data exists."
              />
            )}
          </SectionCard>
        </TabsContent>

        <TabsContent value="activity" className="mt-5 space-y-5">
          <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
            <SectionCard
              title="Activity Summary"
              description="Recent high-level activity grouped by user."
            >
              {analytics.data?.activitySummary.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>User</TableHead>
                        <TableHead>Requests</TableHead>
                        <TableHead>Unique Pages</TableHead>
                        <TableHead>Last Active</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {analytics.data.activitySummary.slice(0, 12).map((row) => (
                        <TableRow key={row.user_email}>
                          <TableCell>{row.user_email}</TableCell>
                          <TableCell>{formatNumber(row.total_requests)}</TableCell>
                          <TableCell>{formatNumber(row.unique_pages)}</TableCell>
                          <TableCell>{toBelgianDateTime(row.last_active)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No grouped activity yet"
                  description="The summary endpoint did not return recent activity groups."
                />
              )}
            </SectionCard>

            <SectionCard
              title="Recent Activity Log"
              description="The raw event stream stays here for operator spot checks."
            >
              {analytics.data?.activity.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>User</TableHead>
                        <TableHead>Method</TableHead>
                        <TableHead>Endpoint</TableHead>
                        <TableHead>Created</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {analytics.data.activity.slice(0, 40).map((row, index) => (
                        <TableRow key={`${row.user_email}-${row.created_at}-${index}`}>
                          <TableCell>{row.user_email}</TableCell>
                          <TableCell>
                            <Badge variant="secondary">{row.method}</Badge>
                          </TableCell>
                          <TableCell className="font-mono text-xs">{row.endpoint}</TableCell>
                          <TableCell>{toBelgianDateTime(row.created_at)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No raw activity rows"
                  description="The activity log endpoint did not return recent rows."
                />
              )}
            </SectionCard>
          </div>
        </TabsContent>
      </Tabs>
    </SurfaceFrame>
  );
}
