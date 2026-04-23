"use client";

import Link from "next/link";
import {
  Activity,
  BarChart3,
  Building2,
  CreditCard,
  Database,
  Layers,
  MessageSquare,
  Rocket,
  Settings,
  TrendingUp,
  Users,
} from "lucide-react";
import type { AdminStats, OverviewData } from "@/components/admin/admin-types";
import { KpiCard } from "@/components/admin/kpi-card";
import { Meter } from "@/components/admin/meter";
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
  useAdminResource,
} from "@/lib/admin-fetch";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

type AdminSurfaceKey =
  | "overview"
  | "people"
  | "revenue"
  | "pipeline"
  | "analytics"
  | "settings";

const QUICK_ACTIONS: {
  key: AdminSurfaceKey;
  label: string;
  description: string;
  icon: typeof Users;
}[] = [
  {
    key: "people",
    label: "People",
    description: "Users, feedback, polls, and tier controls.",
    icon: Users,
  },
  {
    key: "revenue",
    label: "Revenue",
    description: "ARR, payments, invoices, and AI spend.",
    icon: CreditCard,
  },
  {
    key: "pipeline",
    label: "Pipeline",
    description: "Coverage, NBB progress, and Staatsblad queues.",
    icon: Database,
  },
  {
    key: "analytics",
    label: "Analytics",
    description: "Traffic, adoption, activity, and traction.",
    icon: BarChart3,
  },
  {
    key: "settings",
    label: "Settings",
    description: "Logo and maintenance utilities.",
    icon: Settings,
  },
];

