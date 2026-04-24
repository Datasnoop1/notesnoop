"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, AlertCircle, Loader2 } from "lucide-react";

/* #17 Public status page. Pings the backend health endpoint and renders
 * a Statuspage-style summary. No auth required.
 */

type Status = "up" | "degraded" | "down" | "unknown";

interface ServiceCheck {
  name: string;
  description: string;
  status: Status;
  detail: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

async function checkBackend(): Promise<ServiceCheck> {
  const started = Date.now();
  try {
    const res = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
    const ms = Date.now() - started;
    if (!res.ok) {
      return { name: "API", description: "DataSnoop backend", status: "down", detail: `HTTP ${res.status}` };
    }
    const body = await res.json();
    if (body?.status === "ok") {
      const s: Status = ms < 400 ? "up" : "degraded";
      return { name: "API", description: "DataSnoop backend", status: s, detail: `${ms} ms` };
    }
    return { name: "API", description: "DataSnoop backend", status: "degraded", detail: "Unexpected payload" };
  } catch (err) {
    return {
      name: "API",
      description: "DataSnoop backend",
      status: "down",
      detail: err instanceof Error ? err.message : "Unreachable",
    };
  }
}

async function checkFrontend(): Promise<ServiceCheck> {
  // If this page is rendering, the frontend is serving. The "check" is
  // just a sanity round-trip to a static asset.
  const started = Date.now();
  try {
    const res = await fetch("/favicon.ico", { cache: "no-store" });
    const ms = Date.now() - started;
    if (!res.ok) {
      return { name: "Frontend", description: "Next.js app", status: "degraded", detail: `HTTP ${res.status}` };
    }
    return { name: "Frontend", description: "Next.js app", status: "up", detail: `${ms} ms` };
  } catch {
    return { name: "Frontend", description: "Next.js app", status: "unknown", detail: "Offline?" };
  }
}

async function checkDatabase(): Promise<ServiceCheck> {
  // The backend's /api/site-config does a lightweight DB read, so it's a
  // good proxy for Postgres health without exposing a new endpoint.
  const started = Date.now();
  try {
    const res = await fetch(`${API_BASE}/api/site-config`, { cache: "no-store" });
    const ms = Date.now() - started;
    if (!res.ok) {
      return { name: "Database", description: "Postgres + read path", status: "down", detail: `HTTP ${res.status}` };
    }
    return { name: "Database", description: "Postgres + read path", status: ms < 800 ? "up" : "degraded", detail: `${ms} ms` };
  } catch (err) {
    return {
      name: "Database",
      description: "Postgres + read path",
      status: "down",
      detail: err instanceof Error ? err.message : "Unreachable",
    };
  }
}

function StatusDot({ status }: { status: Status }) {
  const color =
    status === "up"
      ? "bg-emerald-500"
      : status === "degraded"
        ? "bg-amber-400"
        : status === "down"
          ? "bg-rose-500"
          : "bg-slate-300";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

function StatusBadge({ status }: { status: Status }) {
  if (status === "up") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
        <CheckCircle2 className="h-3.5 w-3.5" /> Operational
      </span>
    );
  }
  if (status === "degraded") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700">
        <AlertCircle className="h-3.5 w-3.5" /> Degraded
      </span>
    );
  }
  if (status === "down") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-rose-700">
        <AlertCircle className="h-3.5 w-3.5" /> Down
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500">
      <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking
    </span>
  );
}

export default function StatusPage() {
  const [checks, setChecks] = useState<ServiceCheck[]>([
    { name: "Frontend", description: "Next.js app", status: "unknown", detail: "Checking..." },
    { name: "API", description: "DataSnoop backend", status: "unknown", detail: "Checking..." },
    { name: "Database", description: "Postgres + read path", status: "unknown", detail: "Checking..." },
  ]);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const runChecks = async () => {
    setRefreshing(true);
    const results = await Promise.all([checkFrontend(), checkBackend(), checkDatabase()]);
    setChecks(results);
    setLastChecked(new Date());
    setRefreshing(false);
  };

  useEffect(() => {
    runChecks();
    const t = setInterval(runChecks, 60_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const overall: Status = (() => {
    if (checks.some((c) => c.status === "down")) return "down";
    if (checks.some((c) => c.status === "degraded")) return "degraded";
    if (checks.every((c) => c.status === "up")) return "up";
    return "unknown";
  })();

  return (
    <div className="mx-auto w-full max-w-[780px] px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">System status</h1>
        <button
          type="button"
          onClick={runChecks}
          disabled={refreshing}
          className="inline-flex items-center gap-1 text-xs text-slate-500 border border-slate-200 hover:border-indigo-300 hover:text-indigo-600 px-2.5 py-1 rounded-md"
        >
          {refreshing ? <Loader2 className="h-3 w-3 animate-spin" /> : "\u21bb"} Refresh
        </button>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 mb-4">
        <div className="flex items-center gap-3">
          <StatusDot status={overall} />
          <div>
            <div className="text-base font-semibold text-slate-900">
              {overall === "up"
                ? "All systems operational"
                : overall === "degraded"
                  ? "Some systems degraded"
                  : overall === "down"
                    ? "Incident in progress"
                    : "Running checks"}
            </div>
            {lastChecked && (
              <div className="text-[11px] text-slate-400 mt-0.5">
                Last checked: {lastChecked.toLocaleString()}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        {checks.map((c) => (
          <div
            key={c.name}
            className="flex items-center justify-between px-5 py-3 border-b border-slate-50 last:border-0"
          >
            <div className="min-w-0">
              <div className="text-sm font-semibold text-slate-800 flex items-center gap-2">
                <StatusDot status={c.status} />
                {c.name}
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5">{c.description} · {c.detail}</div>
            </div>
            <StatusBadge status={c.status} />
          </div>
        ))}
      </div>

      <p className="mt-6 text-center text-[11px] text-slate-400">
        Checks auto-refresh every 60 s.
        {" "}<Link href="/" className="hover:text-indigo-600">Back to DataSnoop</Link>
      </p>
    </div>
  );
}
