"use client";

/**
 * Readiness panel — the unified view of the three production data
 * pipelines (NBB backload, semantic enrichment, Staatsblad). Reads from
 * /api/admin/readiness which the backend computes in a single round
 * trip with per-pipeline status badges, freshness, throughput, and
 * recent failures.
 *
 * The component is fully self-contained: it accepts a fetch helper
 * (so the parent page can keep its auth wrapping) and renders a
 * skeleton on first load. No global state, no side effects beyond the
 * fetch.
 */

import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CircleCheck,
  CircleAlert,
  TriangleAlert,
  RefreshCw,
  ExternalLink,
  Clock,
} from "lucide-react";

type PipelineStatus = "healthy" | "warning" | "broken";

interface PipelineBlock {
  name: string;
  status: PipelineStatus;
  last_run_at: string | null;
  completed: number;
  remaining: number | null;
  excluded?: number | null;
  progress_pct: number | null;
  errors_24h: number;
  recent_failures: string[];
  freshness_h: number | null;
  throughput_24h?: number;
  throughput_7d?: number;
  publications_total?: number;
  publications_24h?: number;
  data_freshness_date?: string | null;
  paused?: boolean;
  budget_usd?: number;
  spend_today_usd?: number;
  queue?: Record<string, number>;
  notes?: string;
  details_url?: string;
}

interface ReadinessResponse {
  nbb: PipelineBlock;
  semantic: PipelineBlock;
  staatsblad: PipelineBlock;
  overall: PipelineStatus;
  computed_at: number;
}

interface Props {
  fetcher: <T>(url: string, init?: RequestInit) => Promise<T>;
}

const STATUS_STYLE: Record<PipelineStatus, { label: string; cls: string; Icon: typeof CircleCheck }> = {
  healthy: {
    label: "Healthy",
    cls: "bg-green-100 text-green-800 border-green-300",
    Icon: CircleCheck,
  },
  warning: {
    label: "Warning",
    cls: "bg-amber-100 text-amber-800 border-amber-300",
    Icon: TriangleAlert,
  },
  broken: {
    label: "Broken",
    cls: "bg-red-100 text-red-800 border-red-300",
    Icon: CircleAlert,
  },
};

function fmtAge(h: number | null | undefined): string {
  if (h == null) return "—";
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h < 48) return `${Math.round(h)}h`;
  return `${Math.round(h / 24)}d`;
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtPct(p: number | null | undefined): string {
  if (p == null) return "—";
  return `${p.toFixed(1)}%`;
}

