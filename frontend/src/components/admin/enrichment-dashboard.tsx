"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Database,
  Gauge,
  Loader2,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
const PW_KEY = "enrichment_admin_pw";

type Overview = {
  enabled: boolean;
  queue_counts: Record<string, number>;
  progress: {
    total_jobs: number;
    raw_total_jobs: number;
    completed_jobs: number;
    done_jobs: number;
    queued_jobs: number;
    claimed_jobs: number;
    failed_jobs: number;
    dead_jobs: number;
    excluded_jobs: number;
    completion_pct: number;
    first_enqueued_at: string | null;
  };
  quality: {
    bulk_rows: number;
    publishable_rows: number;
    publishable_pct: number;
    confidence_counts: Record<string, number>;
  };
  throughput: {
    last_hour_completed: number;
    last_6h_completed: number;
    last_24h_completed: number;
    last_day_completed: number;
    eta_days: number | null;
    eta_at: string | null;
    hourly_window: { label: string; done_count: number; avg_cost_usd: number }[];
  };
  today_spend_usd: number;
  daily_budget_usd: number;
  last_hour_completed: number;
  readiness: {
    schema_ready: boolean;
    search_ready: boolean;
    issues: string[];
    tables: Record<string, boolean>;
    env: Record<string, boolean>;
    counts: {
      bulk_rows: number;
      publishable_rows: number;
      embedding_rows: number;
      query_cache_rows: number;
    };
    worker: {
      state: string | null;
      last_heartbeat: string | null;
      heartbeat_age_s: number | null;
      is_stale: boolean;
      note: string | null;
    };
  };
  recent_done: {
    enterprise_number: string;
    finished_at: string | null;
    priority: number;
  }[];
};

type DeadRow = {
  enterprise_number: string;
  status: string;
  attempts: number;
  claimed_at: string | null;
  finished_at: string | null;
  last_error: string | null;
};

type SkiplistRow = {
  id: number;
  pattern: string;
  kind: string;
  reason: string | null;
  added_at: string;
  added_by: string | null;
};

function readPassword(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(PW_KEY);
  } catch {
    return null;
  }
}

function writePassword(pw: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (pw === null) window.localStorage.removeItem(PW_KEY);
    else window.localStorage.setItem(PW_KEY, pw);
  } catch {
    /* no-op */
  }
}

function promptPassword(): string | null {
  if (typeof window === "undefined") return null;
  const entered = window.prompt("Enrichment admin password", "");
  if (!entered) return null;
  writePassword(entered);
  return entered;
}

async function pwFetch<T>(path: string, options?: RequestInit): Promise<T> {
  let pw = readPassword() || promptPassword();
  if (!pw) throw new Error("Password required");

  const doFetch = async (password: string) =>
    fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Enrichment-Password": password,
        ...(options?.headers || {}),
      },
    });

  let res = await doFetch(pw);
  if (res.status === 401) {
    writePassword(null);
    pw = promptPassword();
    if (!pw) throw new Error("Password required");
    res = await doFetch(pw);
  }
  if (res.status === 503) {
    throw new Error("ENRICHMENT_ADMIN_PASSWORD not set on the server");
  }
  if (res.status === 401) throw new Error("Wrong password");
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

function formatNumber(value: number): string {
  return value.toLocaleString();
}

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

function formatCurrency(value: number, digits = 2): string {
  return `$${value.toFixed(digits)}`;
}

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("nl-BE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatEtaDays(days: number | null): string {
  if (days === null) return "Nog te weinig tempo-data";
  if (days < 1) {
    const hours = Math.max(1, Math.round(days * 24));
    return `ongeveer ${hours}u`;
  }
  return `ongeveer ${days.toFixed(1)} dagen`;
}

