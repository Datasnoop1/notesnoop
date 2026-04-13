"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { createClient } from "@/lib/supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

/* ---------- Types ---------- */

interface AdminStats {
  total_enterprises: number;
  companies_with_financials: number;
  admin_records: number;
  financial_rows: number;
  activity_rows: number;
  total_users: number;
  admin_users: number;
  blocked_users: number;
  total_favourites: number;
  total_feedback: number;
  bug_count: number;
  suggestion_count: number;
  survey_count: number;
  db_size: string;
  target_enterprises: number;
  target_financial_rows: number;
  target_activity_rows: number;
  target_companies: number;
  daily_active_users: number;
  most_visited_page: string | null;
  companies_with_staatsblad: number;
  // Dataset coverage KPIs
  companies_with_latest_financials: number;
  companies_with_history: number;
  companies_with_publications: number;
  companies_with_admins: number;
  companies_with_shareholders: number;
  companies_with_subsidiaries: number;
  fully_loaded_companies: number;
}

interface UserRow {
  email: string;
  role: string;
  created_at: string;
  favourites_count: number;
  feedback_count: number;
}

interface FeedbackRow {
  id: number;
  type: string;
  page: string | null;
  description: string;
  user_email: string | null;
  created_at: string;
  reply: string | null;
  replied_at: string | null;
}

interface ActivitySummary {
  user_email: string;
  total_requests: number;
  unique_pages: number;
  last_active: string;
}

interface Poll {
  id: number;
  title: string;
  question: string;
  options: string[];
  status: string;
  created_at: string;
  archived_at: string | null;
  total_votes: number;
  votes: Record<string, number>;
}

/* ---------- API helper ---------- */

async function adminFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const supabase = createClient();
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not authenticated");

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });
  if (res.status === 403) throw new Error("Admin access required");
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

