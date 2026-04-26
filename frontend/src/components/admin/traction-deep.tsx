"use client";

/**
 * Traction-deep — extended traction analytics: KPIs, daily trend,
 * sessions, cohort retention, hourly heatmap, top pages, device /
 * browser / country mix, dormant accounts. All driven from
 * /api/admin/analytics + /api/admin/sessions/breakdown +
 * /api/admin/sessions/paths.
 */

import { Fragment, useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface AnalyticsKpi {
  visitors_1d: number;
  visitors_7d: number;
  visitors_30d: number;
  sessions_1d: number;
  sessions_7d: number;
  sessions_30d: number;
  registered_1d: number;
  registered_7d: number;
  registered_30d: number;
  reqs_1d: number;
  reqs_7d: number;
  reqs_30d: number;
}

interface AnalyticsResp {
  kpi: AnalyticsKpi;
  daily: { day: string; visitors: number; registered: number; sessions: number; reqs: number }[];
  hourly: { hour: number; dow: number; reqs: number }[];
  top_pages: { endpoint: string; hits: number; visitors: number }[];
  session: {
    sessions: number;
    avg_duration_s: number | null;
    pages_per_session: string | number | null;
    bounces: number;
    bounce_rate_pct: number | null;
  } | null;
  cohorts: { cohort: string; weeks_since: number; users: number }[];
  signups: { day: string; signups: number }[];
  top_registered: { user_email: string; reqs: number; pages: number; last_seen: string }[];
  top_guests: { anon_id: string; reqs: number; pages: number; last_seen: string }[];
  dormant: { email: string; created_at: string; last_active: string | null }[];
  failures: unknown[];
}

interface BreakdownResp {
  device: { device: string; sessions: number; reqs: number }[];
  browser: { browser: string; sessions: number; reqs: number }[];
  country: { country: string; sessions: number; reqs: number }[];
}

interface PathsResp {
  transitions: { prev: string; next: string; n: number }[];
}

interface Props {
  fetcher: <T>(url: string, init?: RequestInit) => Promise<T>;
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

function fmtDuration(s: number | null): string {
  if (s == null || isNaN(s)) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="overflow-hidden">
      <CardContent className="p-3">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide">{label}</div>
        <div className="text-xl font-semibold tabular-nums mt-0.5">{value}</div>
        {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

const DOW_LABEL = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function TractionDeep({ fetcher }: Props) {
  const [a, setA] = useState<AnalyticsResp | null>(null);
  const [bd, setBd] = useState<BreakdownResp | null>(null);
  const [paths, setPaths] = useState<PathsResp | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [aResp, bResp, pResp] = await Promise.all([
          fetcher<AnalyticsResp>("/api/admin/analytics").catch(() => null),
          fetcher<BreakdownResp>("/api/admin/sessions/breakdown").catch(() => null),
          fetcher<PathsResp>("/api/admin/sessions/paths").catch(() => null),
        ]);
        if (cancelled) return;
        setA(aResp);
        setBd(bResp);
        setPaths(pResp);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetcher]);

  if (loading) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 animate-pulse" />
          ))}
        </div>
        <Skeleton className="h-64 animate-pulse" />
      </div>
    );
  }

  if (!a) {
    return (
      <div className="text-sm text-muted-foreground">
        Could not load analytics.
      </div>
    );
  }

  // Build a 7×24 heatmap matrix from the hourly rows.
  const hourGrid: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0));
  for (const row of a.hourly || []) {
    if (row.dow >= 0 && row.dow < 7 && row.hour >= 0 && row.hour < 24) {
      hourGrid[row.dow][row.hour] = row.reqs;
    }
  }
  const hourMax = Math.max(1, ...hourGrid.flat());

  // Cohort matrix: pivot { cohort, weeks_since, users } into a {cohort}×{week}
  // table where week 0 is the cohort size.
  const cohortMap = new Map<string, Map<number, number>>();
  for (const c of a.cohorts || []) {
    if (!cohortMap.has(c.cohort)) cohortMap.set(c.cohort, new Map());
    cohortMap.get(c.cohort)!.set(c.weeks_since, c.users);
  }
  const cohortRows = Array.from(cohortMap.entries())
    .sort(([a1], [b1]) => a1.localeCompare(b1))
    .slice(-8); // last 8 weekly cohorts

  return (
    <div className="space-y-4">
      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Visitors 24h" value={fmtNum(a.kpi.visitors_1d)} sub={`${fmtNum(a.kpi.visitors_7d)} 7d · ${fmtNum(a.kpi.visitors_30d)} 30d`} />
        <Kpi label="Sessions 24h" value={fmtNum(a.kpi.sessions_1d)} sub={`${fmtNum(a.kpi.sessions_7d)} 7d · ${fmtNum(a.kpi.sessions_30d)} 30d`} />
        <Kpi label="Registered 24h" value={fmtNum(a.kpi.registered_1d)} sub={`${fmtNum(a.kpi.registered_7d)} 7d · ${fmtNum(a.kpi.registered_30d)} 30d`} />
        <Kpi label="Requests 24h" value={fmtNum(a.kpi.reqs_1d)} sub={`${fmtNum(a.kpi.reqs_7d)} 7d · ${fmtNum(a.kpi.reqs_30d)} 30d`} />
      </div>

      {/* Engagement KPIs from session block */}
      {a.session && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Kpi
            label="Avg session"
            value={fmtDuration(a.session.avg_duration_s)}
            sub={`${a.session.sessions} sessions / 7d`}
          />
          <Kpi
            label="Pages / session"
            value={String(a.session.pages_per_session ?? "—")}
          />
          <Kpi
            label="Bounce rate"
            value={a.session.bounce_rate_pct != null ? `${a.session.bounce_rate_pct}%` : "—"}
            sub={`${a.session.bounces} single-hit sessions`}
          />
          <Kpi
            label="New signups 30d"
            value={fmtNum((a.signups || []).reduce((acc, x) => acc + (x.signups || 0), 0))}
          />
        </div>
      )}

      {/* Daily trend */}
      <Card>
        <CardContent className="p-3">
          <div className="text-sm font-medium mb-2">Daily — visitors / sessions / registered</div>
          <div className="h-56">
            <ResponsiveContainer>
              <LineChart data={a.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.08)" />
                <XAxis dataKey="day" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Line type="monotone" dataKey="visitors" stroke="#0ea5e9" dot={false} />
                <Line type="monotone" dataKey="sessions" stroke="#10b981" dot={false} />
                <Line type="monotone" dataKey="registered" stroke="#a855f7" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Hourly heatmap */}
      <Card>
        <CardContent className="p-3">
          <div className="text-sm font-medium mb-2">When users visit (last 7 days, Europe/Brussels)</div>
          <div className="overflow-x-auto">
            <div className="inline-grid" style={{ gridTemplateColumns: `40px repeat(24, minmax(14px, 1fr))` }}>
              <div />
              {Array.from({ length: 24 }, (_, h) => (
                <div key={h} className="text-[9px] text-muted-foreground text-center">
                  {h % 3 === 0 ? h : ""}
                </div>
              ))}
              {hourGrid.map((row, dow) => (
                <Fragment key={`row-${dow}`}>
                  <div className="text-[10px] text-muted-foreground pr-1 self-center">
                    {DOW_LABEL[dow]}
                  </div>
                  {row.map((v, h) => {
                    const intensity = v / hourMax;
                    return (
                      <div
                        key={`${dow}-${h}`}
                        title={`${DOW_LABEL[dow]} ${h}:00 — ${v} reqs`}
                        className="aspect-square m-px rounded-sm"
                        style={{
                          backgroundColor: `rgba(14,165,233,${0.05 + intensity * 0.85})`,
                        }}
                      />
                    );
                  })}
                </Fragment>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Cohorts */}
      {cohortRows.length > 0 && (
        <Card>
          <CardContent className="p-3">
            <div className="text-sm font-medium mb-2">Weekly retention cohorts (registered users)</div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-muted-foreground">
                    <th className="text-left font-normal pr-2">Cohort</th>
                    <th className="text-right font-normal">Size</th>
                    {Array.from({ length: 7 }, (_, i) => (
                      <th key={i} className="text-right font-normal">
                        W{i + 1}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cohortRows.map(([cohort, weeks]) => {
                    const size = weeks.get(0) || 0;
                    return (
                      <tr key={cohort} className="border-t">
                        <td className="pr-2 py-1 font-mono">{cohort}</td>
                        <td className="text-right tabular-nums">{size}</td>
                        {Array.from({ length: 7 }, (_, i) => {
                          const u = weeks.get(i + 1) || 0;
                          const pct = size ? Math.round((100 * u) / size) : 0;
                          return (
                            <td
                              key={i}
                              className="text-right tabular-nums"
                              style={{
                                backgroundColor: pct
                                  ? `rgba(16,185,129,${0.08 + (pct / 100) * 0.5})`
                                  : undefined,
                              }}
                            >
                              {u ? `${u} (${pct}%)` : "—"}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Device / Browser / Country */}
      {bd && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <BreakdownCard title="Device (7d)" rows={bd.device.map(r => ({ k: r.device, n: r.sessions }))} />
          <BreakdownCard title="Browser (7d)" rows={bd.browser.map(r => ({ k: r.browser, n: r.sessions }))} />
          <BreakdownCard title="Country (7d)" rows={bd.country.map(r => ({ k: r.country, n: r.sessions }))} />
        </div>
      )}

      {/* Top pages */}
      <Card>
        <CardContent className="p-3">
          <div className="text-sm font-medium mb-2">Top pages (last 7 days)</div>
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={a.top_pages.slice(0, 10)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.08)" />
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis dataKey="endpoint" type="category" width={200} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="hits" fill="#0ea5e9" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Top user paths */}
      {paths && paths.transitions.length > 0 && (
        <Card>
          <CardContent className="p-3">
            <div className="text-sm font-medium mb-2">Most common navigation transitions</div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-muted-foreground">
                    <th className="text-left font-normal pr-2">From</th>
                    <th className="text-left font-normal pr-2">To</th>
                    <th className="text-right font-normal">N</th>
                  </tr>
                </thead>
                <tbody>
                  {paths.transitions.slice(0, 20).map((t, i) => (
                    <tr key={i} className="border-t">
                      <td className="font-mono pr-2 py-0.5 truncate max-w-[260px]">{t.prev}</td>
                      <td className="font-mono pr-2 py-0.5 truncate max-w-[260px]">{t.next}</td>
                      <td className="text-right tabular-nums">{t.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top users / dormant */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-3">
            <div className="text-sm font-medium mb-2">Top registered users (7d)</div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-muted-foreground">
                  <th className="text-left font-normal pr-2">User</th>
                  <th className="text-right font-normal">Reqs</th>
                  <th className="text-right font-normal">Pages</th>
                </tr>
              </thead>
              <tbody>
                {a.top_registered.slice(0, 10).map((u, i) => (
                  <tr key={i} className="border-t">
                    <td className="truncate max-w-[200px] pr-2 py-0.5">{u.user_email}</td>
                    <td className="text-right tabular-nums">{u.reqs}</td>
                    <td className="text-right tabular-nums">{u.pages}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-3">
            <div className="text-sm font-medium mb-2">Dormant accounts (no activity 30d)</div>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-muted-foreground">
                  <th className="text-left font-normal pr-2">Email</th>
                  <th className="text-left font-normal pr-2">Joined</th>
                  <th className="text-left font-normal">Last active</th>
                </tr>
              </thead>
              <tbody>
                {a.dormant.length === 0 && (
                  <tr><td colSpan={3} className="text-muted-foreground py-2">None — every registered user is active.</td></tr>
                )}
                {a.dormant.slice(0, 10).map((u, i) => (
                  <tr key={i} className="border-t">
                    <td className="truncate max-w-[200px] pr-2 py-0.5">{u.email}</td>
                    <td className="pr-2 py-0.5 text-muted-foreground">{u.created_at?.slice(0, 10)}</td>
                    <td className="text-muted-foreground">{u.last_active?.slice(0, 10) || "never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>

      <div className="text-[11px] text-muted-foreground">
        Analytics excludes admin traffic. Sessions track via the GDPR-compliant{" "}
        <code>ds_sid</code> cookie (random UUID, no PII) — see{" "}
        <code>docs/sessions.md</code>.
      </div>
    </div>
  );
}

function BreakdownCard({ title, rows }: { title: string; rows: { k: string; n: number }[] }) {
  const total = rows.reduce((s, r) => s + r.n, 0) || 1;
  return (
    <Card>
      <CardContent className="p-3">
        <div className="text-sm font-medium mb-2">{title}</div>
        <div className="space-y-1">
          {rows.slice(0, 8).map((r) => {
            const pct = Math.round((100 * r.n) / total);
            return (
              <div key={r.k} className="flex items-center gap-2 text-[11px]">
                <div className="w-20 truncate">{r.k}</div>
                <div className="flex-1 h-2 bg-muted rounded overflow-hidden">
                  <div className="h-full bg-sky-500" style={{ width: `${pct}%` }} />
                </div>
                <div className="tabular-nums w-14 text-right">
                  {fmtNum(r.n)} <Badge variant="outline" className="ml-1 text-[9px] h-3.5">{pct}%</Badge>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