function toneForConfidence(bucket: string): string {
  if (bucket === "high") return "bg-emerald-500";
  if (bucket === "medium") return "bg-amber-500";
  if (bucket === "low") return "bg-orange-500";
  if (bucket === "insufficient_information") return "bg-slate-400";
  return "bg-slate-300";
}

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  accent = "text-slate-900",
}: {
  label: string;
  value: string;
  hint: string;
  icon: typeof Gauge;
  accent?: string;
}) {
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              {label}
            </div>
            <div className={`mt-2 text-3xl font-semibold tracking-tight ${accent}`}>
              {value}
            </div>
            <div className="mt-1 text-sm text-slate-500">{hint}</div>
          </div>
          <div className="rounded-2xl bg-slate-100 p-3 text-slate-700">
            <Icon className="size-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function Meter({
  label,
  value,
  toneClass,
}: {
  label: string;
  value: number;
  toneClass: string;
}) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-600">{label}</span>
        <span className="font-medium text-slate-900">{formatPercent(pct)}</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${toneClass}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function EnrichmentDashboard({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [dead, setDead] = useState<DeadRow[]>([]);
  const [skiplist, setSkiplist] = useState<SkiplistRow[]>([]);
  const [newPattern, setNewPattern] = useState("");
  const [newKind, setNewKind] = useState("domain");
  const [budgetInput, setBudgetInput] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setErr(null);
    setLoading(true);
    try {
      const [ov, dd, sl] = await Promise.all([
        pwFetch<Overview>("/api/admin/enrichment/overview"),
        pwFetch<{ items: DeadRow[] }>("/api/admin/enrichment/dead?limit=50"),
        pwFetch<{ items: SkiplistRow[] }>("/api/admin/enrichment/skiplist"),
      ]);
      setOverview(ov);
      setDead(dd.items || []);
      setSkiplist(sl.items || []);
      setBudgetInput(ov.daily_budget_usd.toString());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 15_000);
    return () => clearInterval(t);
  }, [refresh]);

  const forgetPassword = () => {
    writePassword(null);
    window.location.reload();
  };

  const toggleEnabled = async () => {
    if (!overview) return;
    const endpoint = overview.enabled ? "pause" : "resume";
    await pwFetch(`/api/admin/enrichment/${endpoint}`, {
      method: "POST",
      body: overview.enabled ? JSON.stringify({ reason: "admin toggle" }) : undefined,
    });
    void refresh();
  };

  const submitBudget = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = Number(budgetInput);
    if (Number.isNaN(parsed) || parsed < 0) return;
    await pwFetch("/api/admin/enrichment/budget", {
      method: "POST",
      body: JSON.stringify({ daily_budget_usd: parsed }),
    });
    void refresh();
  };

  const retryScope = async (scope: "failed" | "dead") => {
    await pwFetch("/api/admin/enrichment/retry", {
      method: "POST",
      body: JSON.stringify({ scope }),
    });
    void refresh();
  };

  const addSkip = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPattern.trim()) return;
    await pwFetch("/api/admin/enrichment/skiplist", {
      method: "POST",
      body: JSON.stringify({ pattern: newPattern.trim(), kind: newKind }),
    });
    setNewPattern("");
    void refresh();
  };

  const removeSkip = async (id: number) => {
    await pwFetch(`/api/admin/enrichment/skiplist/${id}`, {
      method: "DELETE",
    });
    void refresh();
  };

  const qualityRows = useMemo(() => {
    if (!overview) return [];
    const total = Math.max(overview.quality.bulk_rows, 1);
    return Object.entries(overview.quality.confidence_counts)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([bucket, count]) => ({
        bucket,
        count,
        pct: (count / total) * 100,
      }));
  }, [overview]);

  const spendPct = overview
    ? Math.min(100, (overview.today_spend_usd / Math.max(overview.daily_budget_usd, 0.01)) * 100)
    : 0;

  const inner = (
    <div className="space-y-6">
      <div className="border-b border-slate-200 px-6 py-6 sm:px-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">
              <Rocket className="size-3.5" />
              Semantic Enrichment
            </div>
            <div>
              <h1 className={`${embedded ? "text-2xl" : "text-3xl"} font-semibold tracking-tight text-slate-900`}>
                Eén cockpit voor voortgang, kwaliteit en worker health
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                Dit scherm toont hoeveel bedrijven al semantisch verrijkt zijn,
                hoeveel backlog nog wacht, hoe sterk de output is en of de serverworker gezond blijft draaien.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {!embedded && (
              <Link href="/admin" className="text-sm font-medium text-slate-500 hover:text-slate-900">
                ← Terug naar admin
              </Link>
            )}
            <Button variant="ghost" size="sm" onClick={forgetPassword}>
              Forget password
            </Button>
            <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
              {loading ? <Loader2 className="mr-2 size-4 animate-spin" /> : <RefreshCw className="mr-2 size-4" />}
              Refresh
            </Button>
          </div>
        </div>
      </div>

      <div className="space-y-6 px-6 pb-6 sm:px-8">
        {err && (
          <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Error: {err}
          </div>
        )}

        {!overview ? (
          <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-600">
            <Loader2 className="size-4 animate-spin" />
            Dashboard wordt geladen…
          </div>
        ) : (
          <>
            <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
              <Card className="overflow-hidden border-0 bg-[linear-gradient(135deg,#0f172a_0%,#1d4ed8_52%,#38bdf8_100%)] text-white shadow-[0_25px_80px_-45px_rgba(30,64,175,0.9)]">
                <CardContent className="p-6 sm:p-7">
                  <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
                    <div className="space-y-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge className="border-white/15 bg-white/10 text-white hover:bg-white/10">
                          {overview.enabled ? "Worker running" : "Worker paused"}
                        </Badge>
                        <Badge className="border-white/15 bg-white/10 text-white hover:bg-white/10">
                          {overview.readiness.search_ready ? "Search ready" : "Search not ready"}
                        </Badge>
                        {overview.readiness.worker.is_stale && (
                          <Badge variant="destructive">Heartbeat stale</Badge>
                        )}
                      </div>
                      <div>
                        <div className="text-sm text-sky-100">Totale voortgang</div>
                        <div className="mt-1 text-5xl font-semibold tracking-tight">
                          {formatPercent(overview.progress.completion_pct)}
                        </div>
                        <div className="mt-2 text-sm text-sky-100/90">
                          {formatNumber(overview.progress.completed_jobs)} van{" "}
                          {formatNumber(overview.progress.total_jobs)} targetjobs afgerond of afgevoerd
                          {overview.progress.excluded_jobs > 0
                            ? ` • ${formatNumber(overview.progress.excluded_jobs)} expliciet uitgesloten`
                            : ""}
                        </div>
                      </div>
                      <Meter
                        label="Backlog afgewerkt"
                        value={overview.progress.completion_pct}
                        toneClass="bg-white"
                      />
                    </div>

                    <div className="grid min-w-[240px] gap-3 rounded-3xl border border-white/15 bg-white/10 p-4 backdrop-blur">
                      <div>
                        <div className="text-xs uppercase tracking-[0.18em] text-sky-100">ETA</div>
                        <div className="mt-1 text-xl font-semibold">
                          {formatEtaDays(overview.throughput.eta_days)}
                        </div>
                        <div className="text-xs text-sky-100/85">
                          {overview.throughput.eta_at
                            ? `bij huidig tempo klaar rond ${formatDateTime(overview.throughput.eta_at)}`
                            : "ETA verschijnt zodra er genoeg throughput-data is"}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs uppercase tracking-[0.18em] text-sky-100">Laatste heartbeat</div>
                        <div className="mt-1 text-sm font-medium">
                          {overview.readiness.worker.heartbeat_age_s !== null
                            ? `${overview.readiness.worker.heartbeat_age_s}s geleden`
                            : "geen heartbeat"}
                        </div>
                        <div className="text-xs text-sky-100/85">
                          {overview.readiness.worker.note || "Geen worker note beschikbaar"}
                        </div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-slate-200 bg-slate-900 text-white shadow-sm">
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                        Quality Gate
                      </div>
                      <div className="mt-2 text-3xl font-semibold">
                        {formatPercent(overview.quality.publishable_pct)}
                      </div>
                      <div className="mt-1 text-sm text-slate-300">
                        publishable output (`high` + `medium`)
                      </div>
                    </div>
                    <ShieldCheck className="size-8 text-emerald-300" />
                  </div>
                  <div className="mt-5 space-y-3">
                    <Meter
                      label="Publishable share"
                      value={overview.quality.publishable_pct}
                      toneClass="bg-emerald-400"
                    />
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div className="rounded-2xl bg-white/5 p-3">
                        <div className="text-slate-400">Bulk rows</div>
                        <div className="mt-1 text-xl font-semibold">{formatNumber(overview.quality.bulk_rows)}</div>
                      </div>
                      <div className="rounded-2xl bg-white/5 p-3">
                        <div className="text-slate-400">Publishable</div>
                        <div className="mt-1 text-xl font-semibold">{formatNumber(overview.quality.publishable_rows)}</div>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
              <StatCard
                label="Queue Remaining"
                value={formatNumber(overview.progress.queued_jobs)}
                hint={`${formatNumber(overview.progress.claimed_jobs)} nu in verwerking`}
                icon={Database}
              />
              <StatCard
                label="Completed 24h"
                value={formatNumber(overview.throughput.last_24h_completed)}
                hint={`${formatNumber(overview.throughput.last_hour_completed)} in het laatste uur`}
                icon={Gauge}
                accent="text-sky-700"
              />
              <StatCard
                label="Excluded"
                value={formatNumber(overview.progress.excluded_jobs)}
                hint="bewust buiten semantic corpus"
                icon={AlertTriangle}
                accent="text-amber-700"
              />
              <StatCard
                label="Spend Today"
                value={formatCurrency(overview.today_spend_usd, 3)}
                hint={`budget ${formatCurrency(overview.daily_budget_usd)}`}
                icon={Wallet}
                accent="text-emerald-700"
              />
              <StatCard
                label="Embeddings Ready"
                value={formatNumber(overview.readiness.counts.embedding_rows)}
                hint={`${formatNumber(overview.readiness.counts.query_cache_rows)} query-cache rows`}
                icon={Rocket}
                accent="text-violet-700"
              />
            </div>

            <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
              <Card className="border-slate-200 shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-lg font-semibold text-slate-900">Run status</div>
                      <div className="text-sm text-slate-500">
                        Live zicht op worker, budget en operationele gezondheid.
                      </div>
                    </div>
                    <Button size="sm" onClick={toggleEnabled}>
                      {overview.enabled ? "Pause worker" : "Resume worker"}
                    </Button>
                  </div>

                  <div className="mt-5 grid gap-4 md:grid-cols-2">
                    <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
                      <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                        {overview.readiness.worker.is_stale ? (
                          <AlertTriangle className="size-4 text-amber-600" />
                        ) : (
                          <CheckCircle2 className="size-4 text-emerald-600" />
                        )}
                        Worker health
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Badge variant={overview.enabled ? "default" : "secondary"}>
                          {overview.enabled ? "running" : "paused"}
                        </Badge>
                        <Badge variant={overview.readiness.schema_ready ? "default" : "secondary"}>
                          {overview.readiness.schema_ready ? "schema ready" : "schema issue"}
                        </Badge>
                        <Badge variant={overview.readiness.search_ready ? "default" : "secondary"}>
                          {overview.readiness.search_ready ? "index ready" : "index not ready"}
                        </Badge>
                      </div>
                      <div className="mt-3 text-sm text-slate-600">
                        State: <span className="font-medium text-slate-900">{overview.readiness.worker.state || "unknown"}</span>
                      </div>
                      <div className="mt-1 text-sm text-slate-600">
                        Heartbeat:{" "}
                        <span className="font-medium text-slate-900">
                          {overview.readiness.worker.heartbeat_age_s !== null
                            ? `${overview.readiness.worker.heartbeat_age_s}s geleden`
                            : "niet gezien"}
                        </span>
                      </div>
                      <div className="mt-3 rounded-2xl bg-white p-3 text-sm text-slate-600">
                        {overview.readiness.worker.note || "Geen recente worker note"}
                      </div>
                    </div>

                    <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
                      <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                        <Wallet className="size-4 text-emerald-600" />
                        Budget control
                      </div>
                      <div className="mt-3 text-3xl font-semibold text-slate-900">
                        {formatPercent(spendPct)}
                      </div>
                      <div className="mt-1 text-sm text-slate-600">
                        {formatCurrency(overview.today_spend_usd, 3)} van {formatCurrency(overview.daily_budget_usd)}
                      </div>
                      <div className="mt-4">
                        <Meter label="Budget used" value={spendPct} toneClass="bg-emerald-500" />
                      </div>
                      <form onSubmit={submitBudget} className="mt-4 flex items-center gap-2">
                        <Input
                          type="number"
                          step="0.01"
                          min={0}
                          value={budgetInput}
                          onChange={(e) => setBudgetInput(e.target.value)}
                          className="h-10 w-32"
                        />
                        <Button size="sm" type="submit" variant="outline">
                          Update budget
                        </Button>
                      </form>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-slate-200 shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-lg font-semibold text-slate-900">Confidence mix</div>
                      <div className="text-sm text-slate-500">
                        Hoeveel output vandaag frontend-waardig lijkt.
                      </div>
                    </div>
                    <ShieldCheck className="size-5 text-slate-400" />
                  </div>
                  <div className="mt-5 space-y-4">
                    {qualityRows.map((row) => (
                      <div key={row.bucket} className="space-y-1.5">
                        <div className="flex items-center justify-between text-sm">
                          <div className="flex items-center gap-2">
                            <span className={`size-2.5 rounded-full ${toneForConfidence(row.bucket)}`} />
                            <span className="text-slate-700">{row.bucket}</span>
                          </div>
                          <span className="font-medium text-slate-900">
                            {formatNumber(row.count)} · {formatPercent(row.pct)}
                          </span>
                        </div>
                        <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                          <div
                            className={`h-full rounded-full ${toneForConfidence(row.bucket)}`}
                            style={{ width: `${Math.max(2, row.pct)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
              <Card className="border-slate-200 shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-lg font-semibold text-slate-900">Queue snapshot</div>
                      <div className="text-sm text-slate-500">
                        Waar de backlog nu effectief zit.
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => void retryScope("failed")}>
                        Requeue failed
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => void retryScope("dead")}>
                        Requeue dead
                      </Button>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    {Object.entries(overview.queue_counts).map(([status, n]) => (
                      <div key={status} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                        <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{status}</div>
                        <div className="mt-2 text-2xl font-semibold text-slate-900">{formatNumber(n)}</div>
                      </div>
                    ))}
                  </div>

                  {overview.readiness.issues.length > 0 && (
                    <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4">
                      <div className="flex items-center gap-2 text-sm font-medium text-amber-900">
                        <AlertTriangle className="size-4" />
                        Issues die aandacht vragen
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {overview.readiness.issues.map((issue) => (
                          <Badge key={issue} variant="outline" className="border-amber-300 bg-white font-mono text-[11px] text-amber-900">
                            {issue}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card className="border-slate-200 shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-lg font-semibold text-slate-900">24h throughput</div>
                      <div className="text-sm text-slate-500">
                        Laatste 24 uur, per uur gegroepeerd.
                      </div>
                    </div>
                    <Clock3 className="size-5 text-slate-400" />
                  </div>

                  <div className="mt-5 space-y-3">
                    {overview.throughput.hourly_window.slice(-8).map((row) => {
                      const maxDone = Math.max(
                        1,
                        ...overview.throughput.hourly_window.map((item) => item.done_count),
                      );
                      const width = (row.done_count / maxDone) * 100;
                      return (
                        <div key={row.label} className="grid grid-cols-[88px_1fr_70px] items-center gap-3">
                          <div className="text-xs font-medium text-slate-500">
                            {row.label.slice(11)}
                          </div>
                          <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                            <div className="h-full rounded-full bg-sky-500" style={{ width: `${Math.max(width, row.done_count > 0 ? 6 : 0)}%` }} />
                          </div>
                          <div className="text-right text-sm font-medium text-slate-900">
                            {row.done_count}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-3">
                    <div className="rounded-2xl bg-slate-50 p-3">
                      <div className="text-xs uppercase tracking-[0.16em] text-slate-500">6h</div>
                      <div className="mt-1 text-xl font-semibold text-slate-900">
                        {formatNumber(overview.throughput.last_6h_completed)}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-slate-50 p-3">
                      <div className="text-xs uppercase tracking-[0.16em] text-slate-500">24h</div>
                      <div className="mt-1 text-xl font-semibold text-slate-900">
                        {formatNumber(overview.throughput.last_24h_completed)}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
              <Card className="border-slate-200 shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-lg font-semibold text-slate-900">Recent failures</div>
                      <div className="text-sm text-slate-500">
                        Alleen de jobs die geblokkeerd zijn of herhaaldelijk mislopen.
                      </div>
                    </div>
                    <AlertTriangle className="size-5 text-slate-400" />
                  </div>
                  <div className="mt-4 overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>CBE</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Attempts</TableHead>
                          <TableHead>Moment</TableHead>
                          <TableHead>Error</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {dead.map((r) => (
                          <TableRow key={r.enterprise_number}>
                            <TableCell className="font-mono text-xs">{r.enterprise_number}</TableCell>
                            <TableCell>
                              <Badge variant={r.status === "dead" ? "destructive" : "secondary"}>
                                {r.status}
                              </Badge>
                            </TableCell>
                            <TableCell>{r.attempts}</TableCell>
                            <TableCell className="text-xs">
                              {formatDateTime(r.finished_at || r.claimed_at)}
                            </TableCell>
                            <TableCell className="max-w-[260px] truncate text-xs" title={r.last_error || ""}>
                              {r.last_error || "—"}
                            </TableCell>
                          </TableRow>
                        ))}
                        {dead.length === 0 && (
                          <TableRow>
                            <TableCell colSpan={5} className="text-center text-sm text-slate-500">
                              Geen recente failures.
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-slate-200 shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-lg font-semibold text-slate-900">Recently completed</div>
                      <div className="text-sm text-slate-500">
                        Handig om steekproeven rechtstreeks te openen.
                      </div>
                    </div>
                    <CheckCircle2 className="size-5 text-slate-400" />
                  </div>
                  <div className="mt-4 overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>CBE</TableHead>
                          <TableHead>Priority</TableHead>
                          <TableHead>Finished</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {overview.recent_done.map((r) => (
                          <TableRow key={r.enterprise_number}>
                            <TableCell className="font-mono text-xs">
                              <Link href={`/company/${r.enterprise_number}`} className="hover:underline">
                                {r.enterprise_number}
                              </Link>
                            </TableCell>
                            <TableCell>{r.priority}</TableCell>
                            <TableCell className="text-xs">{formatDateTime(r.finished_at)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            </div>

            <Card className="border-slate-200 shadow-sm">
              <CardContent className="p-5">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="text-lg font-semibold text-slate-900">Aggregator skip-list</div>
                    <div className="text-sm text-slate-500">
                      Bronpatronen die de worker bewust links laat liggen.
                    </div>
                  </div>
                  <Database className="size-5 text-slate-400" />
                </div>
                <form onSubmit={addSkip} className="mt-4 flex flex-col gap-2 sm:flex-row">
                  <Input
                    placeholder="bv. companyweb.be of /bedrijvengids/"
                    value={newPattern}
                    onChange={(e) => setNewPattern(e.target.value)}
                    className="h-10"
                  />
                  <select
                    value={newKind}
                    onChange={(e) => setNewKind(e.target.value)}
                    className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm"
                  >
                    <option value="domain">domain</option>
                    <option value="path">path</option>
                  </select>
                  <Button type="submit" size="sm">Add pattern</Button>
                </form>

                <div className="mt-4 overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Pattern</TableHead>
                        <TableHead>Kind</TableHead>
                        <TableHead>Reason</TableHead>
                        <TableHead>Added</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {skiplist.map((r) => (
                        <TableRow key={r.id}>
                          <TableCell className="font-mono text-xs">{r.pattern}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{r.kind}</Badge>
                          </TableCell>
                          <TableCell className="text-xs">{r.reason || "—"}</TableCell>
                          <TableCell className="text-xs">{formatDateTime(r.added_at)}</TableCell>
                          <TableCell className="text-right">
                            <Button size="sm" variant="ghost" onClick={() => void removeSkip(r.id)}>
                              Remove
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );

  if (embedded) {
    return <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">{inner}</div>;
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.10),_transparent_28%),linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)]">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="rounded-[28px] border border-white/70 bg-white/90 shadow-[0_20px_80px_-40px_rgba(15,23,42,0.35)] backdrop-blur">
          {inner}
        </div>
      </div>
    </div>
  );
}