/* ---------- Small components ---------- */

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse bg-slate-200 rounded ${className}`} />
  );
}

function ProgressBar({
  value,
  target,
  colorCoded,
}: {
  value: number;
  target: number;
  colorCoded?: boolean;
}) {
  const pct = Math.min((value / target) * 100, 100);
  let barColor = "bg-indigo-600";
  if (colorCoded) {
    if (pct >= 80) barColor = "bg-emerald-500";
    else if (pct >= 40) barColor = "bg-amber-500";
    else barColor = "bg-red-500";
  }
  return (
    <div className="mt-2 h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
      <div
        className={`h-full rounded-full ${barColor} transition-all duration-500`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2 mb-4">
      {children}
    </h2>
  );
}

function fmt(n: number | undefined | null): string {
  if (n == null) return "--";
  return n.toLocaleString();
}

/* ---------- Main component ---------- */

export default function AdminPanel() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [feedback, setFeedback] = useState<FeedbackRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [myEmail, setMyEmail] = useState<string>("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [confirmClearFeedback, setConfirmClearFeedback] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [userSearch, setUserSearch] = useState("");
  const [activity, setActivity] = useState<ActivitySummary[]>([]);
  const [polls, setPolls] = useState<Poll[]>([]);
  const [pollTitle, setPollTitle] = useState("");
  const [pollQuestion, setPollQuestion] = useState("");
  const [pollOptions, setPollOptions] = useState("");
  const [pollCreating, setPollCreating] = useState(false);
  const [archivedExpanded, setArchivedExpanded] = useState(false);
  const [replyingTo, setReplyingTo] = useState<number | null>(null);
  const [replyText, setReplyText] = useState("");

  const loadData = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: sessionData } = await supabase.auth.getSession();
      setMyEmail(sessionData.session?.user?.email || "");

      const [s, u, f, a, p] = await Promise.all([
        adminFetch<AdminStats>("/api/admin/stats"),
        adminFetch<UserRow[]>("/api/admin/users"),
        adminFetch<FeedbackRow[]>("/api/admin/feedback"),
        adminFetch<ActivitySummary[]>("/api/admin/activity/summary").catch(() => [] as ActivitySummary[]),
        adminFetch<Poll[]>("/api/polls").catch(() => [] as Poll[]),
      ]);
      setStats(s);
      setUsers(u);
      setFeedback(f);
      setActivity(a);
      setPolls(p);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setError(message);
      if (message === "Not authenticated") router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  /* ---- User actions ---- */

  async function setRole(email: string, role: string) {
    setActionLoading(`role-${email}`);
    try {
      await adminFetch(`/api/admin/users/${encodeURIComponent(email)}/role`, {
        method: "POST",
        body: JSON.stringify({ role }),
      });
      setUsers((prev) =>
        prev.map((u) => (u.email === email ? { ...u, role } : u))
      );
    } catch {
      /* ignore */
    } finally {
      setActionLoading(null);
    }
  }

  async function deleteUser(email: string) {
    setActionLoading(`delete-${email}`);
    try {
      await adminFetch(`/api/admin/users/${encodeURIComponent(email)}`, {
        method: "DELETE",
      });
      setUsers((prev) => prev.filter((u) => u.email !== email));
      setConfirmDelete(null);
    } catch {
      /* ignore */
    } finally {
      setActionLoading(null);
    }
  }

  /* ---- Feedback actions ---- */

  async function deleteFeedback(id: number) {
    setActionLoading(`fb-${id}`);
    try {
      await adminFetch(`/api/admin/feedback/${id}`, { method: "DELETE" });
      setFeedback((prev) => prev.filter((f) => f.id !== id));
    } catch {
      /* ignore */
    } finally {
      setActionLoading(null);
    }
  }

  async function clearAllFeedback() {
    setActionLoading("clear-fb");
    try {
      await adminFetch("/api/admin/feedback", { method: "DELETE" });
      setFeedback([]);
      setConfirmClearFeedback(false);
    } catch {
      /* ignore */
    } finally {
      setActionLoading(null);
    }
  }

  /* ---- Reply actions ---- */

  async function replyToFeedback(id: number) {
    if (!replyText.trim()) return;
    setActionLoading(`reply-${id}`);
    try {
      await adminFetch(`/api/admin/feedback/${id}/reply`, {
        method: "POST",
        body: JSON.stringify({ message: replyText.trim() }),
      });
      setFeedback((prev) =>
        prev.map((f) =>
          f.id === id
            ? { ...f, reply: replyText.trim(), replied_at: new Date().toISOString() }
            : f
        )
      );
      setReplyingTo(null);
      setReplyText("");
    } catch {
      /* ignore */
    } finally {
      setActionLoading(null);
    }
  }

  /* ---- Poll actions ---- */

  async function createPoll() {
    const opts = pollOptions.split(",").map((o) => o.trim()).filter(Boolean);
    if (!pollTitle.trim() || !pollQuestion.trim() || opts.length < 2) return;
    setPollCreating(true);
    try {
      const created = await adminFetch<Poll>("/api/polls", {
        method: "POST",
        body: JSON.stringify({ title: pollTitle.trim(), question: pollQuestion.trim(), options: opts }),
      });
      setPolls((prev) => [created, ...prev]);
      setPollTitle("");
      setPollQuestion("");
      setPollOptions("");
    } catch {
      /* ignore */
    } finally {
      setPollCreating(false);
    }
  }

  async function archivePoll(id: number) {
    setActionLoading(`poll-archive-${id}`);
    try {
      await adminFetch(`/api/polls/${id}/archive`, { method: "POST" });
      setPolls((prev) =>
        prev.map((p) =>
          p.id === id ? { ...p, status: "archived", archived_at: new Date().toISOString() } : p
        )
      );
    } catch {
      /* ignore */
    } finally {
      setActionLoading(null);
    }
  }

  async function activatePoll(id: number) {
    setActionLoading(`poll-activate-${id}`);
    try {
      await adminFetch(`/api/polls/${id}/activate`, { method: "POST" });
      setPolls((prev) =>
        prev.map((p) =>
          p.id === id ? { ...p, status: "active", archived_at: null } : p
        )
      );
    } catch {
      /* ignore */
    } finally {
      setActionLoading(null);
    }
  }

  /* ---- Derived data ---- */

  const filteredUsers = users.filter(u =>
    u.email.toLowerCase().includes(userSearch.toLowerCase())
  );

  const bugs = feedback.filter((f) => f.type === "bug");
  const suggestions = feedback.filter((f) => f.type === "suggestion");
  const surveys = feedback.filter((f) => f.type === "survey");

  // Aggregate survey results by description value
  const surveyResults: Record<string, number> = {};
  surveys.forEach((s) => {
    surveyResults[s.description] = (surveyResults[s.description] || 0) + 1;
  });
  const surveyMax = Math.max(...Object.values(surveyResults), 1);

  const activePolls = polls.filter((p) => p.status === "active");
  const archivedPolls = polls.filter((p) => p.status === "archived");

  /* ---- Error state ---- */

  if (error) {
    return (
      <div className="max-w-2xl mx-auto py-20 text-center">
        <h1 className="text-2xl font-bold text-slate-900 mb-2">
          Access Denied
        </h1>
        <p className="text-slate-500">{error}</p>
      </div>
    );
  }

  /* ---- Render ---- */

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Admin Panel</h1>
        <p className="text-sm text-slate-500 mt-1">
          Platform overview and user management
        </p>
      </div>

      {/* ======== 1. Platform Stats ======== */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {/* Enterprises */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-slate-900 text-center">
                  {fmt(stats?.total_enterprises)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1 text-center">
                  Enterprises
                </div>
                {stats && (
                  <>
                    <ProgressBar
                      value={stats.total_enterprises}
                      target={stats.target_enterprises}
                    />
                    <div className="text-[10px] text-slate-400 mt-1 text-right">
                      {((stats.total_enterprises / stats.target_enterprises) * 100).toFixed(1)}%
                      of {fmt(stats.target_enterprises)}
                    </div>
                  </>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Companies with Financials */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-slate-900">
                  {fmt(stats?.companies_with_financials)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                  With Financials
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Financial Rows */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-slate-900 text-center">
                  {fmt(stats?.financial_rows)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1 text-center">
                  Financial Rows
                </div>
                {stats && (
                  <>
                    <ProgressBar
                      value={stats.financial_rows}
                      target={stats.target_financial_rows}
                    />
                    <div className="text-[10px] text-slate-400 mt-1 text-right">
                      {((stats.financial_rows / stats.target_financial_rows) * 100).toFixed(1)}%
                      of {fmt(stats.target_financial_rows)}
                    </div>
                  </>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Activity Rows */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-slate-900 text-center">
                  {fmt(stats?.activity_rows)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1 text-center">
                  Activity Rows
                </div>
                {stats && (
                  <>
                    <ProgressBar
                      value={stats.activity_rows}
                      target={stats.target_activity_rows}
                    />
                    <div className="text-[10px] text-slate-400 mt-1 text-right">
                      {((stats.activity_rows / stats.target_activity_rows) * 100).toFixed(1)}%
                      of {fmt(stats.target_activity_rows)}
                    </div>
                  </>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* DB Size */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-slate-900">
                  {stats?.db_size || "--"}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                  DB Size
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Total Users */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-slate-900">
                  {fmt(stats?.total_users)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                  Total Users
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Admin Users */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-indigo-600">
                  {fmt(stats?.admin_users)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                  Admins
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Blocked Users */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-red-600">
                  {fmt(stats?.blocked_users)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                  Blocked
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Daily Active Users */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-emerald-600">
                  {fmt(stats?.daily_active_users)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                  Active Today
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Most Visited Page */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-sm font-bold text-slate-900 truncate" title={stats?.most_visited_page || "--"}>
                  {stats?.most_visited_page || "--"}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                  Top Page (7d)
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Companies with Staatsblad */}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <Skeleton className="h-8 w-24 mx-auto" />
            ) : (
              <>
                <div className="text-2xl font-bold text-amber-600">
                  {fmt(stats?.companies_with_staatsblad)}
                </div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                  With Staatsblad
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ======== 1b. Dataset Coverage ======== */}
      {!loading && stats && (
        <div>
          <SectionHeading>Dataset Coverage</SectionHeading>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* Fully loaded — key metric */}
            <Card className="bg-white border-2 border-indigo-200 sm:col-span-2 lg:col-span-3">
              <CardContent className="pt-5 pb-4">
                <div className="flex items-center justify-between mb-1">
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-indigo-600 font-bold">
                      Fully Loaded Companies
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      Companies with financials + administrators + publications
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold text-indigo-600">
                      {fmt(stats.fully_loaded_companies)}
                    </div>
                    <div className="text-[10px] text-slate-400">
                      {((stats.fully_loaded_companies / stats.target_companies) * 100).toFixed(1)}% of {fmt(stats.target_companies)}
                    </div>
                  </div>
                </div>
                <ProgressBar value={stats.fully_loaded_companies} target={stats.target_companies} colorCoded />
              </CardContent>
            </Card>

            {/* Latest financials */}
            <Card className="bg-white">
              <CardContent className="pt-5 pb-4">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                    Latest Financials
                  </div>
                  <div className="text-lg font-bold text-slate-900">
                    {fmt(stats.companies_with_latest_financials)}
                  </div>
                </div>
                <ProgressBar value={stats.companies_with_latest_financials} target={stats.target_companies} colorCoded />
                <div className="text-[10px] text-slate-400 mt-1 text-right">
                  {((stats.companies_with_latest_financials / stats.target_companies) * 100).toFixed(1)}%
                </div>
              </CardContent>
            </Card>

            {/* Financial history */}
            <Card className="bg-white">
              <CardContent className="pt-5 pb-4">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                    Financial History
                  </div>
                  <div className="text-lg font-bold text-slate-900">
                    {fmt(stats.companies_with_history)}
                  </div>
                </div>
                <ProgressBar value={stats.companies_with_history} target={stats.target_companies} colorCoded />
                <div className="text-[10px] text-slate-400 mt-1 text-right">
                  {((stats.companies_with_history / stats.target_companies) * 100).toFixed(1)}%
                </div>
              </CardContent>
            </Card>

            {/* Publications (Staatsblad) */}
            <Card className="bg-white">
              <CardContent className="pt-5 pb-4">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                    Publications
                  </div>
                  <div className="text-lg font-bold text-slate-900">
                    {fmt(stats.companies_with_publications)}
                  </div>
                </div>
                <ProgressBar value={stats.companies_with_publications} target={stats.target_companies} colorCoded />
                <div className="text-[10px] text-slate-400 mt-1 text-right">
                  {((stats.companies_with_publications / stats.target_companies) * 100).toFixed(1)}%
                </div>
              </CardContent>
            </Card>

            {/* Administrators */}
            <Card className="bg-white">
              <CardContent className="pt-5 pb-4">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                    Administrators
                  </div>
                  <div className="text-lg font-bold text-slate-900">
                    {fmt(stats.companies_with_admins)}
                  </div>
                </div>
                <ProgressBar value={stats.companies_with_admins} target={stats.target_companies} colorCoded />
                <div className="text-[10px] text-slate-400 mt-1 text-right">
                  {((stats.companies_with_admins / stats.target_companies) * 100).toFixed(1)}%
                </div>
              </CardContent>
            </Card>

            {/* Shareholders */}
            <Card className="bg-white">
              <CardContent className="pt-5 pb-4">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                    Shareholders
                  </div>
                  <div className="text-lg font-bold text-slate-900">
                    {fmt(stats.companies_with_shareholders)}
                  </div>
                </div>
                <ProgressBar value={stats.companies_with_shareholders} target={stats.target_companies} colorCoded />
                <div className="text-[10px] text-slate-400 mt-1 text-right">
                  {((stats.companies_with_shareholders / stats.target_companies) * 100).toFixed(1)}%
                </div>
              </CardContent>
            </Card>

            {/* Subsidiaries */}
            <Card className="bg-white">
              <CardContent className="pt-5 pb-4">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                    Subsidiaries
                  </div>
                  <div className="text-lg font-bold text-slate-900">
                    {fmt(stats.companies_with_subsidiaries)}
                  </div>
                </div>
                <ProgressBar value={stats.companies_with_subsidiaries} target={stats.target_companies} colorCoded />
                <div className="text-[10px] text-slate-400 mt-1 text-right">
                  {((stats.companies_with_subsidiaries / stats.target_companies) * 100).toFixed(1)}%
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* ======== 2. Users Table ======== */}
      <div>
        <SectionHeading>Users ({users.length})</SectionHeading>
        <Input
          placeholder="Search users..."
          value={userSearch}
          onChange={(e) => setUserSearch(e.target.value)}
          className="max-w-sm mb-3"
        />
        <Card className="bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead className="text-right">Favourites</TableHead>
                <TableHead className="text-right">Feedback</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 6 }).map((_, j) => (
                        <TableCell key={j}>
                          <Skeleton className="h-4 w-24" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                : filteredUsers.map((u) => {
                    const isMe = u.email === myEmail;
                    return (
                      <TableRow key={u.email}>
                        <TableCell className="font-medium">
                          {u.email}
                          {isMe && (
                            <span className="ml-1.5 text-[10px] text-slate-400">
                              (you)
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              u.role === "admin"
                                ? "default"
                                : u.role === "blocked"
                                  ? "destructive"
                                  : "secondary"
                            }
                            className={
                              u.role === "admin"
                                ? "bg-indigo-100 text-indigo-700"
                                : u.role === "blocked"
                                  ? "bg-red-100 text-red-700"
                                  : ""
                            }
                          >
                            {u.role}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          {u.favourites_count}
                        </TableCell>
                        <TableCell className="text-right">
                          {u.feedback_count}
                        </TableCell>
                        <TableCell className="text-sm text-slate-500">
                          {new Date(u.created_at).toLocaleDateString()}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            {/* Block / Unblock */}
                            {!isMe && u.role !== "blocked" && (
                              <Button
                                variant="outline"
                                size="xs"
                                className="border-red-300 text-red-600 hover:bg-red-50"
                                disabled={actionLoading === `role-${u.email}`}
                                onClick={() => setRole(u.email, "blocked")}
                              >
                                Block
                              </Button>
                            )}
                            {!isMe && u.role === "blocked" && (
                              <Button
                                variant="outline"
                                size="xs"
                                className="border-slate-300 text-slate-600 hover:bg-slate-50"
                                disabled={actionLoading === `role-${u.email}`}
                                onClick={() => setRole(u.email, "user")}
                              >
                                Unblock
                              </Button>
                            )}

                            {/* Make admin / Remove admin */}
                            {!isMe && u.role !== "admin" && (
                              <Button
                                variant="outline"
                                size="xs"
                                className="border-indigo-300 text-indigo-600 hover:bg-indigo-50"
                                disabled={actionLoading === `role-${u.email}`}
                                onClick={() => setRole(u.email, "admin")}
                              >
                                Make admin
                              </Button>
                            )}
                            {!isMe && u.role === "admin" && (
                              <Button
                                variant="outline"
                                size="xs"
                                className="border-slate-300 text-slate-600 hover:bg-slate-50"
                                disabled={actionLoading === `role-${u.email}`}
                                onClick={() => setRole(u.email, "user")}
                              >
                                Revoke admin
                              </Button>
                            )}

                            {/* Delete */}
                            {!isMe && (
                              <>
                                {confirmDelete === u.email ? (
                                  <div className="flex items-center gap-1">
                                    <Button
                                      variant="destructive"
                                      size="xs"
                                      disabled={
                                        actionLoading === `delete-${u.email}`
                                      }
                                      onClick={() => deleteUser(u.email)}
                                    >
                                      Confirm
                                    </Button>
                                    <Button
                                      variant="ghost"
                                      size="xs"
                                      onClick={() => setConfirmDelete(null)}
                                    >
                                      Cancel
                                    </Button>
                                  </div>
                                ) : (
                                  <Button
                                    variant="outline"
                                    size="xs"
                                    className="border-red-300 text-red-600 hover:bg-red-50"
                                    onClick={() => setConfirmDelete(u.email)}
                                  >
                                    Remove
                                  </Button>
                                )}
                              </>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
            </TableBody>
          </Table>
        </Card>
      </div>

      {/* ======== 3. Feedback ======== */}
      <div>
        <SectionHeading>
          Feedback ({feedback.length})
        </SectionHeading>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Bugs column */}
          <div>
            <h3 className="text-sm font-semibold text-slate-700 mb-3">
              Bugs ({bugs.length})
            </h3>
            {bugs.length === 0 ? (
              <Card className="bg-white">
                <div className="py-6 text-center text-sm text-slate-400">
                  No bugs reported
                </div>
              </Card>
            ) : (
              <div className="space-y-3">
                {bugs.map((f) => (
                  <Card key={f.id} className="bg-white" size="sm">
                    <CardContent className="relative">
                      <button
                        className="absolute top-0 right-0 p-1 text-slate-300 hover:text-red-500 transition-colors"
                        onClick={() => deleteFeedback(f.id)}
                        disabled={actionLoading === `fb-${f.id}`}
                        aria-label="Delete feedback"
                      >
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 14 14"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                        >
                          <path d="M3 3l8 8M11 3l-8 8" />
                        </svg>
                      </button>
                      <p className="text-sm text-slate-800 pr-5 leading-relaxed">
                        {f.description}
                      </p>
                      <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-400">
                        {f.page && <span>{f.page}</span>}
                        {f.user_email && <span>{f.user_email}</span>}
                        <span>
                          {new Date(f.created_at).toLocaleDateString()}
                        </span>
                      </div>

                      {/* Reply display / button */}
                      {f.reply ? (
                        <div className="mt-3 border-t border-slate-100 pt-3">
                          <div className="flex items-center gap-2 mb-1">
                            <Badge className="bg-green-100 text-green-700 text-[10px]">Replied</Badge>
                            {f.replied_at && (
                              <span className="text-[10px] text-slate-400">
                                {new Date(f.replied_at).toLocaleDateString()}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-slate-600 leading-relaxed">{f.reply}</p>
                        </div>
                      ) : replyingTo === f.id ? (
                        <div className="mt-3 border-t border-slate-100 pt-3 space-y-2">
                          <Textarea
                            placeholder="Write a reply..."
                            value={replyText}
                            onChange={(e) => setReplyText(e.target.value)}
                            className="text-sm min-h-[60px]"
                          />
                          <div className="flex gap-2">
                            <Button
                              size="xs"
                              className="bg-indigo-600 text-white hover:bg-indigo-700"
                              disabled={!replyText.trim() || actionLoading === `reply-${f.id}`}
                              onClick={() => replyToFeedback(f.id)}
                            >
                              {actionLoading === `reply-${f.id}` ? "Sending..." : "Send Reply"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="xs"
                              onClick={() => { setReplyingTo(null); setReplyText(""); }}
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="mt-2">
                          <Button
                            variant="outline"
                            size="xs"
                            className="border-indigo-300 text-indigo-600 hover:bg-indigo-50 text-[11px]"
                            onClick={() => { setReplyingTo(f.id); setReplyText(""); }}
                          >
                            Reply
                          </Button>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>

          {/* Suggestions column */}
          <div>
            <h3 className="text-sm font-semibold text-slate-700 mb-3">
              Suggestions ({suggestions.length})
            </h3>
            {suggestions.length === 0 ? (
              <Card className="bg-white">
                <div className="py-6 text-center text-sm text-slate-400">
                  No suggestions yet
                </div>
              </Card>
            ) : (
              <div className="space-y-3">
                {suggestions.map((f) => (
                  <Card key={f.id} className="bg-white" size="sm">
                    <CardContent className="relative">
                      <button
                        className="absolute top-0 right-0 p-1 text-slate-300 hover:text-red-500 transition-colors"
                        onClick={() => deleteFeedback(f.id)}
                        disabled={actionLoading === `fb-${f.id}`}
                        aria-label="Delete feedback"
                      >
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 14 14"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                        >
                          <path d="M3 3l8 8M11 3l-8 8" />
                        </svg>
                      </button>
                      <p className="text-sm text-slate-800 pr-5 leading-relaxed">
                        {f.description}
                      </p>
                      <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-400">
                        {f.page && <span>{f.page}</span>}
                        {f.user_email && <span>{f.user_email}</span>}
                        <span>
                          {new Date(f.created_at).toLocaleDateString()}
                        </span>
                      </div>

                      {/* Reply display / button */}
                      {f.reply ? (
                        <div className="mt-3 border-t border-slate-100 pt-3">
                          <div className="flex items-center gap-2 mb-1">
                            <Badge className="bg-green-100 text-green-700 text-[10px]">Replied</Badge>
                            {f.replied_at && (
                              <span className="text-[10px] text-slate-400">
                                {new Date(f.replied_at).toLocaleDateString()}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-slate-600 leading-relaxed">{f.reply}</p>
                        </div>
                      ) : replyingTo === f.id ? (
                        <div className="mt-3 border-t border-slate-100 pt-3 space-y-2">
                          <Textarea
                            placeholder="Write a reply..."
                            value={replyText}
                            onChange={(e) => setReplyText(e.target.value)}
                            className="text-sm min-h-[60px]"
                          />
                          <div className="flex gap-2">
                            <Button
                              size="xs"
                              className="bg-indigo-600 text-white hover:bg-indigo-700"
                              disabled={!replyText.trim() || actionLoading === `reply-${f.id}`}
                              onClick={() => replyToFeedback(f.id)}
                            >
                              {actionLoading === `reply-${f.id}` ? "Sending..." : "Send Reply"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="xs"
                              onClick={() => { setReplyingTo(null); setReplyText(""); }}
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="mt-2">
                          <Button
                            variant="outline"
                            size="xs"
                            className="border-indigo-300 text-indigo-600 hover:bg-indigo-50 text-[11px]"
                            onClick={() => { setReplyingTo(f.id); setReplyText(""); }}
                          >
                            Reply
                          </Button>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Survey results */}
        {surveys.length > 0 && (
          <div className="mt-6">
            <h3 className="text-sm font-semibold text-slate-700 mb-3">
              Survey Results ({surveys.length} responses)
            </h3>
            <Card className="bg-white">
              <CardContent>
                <div className="space-y-3">
                  {Object.entries(surveyResults)
                    .sort(([, a], [, b]) => b - a)
                    .map(([label, count]) => (
                      <div key={label}>
                        <div className="flex items-center justify-between text-sm mb-1">
                          <span className="text-slate-700 truncate mr-3">
                            {label}
                          </span>
                          <span className="text-slate-500 font-medium tabular-nums shrink-0">
                            {count}
                          </span>
                        </div>
                        <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-indigo-500 transition-all duration-500"
                            style={{
                              width: `${(count / surveyMax) * 100}%`,
                            }}
                          />
                        </div>
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Clear all feedback */}
        {feedback.length > 0 && (
          <div className="mt-4">
            {confirmClearFeedback ? (
              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-500">
                  Delete all {feedback.length} feedback items?
                </span>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={actionLoading === "clear-fb"}
                  onClick={clearAllFeedback}
                >
                  Yes, clear all
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmClearFeedback(false)}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="border-red-300 text-red-600 hover:bg-red-50"
                onClick={() => setConfirmClearFeedback(true)}
              >
                Clear all feedback
              </Button>
            )}
          </div>
        )}
      </div>

      {/* ======== 4. User Activity ======== */}
      <div>
        <SectionHeading>User Activity (7 days)</SectionHeading>
        <Card className="bg-white">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead className="text-right">Total Requests</TableHead>
                <TableHead className="text-right">Unique Pages</TableHead>
                <TableHead>Last Active</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 4 }).map((_, j) => (
                        <TableCell key={j}>
                          <Skeleton className="h-4 w-24" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                : activity.length === 0
                  ? (
                    <TableRow>
                      <TableCell colSpan={4} className="text-center py-8 text-sm text-slate-400">
                        No activity data available
                      </TableCell>
                    </TableRow>
                  )
                  : [...activity]
                      .sort((a, b) => b.total_requests - a.total_requests)
                      .map((row) => (
                        <TableRow key={row.user_email}>
                          <TableCell className="font-medium">
                            {row.user_email}
                          </TableCell>
                          <TableCell className="text-right font-mono text-sm">
                            {fmt(row.total_requests)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-sm">
                            {fmt(row.unique_pages)}
                          </TableCell>
                          <TableCell className="text-sm text-slate-500">
                            {new Date(row.last_active).toLocaleString()}
                          </TableCell>
                        </TableRow>
                      ))}
            </TableBody>
          </Table>
        </Card>
      </div>

      {/* ======== 5. Polls & Campaigns ======== */}
      <div>
        <SectionHeading>Polls &amp; Campaigns</SectionHeading>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Create Poll form */}
          <Card className="bg-white">
            <CardContent>
              <h3 className="text-sm font-semibold text-slate-700 mb-3">
                Create Poll
              </h3>
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-slate-500 mb-1 block">Title</label>
                  <Input
                    placeholder="e.g. Feature Priority Q2"
                    value={pollTitle}
                    onChange={(e) => setPollTitle(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-500 mb-1 block">Question</label>
                  <Input
                    placeholder="e.g. Which feature should we build next?"
                    value={pollQuestion}
                    onChange={(e) => setPollQuestion(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs text-slate-500 mb-1 block">Options (comma-separated)</label>
                  <Input
                    placeholder="e.g. Dark mode, API access, Mobile app"
                    value={pollOptions}
                    onChange={(e) => setPollOptions(e.target.value)}
                  />
                </div>
                <Button
                  onClick={createPoll}
                  disabled={pollCreating || !pollTitle.trim() || !pollQuestion.trim() || pollOptions.split(",").filter((o) => o.trim()).length < 2}
                  className="w-full bg-indigo-600 text-white hover:bg-indigo-700"
                >
                  {pollCreating ? "Creating..." : "Create"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Active poll */}
          <div>
            <h3 className="text-sm font-semibold text-slate-700 mb-3">
              Active Poll
            </h3>
            {activePolls.length === 0 ? (
              <Card className="bg-white">
                <div className="py-6 text-center text-sm text-slate-400">
                  No active poll
                </div>
              </Card>
            ) : (
              activePolls.map((poll) => (
                <Card key={poll.id} className="bg-white mb-3">
                  <CardContent>
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <h4 className="text-sm font-semibold text-slate-800">{poll.title}</h4>
                        <p className="text-sm text-slate-600 mt-0.5">{poll.question}</p>
                      </div>
                      <Badge className="bg-green-100 text-green-700 shrink-0 ml-2">active</Badge>
                    </div>

                    {/* Vote bars */}
                    <div className="mb-3">
                      {poll.options.map((opt) => {
                        const count = poll.votes[opt] || 0;
                        const pct = poll.total_votes > 0 ? (count / poll.total_votes * 100) : 0;
                        return (
                          <div key={opt} className="mb-2">
                            <div className="flex justify-between text-sm mb-1">
                              <span className="text-slate-700">{opt}</span>
                              <span className="text-slate-500">{count} ({pct.toFixed(0)}%)</span>
                            </div>
                            <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                              <div className="h-full bg-indigo-500 rounded-full" style={{width: `${pct}%`}} />
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-400">
                        {poll.total_votes} total vote{poll.total_votes !== 1 ? "s" : ""}
                      </span>
                      <Button
                        variant="outline"
                        size="xs"
                        className="border-amber-300 text-amber-600 hover:bg-amber-50"
                        disabled={actionLoading === `poll-archive-${poll.id}`}
                        onClick={() => archivePoll(poll.id)}
                      >
                        Archive
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </div>

        {/* Archived polls */}
        {archivedPolls.length > 0 && (
          <div className="mt-6">
            <button
              className="flex items-center gap-1.5 text-sm font-semibold text-slate-700 mb-3 hover:text-slate-900"
              onClick={() => setArchivedExpanded(!archivedExpanded)}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                className={`transition-transform ${archivedExpanded ? "rotate-90" : ""}`}
                fill="currentColor"
              >
                <path d="M4 2l4 4-4 4" />
              </svg>
              Archived Polls ({archivedPolls.length})
            </button>
            {archivedExpanded && (
              <div className="space-y-3">
                {archivedPolls.map((poll) => (
                  <Card key={poll.id} className="bg-white">
                    <CardContent>
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <h4 className="text-sm font-semibold text-slate-800">{poll.title}</h4>
                          <p className="text-sm text-slate-600 mt-0.5">{poll.question}</p>
                        </div>
                        <Badge className="bg-slate-100 text-slate-500 shrink-0 ml-2">archived</Badge>
                      </div>

                      {/* Vote bars */}
                      <div className="mb-3">
                        {poll.options.map((opt) => {
                          const count = poll.votes[opt] || 0;
                          const pct = poll.total_votes > 0 ? (count / poll.total_votes * 100) : 0;
                          return (
                            <div key={opt} className="mb-2">
                              <div className="flex justify-between text-sm mb-1">
                                <span className="text-slate-700">{opt}</span>
                                <span className="text-slate-500">{count} ({pct.toFixed(0)}%)</span>
                              </div>
                              <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                                <div className="h-full bg-slate-400 rounded-full" style={{width: `${pct}%`}} />
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      <div className="flex items-center justify-between">
                        <div className="text-xs text-slate-400 space-x-3">
                          <span>{poll.total_votes} vote{poll.total_votes !== 1 ? "s" : ""}</span>
                          <span>Created {new Date(poll.created_at).toLocaleDateString()}</span>
                          {poll.archived_at && (
                            <span>Archived {new Date(poll.archived_at).toLocaleDateString()}</span>
                          )}
                        </div>
                        <Button
                          variant="outline"
                          size="xs"
                          className="border-indigo-300 text-indigo-600 hover:bg-indigo-50"
                          disabled={actionLoading === `poll-activate-${poll.id}`}
                          onClick={() => activatePoll(poll.id)}
                        >
                          Re-activate
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
