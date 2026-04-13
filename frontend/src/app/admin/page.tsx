"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
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
}: {
  value: number;
  target: number;
}) {
  const pct = Math.min((value / target) * 100, 100);
  return (
    <div className="mt-2 h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
      <div
        className="h-full rounded-full bg-indigo-600 transition-all duration-500"
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

  const loadData = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: sessionData } = await supabase.auth.getSession();
      setMyEmail(sessionData.session?.user?.email || "");

      const [s, u, f] = await Promise.all([
        adminFetch<AdminStats>("/api/admin/stats"),
        adminFetch<UserRow[]>("/api/admin/users"),
        adminFetch<FeedbackRow[]>("/api/admin/feedback"),
      ]);
      setStats(s);
      setUsers(u);
      setFeedback(f);
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

  /* ---- Derived data ---- */

  const bugs = feedback.filter((f) => f.type === "bug");
  const suggestions = feedback.filter((f) => f.type === "suggestion");
  const surveys = feedback.filter((f) => f.type === "survey");

  // Aggregate survey results by description value
  const surveyResults: Record<string, number> = {};
  surveys.forEach((s) => {
    surveyResults[s.description] = (surveyResults[s.description] || 0) + 1;
  });
  const surveyMax = Math.max(...Object.values(surveyResults), 1);

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
      </div>

      {/* ======== 2. Users Table ======== */}
      <div>
        <SectionHeading>Users ({users.length})</SectionHeading>
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
                : users.map((u) => {
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
    </div>
  );
}
