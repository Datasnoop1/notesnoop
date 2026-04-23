"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Activity, Database, MessageSquare, RefreshCw, Users } from "lucide-react";
import type { AdminStats } from "@/components/admin/admin-types";
import { SurfaceErrorState, SurfaceLoadingState } from "@/components/admin/surface-frame";
import {
  isAuthError,
  useAdminResource,
  adminFetch,
  formatNumber,
} from "@/lib/admin-fetch";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const OverviewSurface = dynamic(
  () => import("@/components/admin/overview-surface"),
  {
    loading: () => <SurfaceLoadingState label="Loading overview…" />,
  },
);

const PeopleSurface = dynamic(
  () => import("@/components/admin/people-surface"),
  {
    loading: () => <SurfaceLoadingState label="Loading people tools…" />,
  },
);

const RevenueSurface = dynamic(
  () => import("@/components/admin/revenue-surface"),
  {
    loading: () => <SurfaceLoadingState label="Loading revenue tools…" />,
  },
);

const PipelineSurface = dynamic(
  () => import("@/components/admin/pipeline-surface"),
  {
    loading: () => <SurfaceLoadingState label="Loading data pipeline…" />,
  },
);

const AnalyticsSurface = dynamic(
  () => import("@/components/admin/analytics-surface"),
  {
    loading: () => <SurfaceLoadingState label="Loading analytics…" />,
  },
);

const SettingsSurface = dynamic(
  () => import("@/components/admin/settings-surface"),
  {
    loading: () => <SurfaceLoadingState label="Loading settings…" />,
  },
);

const SURFACES = [
  {
    key: "overview",
    label: "Overview",
    description: "Top-level health and next actions.",
  },
  {
    key: "people",
    label: "People",
    description: "Users, feedback, polls, and tiers.",
  },
  {
    key: "revenue",
    label: "Revenue",
    description: "ARR, invoices, payments, and AI spend.",
  },
  {
    key: "pipeline",
    label: "Pipeline",
    description: "Coverage, NBB, Staatsblad, enrichment.",
  },
  {
    key: "analytics",
    label: "Analytics",
    description: "Traffic, adoption, and raw activity.",
  },
  {
    key: "settings",
    label: "Settings",
    description: "Platform-wide switches and maintenance.",
  },
] as const;

type AdminSurfaceKey = (typeof SURFACES)[number]["key"];

function isSurfaceKey(value: string | null): value is AdminSurfaceKey {
  return SURFACES.some((surface) => surface.key === value);
}

export function AdminShell() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeSurface = isSurfaceKey(searchParams.get("tab"))
    ? searchParams.get("tab")
    : "overview";
  const [visited, setVisited] = useState<Record<AdminSurfaceKey, boolean>>(() => ({
    overview: true,
    people: activeSurface === "people",
    revenue: activeSurface === "revenue",
    pipeline: activeSurface === "pipeline",
    analytics: activeSurface === "analytics",
    settings: activeSurface === "settings",
  }));

  const stats = useAdminResource<AdminStats>({
    enabled: true,
    fetcher: () => adminFetch<AdminStats>("/api/admin/stats"),
  });

  useEffect(() => {
    if (stats.error && isAuthError(stats.error)) {
      router.replace("/login");
    }
  }, [router, stats.error]);

  const openSurface = (surface: AdminSurfaceKey) => {
    setVisited((current) => ({ ...current, [surface]: true }));
    const next = new URLSearchParams(searchParams.toString());
    if (surface === "overview") next.delete("tab");
    else next.set("tab", surface);

    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  };

  if (
    stats.error &&
    !stats.data &&
    stats.error.status !== 401 &&
    stats.error.status !== 403
  ) {
    return (
      <SurfaceErrorState
        message={stats.error.message}
        onRetry={() => void stats.refresh()}
      />
    );
  }

  if (!stats.data) {
    return <SurfaceLoadingState label="Checking admin access…" />;
  }

  return (
    <div className="space-y-6">
      <div className="rounded-[28px] border border-white/70 bg-white/90 p-5 shadow-[0_20px_80px_-40px_rgba(15,23,42,0.35)] backdrop-blur sm:p-6">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div className="space-y-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-600">
              Internal
            </div>
            <div>
              <h1 className="heading-1 text-slate-900">Admin</h1>
              <p className="body text-slate-600">
                Rebuilt as a smaller set of focused operator surfaces instead of one slow, chaotic page.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary" className="px-3 py-1.5">
              <Users className="mr-1 size-3.5" />
              {formatNumber(stats.data?.total_users ?? 0)} users
            </Badge>
            <Badge variant="secondary" className="px-3 py-1.5">
              <Activity className="mr-1 size-3.5" />
              {formatNumber(stats.data?.daily_active_users ?? 0)} active
            </Badge>
            <Badge variant="secondary" className="px-3 py-1.5">
              <MessageSquare className="mr-1 size-3.5" />
              {formatNumber(stats.data?.total_feedback ?? 0)} feedback
            </Badge>
            <Badge variant="secondary" className="px-3 py-1.5">
              <Database className="mr-1 size-3.5" />
              {stats.data?.db_size || "—"}
            </Badge>
            <Button variant="outline" size="sm" onClick={() => void stats.refresh()}>
              <RefreshCw className="mr-2 size-4" />
              Refresh
            </Button>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {SURFACES.map((surface) => (
            <button
              key={surface.key}
              type="button"
              onClick={() => openSurface(surface.key)}
              className={cn(
                "rounded-full border px-4 py-2 text-left transition",
                activeSurface === surface.key
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900",
              )}
            >
              <div className="text-sm font-semibold">{surface.label}</div>
              <div
                className={cn(
                  "hidden text-xs md:block",
                  activeSurface === surface.key ? "text-slate-300" : "text-slate-500",
                )}
              >
                {surface.description}
              </div>
            </button>
          ))}
        </div>
      </div>

      {visited.overview || activeSurface === "overview" ? (
        <div className={cn(activeSurface === "overview" ? "block" : "hidden")}>
          <OverviewSurface
            enabled={activeSurface === "overview"}
            stats={stats.data}
            statsLoading={stats.isLoading}
            onOpenSurface={openSurface}
            onRefreshStats={stats.refresh}
          />
        </div>
      ) : null}

      {visited.people || activeSurface === "people" ? (
        <div className={cn(activeSurface === "people" ? "block" : "hidden")}>
          <PeopleSurface enabled={activeSurface === "people"} />
        </div>
      ) : null}

      {visited.revenue || activeSurface === "revenue" ? (
        <div className={cn(activeSurface === "revenue" ? "block" : "hidden")}>
          <RevenueSurface enabled={activeSurface === "revenue"} />
        </div>
      ) : null}

      {visited.pipeline || activeSurface === "pipeline" ? (
        <div className={cn(activeSurface === "pipeline" ? "block" : "hidden")}>
          <PipelineSurface enabled={activeSurface === "pipeline"} stats={stats.data} />
        </div>
      ) : null}

      {visited.analytics || activeSurface === "analytics" ? (
        <div className={cn(activeSurface === "analytics" ? "block" : "hidden")}>
          <AnalyticsSurface enabled={activeSurface === "analytics"} />
        </div>
      ) : null}

      {visited.settings || activeSurface === "settings" ? (
        <div className={cn(activeSurface === "settings" ? "block" : "hidden")}>
          <SettingsSurface enabled={activeSurface === "settings"} />
        </div>
      ) : null}
    </div>
  );
}