export default function OverviewSurface({
  enabled,
  stats,
  statsLoading,
  onOpenSurface,
  onRefreshStats,
}: {
  enabled: boolean;
  stats: AdminStats | null;
  statsLoading: boolean;
  onOpenSurface: (surface: AdminSurfaceKey) => void;
  onRefreshStats: () => Promise<void>;
}) {
  const overview = useAdminResource<OverviewData>({
    enabled,
    intervalMs: 30_000,
    fetcher: async () => {
      const [insights, polls] = await Promise.all([
        adminFetch<OverviewData["insights"]>("/api/admin/insights").catch(
          () => null,
        ),
        adminFetch<OverviewData["polls"]>("/api/polls").catch(() => []),
      ]);

      return { insights, polls };
    },
  });

  if (!stats && statsLoading) {
    return <SurfaceLoadingState label="Loading admin overview…" />;
  }

  if (!stats) {
    return (
      <SurfaceEmptyState
        title="Overview is unavailable"
        description="The admin shell could not load the core platform stats."
      />
    );
  }

  const completeness =
    (stats.fully_loaded_companies / Math.max(stats.target_companies, 1)) * 100;
  const activePoll = overview.data?.polls.find((poll) => poll.status === "active");

  return (
    <SurfaceFrame
      title="Admin Cockpit"
      description="A calmer top-level view of platform health, operator queues, and the next place to work."
      actions={
        <Button variant="outline" size="sm" onClick={() => void onRefreshStats()}>
          Refresh core stats
        </Button>
      }
    >
      <Card className="overflow-hidden border-0 bg-[linear-gradient(135deg,#0f172a_0%,#1d4ed8_45%,#22c55e_100%)] text-white shadow-[0_25px_80px_-45px_rgba(15,23,42,0.8)]">
        <CardContent className="space-y-6 p-6 sm:p-7">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Badge className="border-white/15 bg-white/10 text-white hover:bg-white/10">
                  {formatNumber(stats.daily_active_users)} daily active
                </Badge>
                <Badge className="border-white/15 bg-white/10 text-white hover:bg-white/10">
                  {formatNumber(stats.total_users)} total users
                </Badge>
                <Badge className="border-white/15 bg-white/10 text-white hover:bg-white/10">
                  DB {stats.db_size}
                </Badge>
              </div>
              <div>
                <div className="text-sm text-sky-100">Platform completeness</div>
                <div className="mt-1 text-5xl font-semibold tracking-tight">
                  {formatPercent(completeness)}
                </div>
                <div className="mt-2 text-sm text-sky-100/90">
                  {formatNumber(stats.fully_loaded_companies)} fully loaded companies out of{" "}
                  {formatNumber(stats.target_companies)} target companies.
                </div>
              </div>
            </div>

            <div className="grid min-w-[260px] gap-3 rounded-3xl border border-white/15 bg-white/10 p-4 backdrop-blur">
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-sky-100">
                  Most Visited
                </div>
                <div className="mt-1 text-sm font-medium">
                  {stats.most_visited_page || "No signal yet"}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-sky-100">
                  Feedback Inbox
                </div>
                <div className="mt-1 text-sm font-medium">
                  {formatNumber(stats.total_feedback)} items, {formatNumber(stats.bug_count)} bugs
                </div>
              </div>
            </div>
          </div>

          <Meter label="Loaded company coverage" value={completeness} toneClass="bg-white" />
        </CardContent>
      </Card>

      <SurfaceStatGrid>
        <KpiCard
          label="Daily Active"
          value={formatNumber(stats.daily_active_users)}
          hint="Distinct users in the last 24 hours."
          icon={Activity}
        />
        <KpiCard
          label="Financial History"
          value={formatNumber(stats.companies_with_history)}
          hint={`${formatNumber(stats.companies_with_latest_financials)} with latest year loaded`}
          icon={Database}
          accentClass="text-sky-700"
        />
        <KpiCard
          label="Admins & Shareholders"
          value={formatNumber(stats.companies_with_admins)}
          hint={`${formatNumber(stats.companies_with_shareholders)} companies with shareholders`}
          icon={Building2}
          accentClass="text-emerald-700"
        />
        <KpiCard
          label="Blocked Users"
          value={formatNumber(stats.blocked_users)}
          hint={`${formatNumber(stats.admin_users)} admins on the platform`}
          icon={Layers}
          accentClass="text-amber-700"
        />
      </SurfaceStatGrid>

      <SectionCard
        title="Next Actions"
        description="Jump into the specific admin surface you need without scanning a wall of tabs."
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {QUICK_ACTIONS.map(({ key, label, description, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => onOpenSurface(key)}
              className="rounded-2xl border border-slate-200 bg-white p-4 text-left transition hover:border-slate-300 hover:bg-slate-50"
            >
              <div className="flex items-center gap-3">
                <div className="rounded-2xl bg-slate-100 p-3 text-slate-700">
                  <Icon className="size-4" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-slate-900">{label}</div>
                  <div className="body-sm text-slate-500">{description}</div>
                </div>
              </div>
            </button>
          ))}
          <Link
            href="/admin/enrichment"
            className="rounded-2xl border border-sky-200 bg-sky-50 p-4 transition hover:border-sky-300 hover:bg-sky-100/70"
          >
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-white p-3 text-sky-700 shadow-sm">
                <Rocket className="size-4" />
              </div>
              <div>
                <div className="text-sm font-semibold text-slate-900">
                  Enrichment Cockpit
                </div>
                <div className="body-sm text-slate-500">
                  Open the dedicated bulk enrichment dashboard.
                </div>
              </div>
            </div>
          </Link>
        </div>
      </SectionCard>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <SectionCard
          title="Health Snapshot"
          description="High-level operational health without needing to open the deeper analytics sections."
        >
          {overview.isLoading && !overview.data ? (
            <SurfaceLoadingState label="Loading overview signals…" />
          ) : (
            <div className="space-y-4">
              <Meter
                label="Company data coverage"
                value={overview.data?.insights?.coverage_pct ?? completeness}
                toneClass="bg-emerald-500"
              />
              <Meter
                label="Load success rate"
                value={overview.data?.insights?.success_rate ?? 100}
                toneClass="bg-sky-500"
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl bg-slate-50 p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-slate-500">
                    Auth Traffic
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-slate-900">
                    {formatNumber(overview.data?.insights?.auth_requests_7d ?? 0)}
                  </div>
                  <div className="body-sm text-slate-500">Requests in the last 7 days.</div>
                </div>
                <div className="rounded-2xl bg-slate-50 p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-slate-500">
                    Anonymous Traffic
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-slate-900">
                    {formatNumber(overview.data?.insights?.anon_requests_7d ?? 0)}
                  </div>
                  <div className="body-sm text-slate-500">Requests in the last 7 days.</div>
                </div>
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard
          title="What Needs Attention"
          description="The things most likely to matter to the operator right now."
        >
          <div className="space-y-3">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                <TrendingUp className="size-4 text-emerald-600" />
                User growth
              </div>
              <div className="mt-2 body-sm text-slate-600">
                {formatNumber(overview.data?.insights?.new_users_7d ?? 0)} new users in the last week.
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                <MessageSquare className="size-4 text-amber-600" />
                Feedback backlog
              </div>
              <div className="mt-2 body-sm text-slate-600">
                {formatNumber(stats.total_feedback)} total messages, including{" "}
                {formatNumber(stats.bug_count)} bugs and{" "}
                {formatNumber(stats.suggestion_count)} suggestions.
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                <Rocket className="size-4 text-sky-600" />
                Enrichment
              </div>
              <div className="mt-2 body-sm text-slate-600">
                Use the dedicated cockpit when you need worker health, dead letters, or budget control.
              </div>
            </div>
          </div>
        </SectionCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <SectionCard
          title="Current Poll"
          description="The poll that is currently active for signed-in users."
        >
          {activePoll ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-slate-50 p-4">
                <div className="text-base font-semibold text-slate-900">
                  {activePoll.title}
                </div>
                <div className="mt-1 body text-slate-600">{activePoll.question}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                {activePoll.options.map((option) => (
                  <Badge key={option} variant="secondary">
                    {option}: {formatNumber(activePoll.votes[option] ?? 0)}
                  </Badge>
                ))}
              </div>
            </div>
          ) : (
            <SurfaceEmptyState
              title="No active poll"
              description="The people surface is where you create or reactivate polls."
            />
          )}
        </SectionCard>

        <SectionCard
          title="Top Companies"
          description="Most-viewed company profiles from the recent analytics window."
        >
          {overview.data?.insights?.top_companies?.length ? (
            <div className="space-y-3">
              {overview.data.insights.top_companies.slice(0, 5).map((company) => (
                <div
                  key={company.cbe}
                  className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3"
                >
                  <div>
                    <div className="text-sm font-medium text-slate-900">{company.name}</div>
                    <div className="body-sm font-mono text-slate-500">{company.cbe}</div>
                  </div>
                  <Badge variant="outline">
                    {formatNumber(company.view_count)} views
                  </Badge>
                </div>
              ))}
            </div>
          ) : (
            <SurfaceEmptyState
              title="No company view signal yet"
              description="This card fills in once recent admin insights are available."
            />
          )}
        </SectionCard>
      </div>
    </SurfaceFrame>
  );
}
