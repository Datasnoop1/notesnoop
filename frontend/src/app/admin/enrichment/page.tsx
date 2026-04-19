"use client";

/*
 * Bulk enrichment orchestrator — operator dashboard.
 *
 * Gated by a shared-secret password (not Supabase admin role). The
 * password prompt fires once on first load, the value lives in
 * localStorage under `enrichment_admin_pw`. A 401 from the backend
 * clears the stored value and re-prompts.
 *
 * Paired with `backend/routers/admin_enrichment.py`. See that module
 * for the header convention and the env var that holds the password.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
    /* private mode etc. — no-op */
  }
}

function promptPassword(): string | null {
  if (typeof window === "undefined") return null;
  const entered = window.prompt(
    "Enrichment admin password",
    "",
  );
  if (!entered) return null;
  writePassword(entered);
  return entered;
}

async function pwFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
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
    // Stored password is wrong — clear and re-prompt once.
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

type Overview = {
  enabled: boolean;
  queue_counts: Record<string, number>;
  today_spend_usd: number;
  daily_budget_usd: number;
  last_hour_completed: number;
  recent_done: { enterprise_number: string; finished_at: string | null; priority: number }[];
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

export default function EnrichmentAdminPage() {
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
    const t = setInterval(() => void refresh(), 10_000);
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

  const queueCount = (status: string): number =>
    overview?.queue_counts[status] ?? 0;

  return (
    <div className="mx-auto max-w-6xl p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Bulk enrichment</h1>
        <div className="flex items-center gap-3">
          <Link href="/admin" className="text-sm text-muted-foreground hover:underline">
            ← Back to admin
          </Link>
          <Button variant="ghost" size="sm" onClick={forgetPassword}>
            Forget password
          </Button>
          <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <div className="text-sm text-red-600">Error: {err}</div>}

      {!overview ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : (
        <>
          {/* ── Status + spend + rate ───────────────────── */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground">Worker status</div>
                <div className="mt-1 flex items-center gap-2">
                  <Badge variant={overview.enabled ? "default" : "secondary"}>
                    {overview.enabled ? "running" : "paused"}
                  </Badge>
                  <Button size="sm" onClick={toggleEnabled}>
                    {overview.enabled ? "Pause" : "Resume"}
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground">Spend today / budget</div>
                <div className="mt-1 text-lg font-medium">
                  ${overview.today_spend_usd.toFixed(3)}
                  <span className="text-sm text-muted-foreground">
                    {" "}/ ${overview.daily_budget_usd.toFixed(2)}
                  </span>
                </div>
                <form onSubmit={submitBudget} className="mt-2 flex items-center gap-2">
                  <Input
                    type="number"
                    step="0.01"
                    min={0}
                    value={budgetInput}
                    onChange={(e) => setBudgetInput(e.target.value)}
                    className="h-8 w-28"
                  />
                  <Button size="sm" type="submit" variant="outline">
                    Update
                  </Button>
                </form>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground">Completed last hour</div>
                <div className="mt-1 text-2xl font-semibold">
                  {overview.last_hour_completed}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground">Queue depth</div>
                <div className="mt-1 text-2xl font-semibold">
                  {queueCount("queued")}
                </div>
                <div className="text-xs text-muted-foreground">
                  claimed: {queueCount("claimed")} · done: {queueCount("done")}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* ── Queue counts by status ──────────────────── */}
          <Card>
            <CardContent className="p-4">
              <div className="mb-2 font-medium">Queue snapshot</div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Count</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(overview.queue_counts).map(([status, n]) => (
                    <TableRow key={status}>
                      <TableCell>{status}</TableCell>
                      <TableCell className="text-right">{n.toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                  {Object.keys(overview.queue_counts).length === 0 && (
                    <TableRow>
                      <TableCell colSpan={2} className="text-center text-muted-foreground">
                        No jobs in queue yet — seed via
                        <code className="ml-1 text-xs">scripts/seed_enrichment_queue.py</code>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
              <div className="mt-3 flex gap-2">
                <Button size="sm" variant="outline" onClick={() => void retryScope("failed")}>
                  Requeue failed
                </Button>
                <Button size="sm" variant="outline" onClick={() => void retryScope("dead")}>
                  Requeue dead
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* ── Dead-letter ─────────────────────────────── */}
          <Card>
            <CardContent className="p-4">
              <div className="mb-2 font-medium">Recent failures</div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>CBE</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Attempts</TableHead>
                    <TableHead>Finished</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dead.map((r) => (
                    <TableRow key={r.enterprise_number}>
                      <TableCell className="font-mono text-xs">
                        {r.enterprise_number}
                      </TableCell>
                      <TableCell>
                        <Badge variant={r.status === "dead" ? "destructive" : "secondary"}>
                          {r.status}
                        </Badge>
                      </TableCell>
                      <TableCell>{r.attempts}</TableCell>
                      <TableCell className="text-xs">
                        {r.finished_at || r.claimed_at || "—"}
                      </TableCell>
                      <TableCell className="max-w-[360px] truncate text-xs" title={r.last_error || ""}>
                        {r.last_error || ""}
                      </TableCell>
                    </TableRow>
                  ))}
                  {dead.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center text-muted-foreground">
                        Nothing failed recently.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* ── Aggregator skip-list ───────────────────── */}
          <Card>
            <CardContent className="p-4">
              <div className="mb-2 font-medium">Aggregator skip-list</div>
              <p className="mb-3 text-xs text-muted-foreground">
                URLs matching these patterns are rejected during discovery.
                Changes apply on the next worker discovery call (in-process
                5-minute cache).
              </p>
              <form onSubmit={addSkip} className="mb-4 flex gap-2">
                <Input
                  placeholder="e.g. companyweb.be or /bedrijvengids/"
                  value={newPattern}
                  onChange={(e) => setNewPattern(e.target.value)}
                  className="h-9"
                />
                <select
                  value={newKind}
                  onChange={(e) => setNewKind(e.target.value)}
                  className="h-9 rounded-md border px-2 text-sm"
                >
                  <option value="domain">domain</option>
                  <option value="path">path</option>
                </select>
                <Button type="submit" size="sm">Add</Button>
              </form>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Pattern</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>Added</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {skiplist.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="font-mono text-xs">{r.pattern}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{r.kind}</Badge>
                      </TableCell>
                      <TableCell className="text-xs">{r.reason || ""}</TableCell>
                      <TableCell className="text-xs">{r.added_at}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void removeSkip(r.id)}
                        >
                          Remove
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* ── Recent successes ───────────────────────── */}
          <Card>
            <CardContent className="p-4">
              <div className="mb-2 font-medium">Recently completed</div>
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
                      <TableCell className="text-xs">{r.finished_at || ""}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