function PipelineCard({ block }: { block: PipelineBlock }) {
  const s = STATUS_STYLE[block.status] ?? STATUS_STYLE.warning;
  const StatusIcon = s.Icon;
  const progress = block.progress_pct;

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-base font-semibold truncate">{block.name}</h3>
            {block.notes ? (
              <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{block.notes}</p>
            ) : null}
          </div>
          <Badge className={`flex items-center gap-1 border ${s.cls}`}>
            <StatusIcon className="h-3 w-3" />
            {s.label}
          </Badge>
        </div>

        {progress != null && (
          <div>
            <div className="flex justify-between text-[11px] text-muted-foreground">
              <span>Progress</span>
              <span>{fmtPct(progress)}</span>
            </div>
            <div className="h-2 bg-muted rounded mt-1 overflow-hidden">
              <div
                className={`h-full ${
                  block.status === "broken"
                    ? "bg-red-500"
                    : block.status === "warning"
                    ? "bg-amber-500"
                    : "bg-emerald-500"
                }`}
                style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
              />
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
          <div className="text-muted-foreground">Completed</div>
          <div className="text-right tabular-nums">{fmtNum(block.completed)}</div>
          {block.remaining != null && (
            <>
              <div className="text-muted-foreground">Remaining</div>
              <div className="text-right tabular-nums">{fmtNum(block.remaining)}</div>
            </>
          )}
          {block.excluded != null && (
            <>
              <div className="text-muted-foreground">Excluded</div>
              <div className="text-right tabular-nums">{fmtNum(block.excluded)}</div>
            </>
          )}
          {block.throughput_24h != null && (
            <>
              <div className="text-muted-foreground">Throughput 24h</div>
              <div className="text-right tabular-nums">{fmtNum(block.throughput_24h)}</div>
            </>
          )}
          {block.throughput_7d != null && (
            <>
              <div className="text-muted-foreground">Throughput 7d</div>
              <div className="text-right tabular-nums">{fmtNum(block.throughput_7d)}</div>
            </>
          )}
          <div className="text-muted-foreground">Freshness</div>
          <div className="text-right tabular-nums flex items-center justify-end gap-1">
            <Clock className="h-3 w-3 opacity-60" />
            {fmtAge(block.freshness_h)}
          </div>
          {block.errors_24h > 0 && (
            <>
              <div className="text-muted-foreground">Errors 24h</div>
              <div className="text-right tabular-nums text-red-600 font-medium">
                {block.errors_24h}
              </div>
            </>
          )}
          {block.spend_today_usd != null && (
            <>
              <div className="text-muted-foreground">Spend today</div>
              <div className="text-right tabular-nums">
                ${block.spend_today_usd.toFixed(2)}
                {block.budget_usd ? ` / $${block.budget_usd.toFixed(0)}` : ""}
              </div>
            </>
          )}
          {block.publications_total != null && (
            <>
              <div className="text-muted-foreground">Publications</div>
              <div className="text-right tabular-nums">{fmtNum(block.publications_total)}</div>
            </>
          )}
        </div>

        {block.queue && Object.keys(block.queue).length > 0 && (
          <div className="text-[11px] text-muted-foreground border-t pt-2">
            Queue:{" "}
            {Object.entries(block.queue)
              .filter(([, v]) => v != null)
              .map(([k, v]) => `${k}=${fmtNum(v as number)}`)
              .join(" · ")}
          </div>
        )}

        {block.recent_failures && block.recent_failures.length > 0 && (
          <details className="text-[11px]">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              Recent failures ({block.recent_failures.length})
            </summary>
            <ul className="mt-1.5 space-y-0.5 pl-3">
              {block.recent_failures.slice(0, 5).map((f, i) => (
                <li key={i} className="text-red-700 font-mono break-all line-clamp-2">
                  {f}
                </li>
              ))}
            </ul>
          </details>
        )}

        {block.paused && (
          <div className="text-[11px] text-amber-700 border-t pt-2 font-medium">
            Worker paused (meta.enrichment_enabled = false)
          </div>
        )}

        {block.details_url && (
          <div className="pt-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => {
                if (block.details_url?.startsWith("/")) {
                  window.location.assign(block.details_url);
                }
              }}
            >
              <ExternalLink className="h-3 w-3 mr-1" />
              Open detail view
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ReadinessPanel({ fetcher }: Props) {
  const [data, setData] = useState<ReadinessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load(opts?: { refresh?: boolean }) {
    if (opts?.refresh) setRefreshing(true);
    try {
      // Force a server-side cache bust on explicit refresh.
      if (opts?.refresh) {
        try {
          await fetcher<{ dropped: number }>("/api/admin/pulse/cache-bust", { method: "POST" });
        } catch {
          /* non-fatal */
        }
      }
      const r = await fetcher<ReadinessResponse>("/api/admin/readiness");
      setData(r);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load readiness");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    load();
    // Auto-refresh every 5 min so a long admin session keeps fresh
    // health data without operator clicks. Idle tabs are fine — the
    // fetch is cheap and the backend caches at 60 s anyway.
    const t = window.setInterval(load, 5 * 60_000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const overall = data?.overall;
  const overallStyle = overall ? STATUS_STYLE[overall] : STATUS_STYLE.warning;
  const OverallIcon = overallStyle.Icon;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">Data Readiness</h2>
          {overall && (
            <Badge className={`flex items-center gap-1 border ${overallStyle.cls}`}>
              <OverallIcon className="h-3 w-3" />
              {overallStyle.label}
            </Badge>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => load({ refresh: true })}
          disabled={refreshing}
          className="h-8"
        >
          <RefreshCw className={`h-3 w-3 mr-1 ${refreshing ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {err && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
          {err}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {loading || !data ? (
          <>
            <Skeleton className="h-56 animate-pulse" />
            <Skeleton className="h-56 animate-pulse" />
            <Skeleton className="h-56 animate-pulse" />
          </>
        ) : (
          <>
            <PipelineCard block={data.nbb} />
            <PipelineCard block={data.semantic} />
            <PipelineCard block={data.staatsblad} />
          </>
        )}
      </div>

      {data && (
        <div className="text-[11px] text-muted-foreground">
          Computed {new Date(data.computed_at * 1000).toLocaleTimeString()}; cache TTL 60 s.
          Pipelines roll up to overall: <span className="font-medium">{overallStyle.label}</span>.
        </div>
      )}
    </div>
  );
}
