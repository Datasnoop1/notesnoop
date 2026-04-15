"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { createClient } from "@/lib/supabase";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  Gauge,
  Users,
  MessageSquare,
  BarChart3,
  Database,
  TrendingUp,
  TrendingDown,
  Shield,
  Search,
  Trash2,
  Reply,
  ChevronRight,
  RefreshCw,
  HardDrive,
  Activity,
  UserX,
  UserCheck,
  CircleCheck,
  CircleAlert,
  Settings,
  Vote,
  Clock,
  Globe,
  Eye,
  HeartPulse,
  UserPlus,
  ShieldCheck,
  AlertTriangle,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Building2,
  CreditCard,
} from "lucide-react";

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

interface ActivityEntry {
  user_email: string;
  endpoint: string;
  method: string;
  created_at: string;
}

interface StripePayment {
  id: string;
  amount: number;
  currency: string;
  status: string;
  email: string | null;
  created: string;
  mode: string;
}

interface PaymentsData {
  payments: StripePayment[];
  total_revenue: number;
  currency: string;
}

interface Insights {
  total_users: number;
  active_users_7d: number;
  new_users_7d: number;
  anon_requests_7d: number;
  auth_requests_7d: number;
  companies_with_financials: number;
  total_companies: number;
  coverage_pct: number;
  load_success_count: number;
  load_error_count: number;
  success_rate: number;
  active_users_prev_7d: number;
  new_users_prev_7d: number;
  top_companies: { cbe: string; name: string; view_count: number }[];
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

/* ---------- Utility ---------- */

function fmt(n: number | undefined | null): string {
  if (n == null) return "--";
  return n.toLocaleString();
}

function pct(value: number, total: number): number {
  if (!total) return 0;
  return Math.min((value / total) * 100, 100);
}

function pctStr(value: number, total: number): string {
  return pct(value, total).toFixed(1);
}

function readinessColor(score: number): string {
  if (score >= 80) return "text-emerald-600";
  if (score >= 40) return "text-amber-500";
  return "text-red-500";
}

function barColor(score: number): string {
  if (score >= 80) return "bg-emerald-500";
  if (score >= 40) return "bg-amber-500";
  return "bg-red-500";
}

function bgReadiness(score: number): string {
  if (score >= 80) return "bg-emerald-50 ring-emerald-200";
  if (score >= 40) return "bg-amber-50 ring-amber-200";
  return "bg-red-50 ring-red-200";
}

function trendDirection(current: number, previous: number): "up" | "down" | "flat" {
  if (current > previous) return "up";
  if (current < previous) return "down";
  return "flat";
}

function healthStatus(rate: number): { label: string; color: string; bg: string } {
  if (rate >= 95) return { label: "Healthy", color: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200" };
  if (rate >= 80) return { label: "Good", color: "text-emerald-600", bg: "bg-emerald-50 border-emerald-200" };
  if (rate >= 50) return { label: "Needs Attention", color: "text-amber-600", bg: "bg-amber-50 border-amber-200" };
  return { label: "Critical", color: "text-red-600", bg: "bg-red-50 border-red-200" };
}

/* ---------- Small components ---------- */

function TrendBadge({ current, previous, suffix = "" }: { current: number; previous: number; suffix?: string }) {
  const dir = trendDirection(current, previous);
  const diff = current - previous;
  if (dir === "flat") {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] font-medium text-slate-400">
        <Minus className="size-3" />
        No change
      </span>
    );
  }
  const isUp = dir === "up";
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] font-medium ${isUp ? "text-emerald-600" : "text-red-500"}`}>
      {isUp ? <ArrowUpRight className="size-3" /> : <ArrowDownRight className="size-3" />}
      {isUp ? "+" : ""}{diff}{suffix} vs prev week
    </span>
  );
}

function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse bg-slate-200 rounded ${className}`} />
  );
}

function SectionHeading({
  icon: Icon,
  children,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-slate-500 mb-4">
      {Icon && <Icon className="size-3.5" />}
      {children}
    </h2>
  );
}

function ProgressBar({
  value,
  target,
  colorCoded,
  height = "h-1.5",
}: {
  value: number;
  target: number;
  colorCoded?: boolean;
  height?: string;
}) {
  const p = pct(value, target);
  const color = colorCoded ? barColor(p) : "bg-indigo-600";
  return (
    <div className={`${height} w-full rounded-full bg-slate-100 overflow-hidden`}>
      <div
        className={`h-full rounded-full ${color} transition-all duration-700`}
        style={{ width: `${p}%` }}
      />
    </div>
  );
}

function HorizontalBar({
  label,
  value,
  total,
}: {
  label: string;
  value: number;
  total: number;
}) {
  const p = pct(value, total);
  const color = barColor(p);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm text-slate-600">{label}</span>
        <span className={`text-sm font-mono font-semibold ${readinessColor(p)}`}>
          {p.toFixed(1)}%
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full rounded-full ${color} transition-all duration-700`}
          style={{ width: `${p}%` }}
        />
      </div>
    </div>
  );
}

/** Large circular readiness gauge rendered with SVG. */
function ReadinessGauge({ score }: { score: number }) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.min(score, 100) / 100) * circumference;
  const strokeColor =
    score >= 80 ? "#10b981" : score >= 40 ? "#f59e0b" : "#ef4444";

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width="140" height="140" className="-rotate-90">
        <circle
          cx="70"
          cy="70"
          r={radius}
          fill="none"
          stroke="#f1f5f9"
          strokeWidth="10"
        />
        <circle
          cx="70"
          cy="70"
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-1000"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className="text-3xl font-bold font-mono"
          style={{ color: strokeColor }}
        >
          {score.toFixed(0)}%
        </span>
        <span className="text-[10px] uppercase tracking-wide text-slate-400 mt-0.5">
          Ready
        </span>
      </div>
    </div>
  );
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
  const [activityLog, setActivityLog] = useState<ActivityEntry[]>([]);
  const [archivedExpanded, setArchivedExpanded] = useState(false);
  const [replyingTo, setReplyingTo] = useState<number | null>(null);
  const [replyText, setReplyText] = useState("");
  const [addingOptionTo, setAddingOptionTo] = useState<number | null>(null);
  const [newOptionText, setNewOptionText] = useState("");
  const [userView, setUserView] = useState<"all" | "active">("all");
  const [finByYear, setFinByYear] = useState<{ fiscal_year: number; companies: number; filings: number }[]>([]);
  const [insights, setInsights] = useState<Insights | null>(null);
  const [usageData, setUsageData] = useState<{
    daily: { day: string; registered_requests: number; guest_requests: number; unique_registered: number; unique_guests: number }[];
    top_pages: { page: string; requests: number; unique_users: number }[];
    top_registered: { user_email: string; requests: number; unique_pages: number; last_seen: string }[];
    top_guests: { ip: string; requests: number; unique_pages: number; last_seen: string }[];
    totals: { total_requests_30d: number; guest_requests_30d: number; registered_requests_30d: number; unique_registered_30d: number; unique_guests_30d: number };
  } | null>(null);
  const [paymentsData, setPaymentsData] = useState<PaymentsData | null>(null);

  const loadData = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: sessionData } = await supabase.auth.getSession();
      setMyEmail(sessionData.session?.user?.email || "");

      const [s, u, f, a, p, fby, alog, ins, usage, pay] = await Promise.all([
        adminFetch<AdminStats>("/api/admin/stats"),
        adminFetch<UserRow[]>("/api/admin/users"),
        adminFetch<FeedbackRow[]>("/api/admin/feedback"),
        adminFetch<ActivitySummary[]>("/api/admin/activity/summary").catch(
          () => [] as ActivitySummary[]
        ),
        adminFetch<Poll[]>("/api/polls").catch(() => [] as Poll[]),
        adminFetch<{ fiscal_year: number; companies: number; filings: number }[]>("/api/admin/financials-by-year").catch(() => []),
        adminFetch<ActivityEntry[]>("/api/admin/activity").catch(() => [] as ActivityEntry[]),
        adminFetch<Insights>("/api/admin/insights").catch(() => null),
        adminFetch<typeof usageData>("/api/admin/usage").catch(() => null),
        adminFetch<PaymentsData>("/api/admin/payments").catch(() => null),
      ]);
      setStats(s);
      setUsers(u);
      setFeedback(f);
      setActivity(a);
      setPolls(p);
      setFinByYear(fby);
      setActivityLog(alog);
      setInsights(ins);
      setUsageData(usage as typeof usageData);
      setPaymentsData(pay);
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

  /* ---- Computed readiness ---- */

  // Use full universe of active legal-person enterprises from backend
  const TARGET = stats?.target_companies || 1941155;

  const readiness = useMemo(() => {
    if (!stats) return null;
    const t = stats.target_companies || 1941155;
    const financials = pct(stats.companies_with_latest_financials, t);
    const admins = pct(stats.companies_with_admins, t);
    const publications = pct(stats.companies_with_publications, t);
    const shareholders = pct(stats.companies_with_shareholders, t);
    const subsidiaries = pct(stats.companies_with_subsidiaries, t);
    const score =
      financials * 0.4 +
      admins * 0.2 +
      publications * 0.2 +
      shareholders * 0.1 +
      subsidiaries * 0.1;
    return {
      score,
      financials,
      admins,
      publications,
      shareholders,
      subsidiaries,
    };
  }, [stats]);

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
    const opts = pollOptions
      .split(",")
      .map((o) => o.trim())
      .filter(Boolean);
    if (!pollTitle.trim() || !pollQuestion.trim() || opts.length < 2) return;
    setPollCreating(true);
    try {
      const created = await adminFetch<Poll>("/api/polls", {
        method: "POST",
        body: JSON.stringify({
          title: pollTitle.trim(),
          question: pollQuestion.trim(),
          options: opts,
        }),
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
          p.id === id
            ? { ...p, status: "archived", archived_at: new Date().toISOString() }
            : p
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

  // Merge users + activity for the users table
  const activityMap = useMemo(() => {
    const map = new Map<string, ActivitySummary>();
    activity.forEach((a) => map.set(a.user_email, a));
    return map;
  }, [activity]);

  // Active users = users who appear in activity_log within the last 7 days
  const activeUsers = useMemo(() => {
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    return users.filter((u) => {
      const act = activityMap.get(u.email);
      if (!act) return false;
      return new Date(act.last_active) > sevenDaysAgo;
    });
  }, [users, activityMap]);

  const baseUsers = userView === "active" ? activeUsers : users;
  const filteredUsers = baseUsers.filter((u) =>
    u.email.toLowerCase().includes(userSearch.toLowerCase())
  );

  const bugs = feedback.filter((f) => f.type === "bug");
  const suggestions = feedback.filter((f) => f.type === "suggestion");
  const surveys = feedback.filter((f) => f.type === "survey");

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

  /* ---- Feedback card reusable ---- */

  function FeedbackCard({ f }: { f: FeedbackRow }) {
    return (
      <Card key={f.id} className="bg-white" size="sm">
        <CardContent className="relative">
          <button
            className="absolute top-0 right-0 p-1 text-slate-300 hover:text-red-500 transition-colors"
            onClick={() => deleteFeedback(f.id)}
            disabled={actionLoading === `fb-${f.id}`}
            aria-label="Delete feedback"
          >
            <Trash2 className="size-3.5" />
          </button>
          <p className="text-sm text-slate-800 pr-5 leading-relaxed">
            {f.description}
          </p>
          <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-400">
            {f.page && <span>{f.page}</span>}
            {f.user_email && <span>{f.user_email}</span>}
            <span>{new Date(f.created_at).toLocaleDateString()}</span>
          </div>

          {f.reply ? (
            <div className="mt-3 border-t border-slate-100 pt-3">
              <div className="flex items-center gap-2 mb-1">
                <Badge className="bg-green-100 text-green-700 text-[10px]">
                  Replied
                </Badge>
                {f.replied_at && (
                  <span className="text-[10px] text-slate-400">
                    {new Date(f.replied_at).toLocaleDateString()}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">
                {f.reply}
              </p>
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
                  disabled={
                    !replyText.trim() || actionLoading === `reply-${f.id}`
                  }
                  onClick={() => replyToFeedback(f.id)}
                >
                  {actionLoading === `reply-${f.id}` ? "Sending..." : "Send"}
                </Button>
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => {
                    setReplyingTo(null);
                    setReplyText("");
                  }}
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
                onClick={() => {
                  setReplyingTo(f.id);
                  setReplyText("");
                }}
              >
                <Reply className="size-3 mr-1" />
                Reply
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  /* ---- Render ---- */

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Admin Panel</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Manage platform readiness, users, feedback, and polls
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setLoading(true);
            loadData();
          }}
          disabled={loading}
          className="text-slate-500"
        >
          <RefreshCw className={`size-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <Tabs defaultValue="readiness">
        <TabsList className="overflow-x-auto scrollbar-none w-full">
          <TabsTrigger value="readiness">
            <Gauge className="size-3.5 mr-1.5" />
            Readiness
          </TabsTrigger>
          <TabsTrigger value="usage">
            <Activity className="size-3.5 mr-1.5" />
            Usage
          </TabsTrigger>
          <TabsTrigger value="users">
            <Users className="size-3.5 mr-1.5" />
            Users
          </TabsTrigger>
          <TabsTrigger value="feedback">
            <MessageSquare className="size-3.5 mr-1.5" />
            Feedback
            {feedback.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 font-mono text-[10px] px-1.5 py-0">
                {feedback.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="polls">
            <Vote className="size-3.5 mr-1.5" />
            Polls
          </TabsTrigger>
          <TabsTrigger value="activity">
            <Clock className="size-3.5 mr-1.5" />
            Activity
          </TabsTrigger>
          <TabsTrigger value="revenue">
            <CreditCard className="size-3.5 mr-1.5" />
            Revenue
          </TabsTrigger>
          <TabsTrigger value="settings">
            <Settings className="size-3.5 mr-1.5" />
            Settings
          </TabsTrigger>
        </TabsList>

        {/* ================================================================
            TAB 1: Readiness
            ================================================================ */}
        <TabsContent value="readiness">
          <div className="space-y-8 pt-2">
            {/* Platform Readiness — Hero metric */}
            <Card className={`bg-white ${!loading && readiness ? bgReadiness(readiness.score) : ""}`}>
              <CardContent>
                {loading ? (
                  <div className="flex items-center justify-center py-8">
                    <Skeleton className="h-32 w-32 rounded-full" />
                  </div>
                ) : readiness && stats ? (
                  <div className="flex flex-col sm:flex-row items-center gap-6 py-2">
                    <ReadinessGauge score={readiness.score} />
                    <div className="flex-1 min-w-0">
                      <h2 className="text-lg font-semibold text-slate-800 mb-1">
                        Platform Readiness Score
                      </h2>
                      <p className="text-sm text-slate-500 mb-4">
                        {fmt(stats.fully_loaded_companies)} out of{" "}
                        <span className="font-mono">{fmt(TARGET)}</span> companies have
                        a complete profile
                      </p>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-xs text-slate-500">
                        <div className="flex justify-between">
                          <span>Financials (40%)</span>
                          <span className="font-mono font-semibold">{readiness.financials.toFixed(1)}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Administrators (20%)</span>
                          <span className="font-mono font-semibold">{readiness.admins.toFixed(1)}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Publications (20%)</span>
                          <span className="font-mono font-semibold">{readiness.publications.toFixed(1)}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Shareholders (10%)</span>
                          <span className="font-mono font-semibold">{readiness.shareholders.toFixed(1)}%</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Subsidiaries (10%)</span>
                          <span className="font-mono font-semibold">{readiness.subsidiaries.toFixed(1)}%</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>

            {/* Platform Health Summary */}
            {!loading && insights && (
              <div>
                <SectionHeading icon={HeartPulse}>Platform Health</SectionHeading>
                {(() => {
                  const health = healthStatus(insights.success_rate);
                  const totalTraffic = insights.anon_requests_7d + insights.auth_requests_7d;
                  const authPct = totalTraffic > 0 ? ((insights.auth_requests_7d / totalTraffic) * 100) : 0;
                  return (
                    <>
                      {/* Health banner */}
                      <Card className={`border ${health.bg} mb-4`}>
                        <CardContent>
                          <div className="flex items-center gap-3">
                            <div className={`p-2 rounded-lg ${health.bg}`}>
                              {insights.success_rate >= 80 ? (
                                <ShieldCheck className={`size-5 ${health.color}`} />
                              ) : (
                                <AlertTriangle className={`size-5 ${health.color}`} />
                              )}
                            </div>
                            <div>
                              <p className={`text-sm font-semibold ${health.color}`}>
                                Platform status: {health.label}
                              </p>
                              <p className="text-xs text-slate-500 mt-0.5">
                                {insights.success_rate.toFixed(1)}% data load success rate
                                {" / "}
                                {fmt(insights.active_users_7d)} active user{insights.active_users_7d !== 1 ? "s" : ""} this week
                                {" / "}
                                {insights.coverage_pct.toFixed(1)}% financial coverage
                              </p>
                            </div>
                          </div>
                        </CardContent>
                      </Card>

                      {/* KPI cards */}
                      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                        {/* Active users */}
                        <Card className="bg-white">
                          <CardContent>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                                Active Users (7d)
                              </span>
                              <Users className="size-3.5 text-indigo-300" />
                            </div>
                            <div className="text-2xl font-bold font-mono text-slate-900">
                              {fmt(insights.active_users_7d)}
                            </div>
                            <div className="text-[10px] text-slate-400 mb-1">
                              of {fmt(insights.total_users)} total
                            </div>
                            <TrendBadge
                              current={insights.active_users_7d}
                              previous={insights.active_users_prev_7d}
                            />
                          </CardContent>
                        </Card>

                        {/* New users */}
                        <Card className="bg-white">
                          <CardContent>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                                New Users (7d)
                              </span>
                              <UserPlus className="size-3.5 text-emerald-300" />
                            </div>
                            <div className="text-2xl font-bold font-mono text-slate-900">
                              {fmt(insights.new_users_7d)}
                            </div>
                            <div className="text-[10px] text-slate-400 mb-1">
                              sign-ups this week
                            </div>
                            <TrendBadge
                              current={insights.new_users_7d}
                              previous={insights.new_users_prev_7d}
                            />
                          </CardContent>
                        </Card>

                        {/* Data coverage */}
                        <Card className="bg-white">
                          <CardContent>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                                Financial Coverage
                              </span>
                              <Database className="size-3.5 text-blue-300" />
                            </div>
                            <div className={`text-2xl font-bold font-mono ${readinessColor(insights.coverage_pct)}`}>
                              {insights.coverage_pct.toFixed(1)}%
                            </div>
                            <div className="text-[10px] text-slate-400 mb-1">
                              {fmt(insights.companies_with_financials)} of {fmt(insights.total_companies)}
                            </div>
                            <ProgressBar
                              value={insights.companies_with_financials}
                              target={insights.total_companies}
                              colorCoded
                            />
                          </CardContent>
                        </Card>

                        {/* Load success rate */}
                        <Card className="bg-white">
                          <CardContent>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                                Load Success Rate
                              </span>
                              <Activity className="size-3.5 text-emerald-300" />
                            </div>
                            <div className={`text-2xl font-bold font-mono ${
                              insights.success_rate >= 95
                                ? "text-emerald-600"
                                : insights.success_rate >= 80
                                  ? "text-amber-500"
                                  : "text-red-500"
                            }`}>
                              {insights.success_rate.toFixed(1)}%
                            </div>
                            <div className="text-[10px] text-slate-400 mb-1">
                              {fmt(insights.load_success_count)} ok / {fmt(insights.load_error_count)} errors
                            </div>
                            <ProgressBar
                              value={insights.load_success_count}
                              target={insights.load_success_count + insights.load_error_count}
                              colorCoded
                            />
                          </CardContent>
                        </Card>
                      </div>

                      {/* Traffic split + Top companies row */}
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        {/* Traffic split */}
                        <Card className="bg-white">
                          <CardContent>
                            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-700 mb-3">
                              <Globe className="size-3.5 text-slate-400" />
                              Traffic Split (7 days)
                            </h3>
                            <div className="flex items-end gap-4 mb-3">
                              <div>
                                <div className="text-xl font-bold font-mono text-slate-900">
                                  {fmt(totalTraffic)}
                                </div>
                                <div className="text-[10px] text-slate-400">total requests</div>
                              </div>
                            </div>
                            {/* Stacked bar */}
                            <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden flex">
                              <div
                                className="h-full bg-indigo-500 transition-all duration-700"
                                style={{ width: `${authPct}%` }}
                              />
                              <div
                                className="h-full bg-slate-300 transition-all duration-700"
                                style={{ width: `${100 - authPct}%` }}
                              />
                            </div>
                            <div className="flex justify-between mt-2 text-xs">
                              <span className="flex items-center gap-1.5">
                                <span className="inline-block w-2 h-2 rounded-full bg-indigo-500" />
                                <span className="text-slate-600">Registered</span>
                                <span className="font-mono font-semibold text-slate-800">{fmt(insights.auth_requests_7d)}</span>
                                <span className="text-slate-400">({authPct.toFixed(0)}%)</span>
                              </span>
                              <span className="flex items-center gap-1.5">
                                <span className="inline-block w-2 h-2 rounded-full bg-slate-300" />
                                <span className="text-slate-600">Anonymous</span>
                                <span className="font-mono font-semibold text-slate-800">{fmt(insights.anon_requests_7d)}</span>
                                <span className="text-slate-400">({(100 - authPct).toFixed(0)}%)</span>
                              </span>
                            </div>
                          </CardContent>
                        </Card>

                        {/* Most viewed companies */}
                        <Card className="bg-white">
                          <CardContent>
                            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-700 mb-3">
                              <Building2 className="size-3.5 text-slate-400" />
                              Most Viewed Companies (30 days)
                            </h3>
                            {insights.top_companies.length === 0 ? (
                              <p className="text-sm text-slate-400 py-4 text-center">No company views recorded yet.</p>
                            ) : (
                              <div className="space-y-1.5">
                                {insights.top_companies.map((tc, i) => {
                                  const maxViews = insights.top_companies[0]?.view_count || 1;
                                  const barW = (tc.view_count / maxViews) * 100;
                                  return (
                                    <div key={tc.cbe} className="flex items-center gap-2">
                                      <span className="text-[10px] text-slate-400 font-mono w-4 text-right shrink-0">
                                        {i + 1}
                                      </span>
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-0.5">
                                          <span className="text-xs text-slate-800 truncate font-medium">
                                            {tc.name}
                                          </span>
                                          <span className="text-[10px] text-slate-400 font-mono shrink-0">
                                            {tc.cbe}
                                          </span>
                                        </div>
                                        <div className="h-1 w-full rounded-full bg-slate-100 overflow-hidden">
                                          <div
                                            className="h-full rounded-full bg-indigo-400 transition-all duration-500"
                                            style={{ width: `${barW}%` }}
                                          />
                                        </div>
                                      </div>
                                      <span className="text-xs font-mono text-slate-600 font-semibold shrink-0 w-8 text-right">
                                        {tc.view_count}
                                      </span>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </CardContent>
                        </Card>
                      </div>
                    </>
                  );
                })()}
              </div>
            )}

            {/* User Experience Simulator */}
            {!loading && stats && (
              <div>
                <SectionHeading icon={TrendingUp}>
                  User Experience Simulator
                </SectionHeading>
                <Card className="bg-white">
                  <CardContent>
                    <p className="text-sm text-slate-500 mb-4">
                      If a user searches for a random company...
                    </p>
                    <div className="space-y-3">
                      <HorizontalBar
                        label="Find financial data"
                        value={stats.companies_with_latest_financials}
                        total={TARGET}
                      />
                      <HorizontalBar
                        label="Find administrator info"
                        value={stats.companies_with_admins}
                        total={TARGET}
                      />
                      <HorizontalBar
                        label="Find publications"
                        value={stats.companies_with_publications}
                        total={TARGET}
                      />
                      <HorizontalBar
                        label="Find shareholders"
                        value={stats.companies_with_shareholders}
                        total={TARGET}
                      />
                      <div className="pt-2 border-t border-slate-100">
                        <HorizontalBar
                          label="Complete profile (all data types)"
                          value={stats.fully_loaded_companies}
                          total={TARGET}
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Data Pipeline Status */}
            {!loading && stats && (
              <div>
                <SectionHeading icon={Database}>Data Pipeline Status</SectionHeading>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  {/* Financial rows */}
                  <Card className="bg-white">
                    <CardContent>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                          Financial Data
                        </span>
                        <TrendingUp className="size-3.5 text-slate-300" />
                      </div>
                      <div className="text-xl font-bold font-mono text-slate-900">
                        {fmt(stats.financial_rows)}
                      </div>
                      <div className="text-[10px] text-slate-400 mb-2">
                        rows loaded
                      </div>
                      <ProgressBar
                        value={stats.financial_rows}
                        target={stats.target_financial_rows}
                        colorCoded
                      />
                      <div className="text-[10px] text-slate-400 mt-1 text-right">
                        {pctStr(stats.financial_rows, stats.target_financial_rows)}% of{" "}
                        {fmt(stats.target_financial_rows)}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Staatsblad */}
                  <Card className="bg-white">
                    <CardContent>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                          Staatsblad
                        </span>
                        <Activity className="size-3.5 text-slate-300" />
                      </div>
                      <div className="text-xl font-bold font-mono text-slate-900">
                        {fmt(stats.companies_with_publications)}
                      </div>
                      <div className="text-[10px] text-slate-400 mb-2">
                        companies scraped
                      </div>
                      <ProgressBar
                        value={stats.companies_with_publications}
                        target={TARGET}
                        colorCoded
                      />
                      <div className="text-[10px] text-slate-400 mt-1 text-right">
                        {pctStr(stats.companies_with_publications, TARGET)}% of{" "}
                        {fmt(TARGET)}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Enterprises */}
                  <Card className="bg-white">
                    <CardContent>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                          Enterprises
                        </span>
                        <Gauge className="size-3.5 text-slate-300" />
                      </div>
                      <div className="text-xl font-bold font-mono text-slate-900">
                        {fmt(stats.total_enterprises)}
                      </div>
                      <div className="text-[10px] text-slate-400 mb-2">
                        KBO records
                      </div>
                      <ProgressBar
                        value={stats.total_enterprises}
                        target={stats.target_enterprises}
                        colorCoded
                      />
                      <div className="text-[10px] text-slate-400 mt-1 text-right">
                        {pctStr(stats.total_enterprises, stats.target_enterprises)}% of{" "}
                        {fmt(stats.target_enterprises)}
                      </div>
                    </CardContent>
                  </Card>

                  {/* DB Size */}
                  <Card className="bg-white">
                    <CardContent>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400 font-medium">
                          Database Size
                        </span>
                        <HardDrive className="size-3.5 text-slate-300" />
                      </div>
                      <div className="text-xl font-bold font-mono text-slate-900">
                        {stats.db_size || "--"}
                      </div>
                      <div className="text-[10px] text-slate-400 mt-1">
                        PostgreSQL
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </div>
            )}

            {/* Financials by Year Breakdown */}
            {!loading && finByYear.length > 0 && (
              <div>
                <SectionHeading icon={BarChart3}>Financials by Year</SectionHeading>
                <Card className="bg-white">
                  <CardContent>
                    <p className="text-xs text-slate-500 mb-3">Companies with financial data per fiscal year — focus on 2024/2025 coverage.</p>
                    <div className="space-y-2">
                      {(() => {
                        const maxCompanies = Math.max(...finByYear.map(f => f.companies));
                        return finByYear.map((fy) => {
                          const isFocus = fy.fiscal_year >= 2024;
                          const pctOfMax = maxCompanies > 0 ? (fy.companies / maxCompanies) * 100 : 0;
                          return (
                            <div key={fy.fiscal_year} className={`flex items-center gap-3 ${isFocus ? "bg-indigo-50/50 rounded px-2 py-1.5 -mx-2" : ""}`}>
                              <span className={`text-xs font-mono w-10 ${isFocus ? "font-bold text-indigo-700" : "text-slate-500"}`}>
                                {fy.fiscal_year}
                              </span>
                              <div className="flex-1 h-4 bg-slate-100 rounded-full overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${isFocus ? "bg-indigo-500" : "bg-slate-300"}`}
                                  style={{ width: `${Math.min(100, pctOfMax)}%` }}
                                />
                              </div>
                              <span className={`text-xs font-mono w-12 text-right ${isFocus ? "font-bold text-indigo-700" : "text-slate-500"}`}>
                                {pctOfMax.toFixed(0)}%
                              </span>
                              <span className={`text-xs font-mono w-20 text-right ${isFocus ? "font-bold text-indigo-700" : "text-slate-600"}`}>
                                {fy.companies.toLocaleString()}
                              </span>
                              <span className="text-[10px] text-slate-400 w-16 text-right">
                                {fy.filings.toLocaleString()}
                              </span>
                            </div>
                          );
                        });
                      })()}
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>
        </TabsContent>

        {/* ================================================================
            TAB: Usage Analytics
            ================================================================ */}
        <TabsContent value="usage">
          <div className="space-y-6 pt-2">
            <SectionHeading icon={Activity}>Platform Usage — Last 30 Days</SectionHeading>

            {!usageData ? (
              <Card className="bg-white"><CardContent><p className="py-8 text-center text-sm text-slate-400">Loading usage data...</p></CardContent></Card>
            ) : (
              <>
                {/* Summary KPIs */}
                <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
                  {[
                    { label: "Total Requests", value: usageData.totals.total_requests_30d, color: "text-slate-800" },
                    { label: "Registered Requests", value: usageData.totals.registered_requests_30d, color: "text-indigo-600" },
                    { label: "Guest Requests", value: usageData.totals.guest_requests_30d, color: "text-orange-500" },
                    { label: "Unique Registered", value: usageData.totals.unique_registered_30d, color: "text-indigo-600" },
                    { label: "Unique Guests (IPs)", value: usageData.totals.unique_guests_30d, color: "text-orange-500" },
                  ].map((kpi) => (
                    <Card key={kpi.label} className="bg-white">
                      <CardContent className="p-3 text-center">
                        <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">{kpi.label}</div>
                        <div className={`text-xl font-bold ${kpi.color}`}>{kpi.value?.toLocaleString() ?? 0}</div>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {/* Daily unique users line chart */}
                <Card className="bg-white">
                  <CardContent className="p-4">
                    <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <Eye className="size-3.5" /> Daily Unique Visitors (last 30 days)
                    </h3>
                    {(() => {
                      const daily = usageData.daily.slice().reverse();
                      const chartData = daily.map((d) => ({
                        date: d.day.slice(5),
                        registered: d.unique_registered,
                        guests: d.unique_guests,
                        total: d.unique_registered + d.unique_guests,
                      }));
                      // Growth indicator: compare last 15 days vs previous 15 days
                      const mid = Math.floor(daily.length / 2);
                      const recentTotal = daily.slice(mid).reduce((s, d) => s + d.unique_registered + d.unique_guests, 0);
                      const prevTotal = daily.slice(0, mid).reduce((s, d) => s + d.unique_registered + d.unique_guests, 0);
                      const growthPct = prevTotal > 0 ? ((recentTotal - prevTotal) / prevTotal) * 100 : 0;
                      const growthSign = growthPct > 0 ? "+" : "";
                      const growthColor = growthPct > 0 ? "text-emerald-600" : growthPct < 0 ? "text-red-500" : "text-slate-400";

                      return (
                        <>
                          <div className="flex items-center gap-3 mb-3">
                            <span className={`text-xs font-semibold ${growthColor}`}>
                              {growthSign}{growthPct.toFixed(1)}% vs previous {mid} days
                            </span>
                            {growthPct > 0 ? (
                              <TrendingUp className="size-3.5 text-emerald-500" />
                            ) : growthPct < 0 ? (
                              <TrendingDown className="size-3.5 text-red-400" />
                            ) : (
                              <Minus className="size-3.5 text-slate-400" />
                            )}
                          </div>
                          <ResponsiveContainer width="100%" height={260}>
                            <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                              <XAxis
                                dataKey="date"
                                tick={{ fontSize: 10, fill: "#94a3b8" }}
                                axisLine={{ stroke: "#cbd5e1" }}
                                tickLine={false}
                              />
                              <YAxis
                                tick={{ fontSize: 10, fill: "#94a3b8" }}
                                axisLine={false}
                                tickLine={false}
                                allowDecimals={false}
                              />
                              <Tooltip
                                contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
                                labelStyle={{ fontWeight: 600 }}
                              />
                              <Legend
                                iconType="circle"
                                iconSize={8}
                                wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                              />
                              <Line
                                type="monotone"
                                dataKey="total"
                                name="Total"
                                stroke="#334155"
                                strokeWidth={2}
                                dot={false}
                                strokeDasharray="5 3"
                              />
                              <Line
                                type="monotone"
                                dataKey="registered"
                                name="Registered"
                                stroke="#6366f1"
                                strokeWidth={2}
                                dot={{ r: 2, fill: "#6366f1" }}
                              />
                              <Line
                                type="monotone"
                                dataKey="guests"
                                name="Guests"
                                stroke="#64748b"
                                strokeWidth={2}
                                dot={{ r: 2, fill: "#64748b" }}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                        </>
                      );
                    })()}
                  </CardContent>
                </Card>

                {/* Monthly unique visitors stacked bar chart */}
                <Card className="bg-white">
                  <CardContent className="p-4">
                    <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <BarChart3 className="size-3.5" /> Monthly Unique Visitors
                    </h3>
                    {(() => {
                      // Aggregate daily data into months
                      const monthMap = new Map<string, { registered: number; guests: number }>();
                      for (const d of usageData.daily) {
                        const month = d.day.slice(0, 7); // "YYYY-MM"
                        const existing = monthMap.get(month) || { registered: 0, guests: 0 };
                        existing.registered += d.unique_registered;
                        existing.guests += d.unique_guests;
                        monthMap.set(month, existing);
                      }
                      const monthlyData = Array.from(monthMap.entries())
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([month, vals]) => ({
                          month,
                          registered: vals.registered,
                          guests: vals.guests,
                          total: vals.registered + vals.guests,
                        }));

                      if (monthlyData.length === 0) {
                        return <p className="text-xs text-slate-400 py-4 text-center">No monthly data available</p>;
                      }

                      return (
                        <ResponsiveContainer width="100%" height={220}>
                          <BarChart data={monthlyData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                            <XAxis
                              dataKey="month"
                              tick={{ fontSize: 10, fill: "#94a3b8" }}
                              axisLine={{ stroke: "#cbd5e1" }}
                              tickLine={false}
                            />
                            <YAxis
                              tick={{ fontSize: 10, fill: "#94a3b8" }}
                              axisLine={false}
                              tickLine={false}
                              allowDecimals={false}
                            />
                            <Tooltip
                              contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
                              labelStyle={{ fontWeight: 600 }}
                            />
                            <Legend
                              iconType="square"
                              iconSize={8}
                              wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                            />
                            <Bar dataKey="registered" name="Registered" stackId="visitors" fill="#6366f1" radius={[0, 0, 0, 0]} />
                            <Bar dataKey="guests" name="Guests" stackId="visitors" fill="#94a3b8" radius={[4, 4, 0, 0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      );
                    })()}
                  </CardContent>
                </Card>

                {/* Daily chart as simple bar */}
                <Card className="bg-white">
                  <CardContent className="p-4">
                    <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <BarChart3 className="size-3.5" /> Daily Requests (last 30 days)
                    </h3>
                    <div className="space-y-1">
                      {usageData.daily.slice(0, 14).map((d) => {
                        const total = d.registered_requests + d.guest_requests;
                        const maxTotal = Math.max(...usageData.daily.map(x => x.registered_requests + x.guest_requests), 1);
                        const regPct = total > 0 ? (d.registered_requests / maxTotal) * 100 : 0;
                        const guestPct = total > 0 ? (d.guest_requests / maxTotal) * 100 : 0;
                        return (
                          <div key={d.day} className="flex items-center gap-2">
                            <span className="text-[10px] text-slate-400 font-mono w-20 shrink-0">{d.day.slice(5)}</span>
                            <div className="flex-1 flex h-4 rounded overflow-hidden bg-slate-50">
                              <div className="bg-indigo-400 rounded-l" style={{ width: `${regPct}%` }} title={`${d.registered_requests} registered`} />
                              <div className="bg-orange-300" style={{ width: `${guestPct}%` }} title={`${d.guest_requests} guest`} />
                            </div>
                            <span className="text-[10px] text-slate-500 font-mono w-12 text-right">{total}</span>
                          </div>
                        );
                      })}
                    </div>
                    <div className="flex items-center gap-4 mt-3 text-[10px] text-slate-400">
                      <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 rounded bg-indigo-400" /> Registered</span>
                      <span className="flex items-center gap-1"><span className="inline-block w-3 h-2 rounded bg-orange-300" /> Guest</span>
                    </div>
                  </CardContent>
                </Card>

                {/* Two columns: Top Pages + Top Users */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {/* Top Pages */}
                  <Card className="bg-white">
                    <CardContent className="p-4">
                      <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                        <Globe className="size-3.5" /> Most Used Features (7d)
                      </h3>
                      <div className="space-y-1.5">
                        {usageData.top_pages.map((p, i) => {
                          const maxReq = usageData.top_pages[0]?.requests || 1;
                          return (
                            <div key={i} className="flex items-center gap-2">
                              <span className="text-xs text-slate-600 truncate flex-1">{p.page}</span>
                              <div className="w-24 h-3 bg-slate-50 rounded overflow-hidden">
                                <div className="h-full bg-indigo-200 rounded" style={{ width: `${(p.requests / maxReq) * 100}%` }} />
                              </div>
                              <span className="text-[10px] text-slate-400 font-mono w-10 text-right">{p.requests}</span>
                            </div>
                          );
                        })}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Top Registered Users */}
                  <Card className="bg-white">
                    <CardContent className="p-4">
                      <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                        <Users className="size-3.5" /> Top Registered Users (7d)
                      </h3>
                      <div className="space-y-1.5">
                        {usageData.top_registered.map((u, i) => (
                          <div key={i} className="flex items-center justify-between py-1 border-b border-slate-50 last:border-0">
                            <span className="text-xs text-indigo-600 font-medium truncate">{u.user_email}</span>
                            <div className="flex items-center gap-3 text-[10px] text-slate-400 shrink-0">
                              <span>{u.unique_pages} pages</span>
                              <span className="font-mono font-semibold text-slate-600">{u.requests} req</span>
                            </div>
                          </div>
                        ))}
                        {usageData.top_registered.length === 0 && <p className="text-xs text-slate-400 py-2 text-center">No registered activity</p>}
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Guest Visitors */}
                <Card className="bg-white">
                  <CardContent className="p-4">
                    <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <Globe className="size-3.5 text-orange-500" /> Guest Visitors (7d)
                    </h3>
                    {usageData.top_guests.length === 0 ? (
                      <p className="text-xs text-slate-400 py-4 text-center">No guest traffic recorded yet. Guest tracking started this session — check back tomorrow.</p>
                    ) : (
                      <div className="space-y-1.5">
                        {usageData.top_guests.map((g, i) => (
                          <div key={i} className="flex items-center justify-between py-1 border-b border-slate-50 last:border-0">
                            <span className="inline-flex items-center gap-1.5">
                              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-orange-50 text-orange-600 text-[9px] font-semibold">
                                <Globe className="size-2.5" /> {g.ip.replace("anon:", "")}
                              </span>
                            </span>
                            <div className="flex items-center gap-3 text-[10px] text-slate-400 shrink-0">
                              <span>{g.unique_pages} pages</span>
                              <span className="font-mono font-semibold text-slate-600">{g.requests} req</span>
                              <span>{g.last_seen?.slice(0, 16).replace("T", " ")}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </div>
        </TabsContent>

        {/* ================================================================
            TAB 2: Users
            ================================================================ */}
        <TabsContent value="users">
          <div className="space-y-4 pt-2">
            <div className="flex items-center justify-between">
              <SectionHeading icon={Users}>
                Users
              </SectionHeading>
            </div>

            <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-3">
              <div className="flex gap-2">
                <button
                  onClick={() => setUserView("all")}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    userView === "all"
                      ? "bg-indigo-600 text-white shadow-sm"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  All Users ({users.length})
                </button>
                <button
                  onClick={() => setUserView("active")}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    userView === "active"
                      ? "bg-indigo-600 text-white shadow-sm"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  Active 7d ({activeUsers.length})
                </button>
              </div>
              <div className="relative max-w-sm flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-slate-400" />
                <Input
                  placeholder="Filter users..."
                  value={userSearch}
                  onChange={(e) => setUserSearch(e.target.value)}
                  className="pl-8"
                />
              </div>
            </div>

            <Card className="bg-white overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Joined</TableHead>
                    <TableHead>Last Active</TableHead>
                    <TableHead className="text-right">Requests (7d)</TableHead>
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
                    : filteredUsers.length === 0
                      ? (
                        <TableRow>
                          <TableCell
                            colSpan={6}
                            className="text-center py-8 text-sm text-slate-400"
                          >
                            No users found
                          </TableCell>
                        </TableRow>
                      )
                      : filteredUsers.map((u) => {
                          const isMe = u.email === myEmail;
                          const act = activityMap.get(u.email);
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
                              <TableCell className="text-sm text-slate-500">
                                {u.created_at
                                  ? new Date(u.created_at).toLocaleDateString()
                                  : "--"}
                              </TableCell>
                              <TableCell className="text-sm text-slate-500">
                                {act
                                  ? new Date(act.last_active).toLocaleString()
                                  : "--"}
                              </TableCell>
                              <TableCell className="text-right font-mono text-sm">
                                {act ? fmt(act.total_requests) : "--"}
                              </TableCell>
                              <TableCell className="text-right">
                                <div className="flex items-center justify-end gap-1.5">
                                  {!isMe && u.role !== "blocked" && (
                                    <Button
                                      variant="outline"
                                      size="xs"
                                      className="border-red-300 text-red-600 hover:bg-red-50"
                                      disabled={
                                        actionLoading === `role-${u.email}`
                                      }
                                      onClick={() => setRole(u.email, "blocked")}
                                    >
                                      <UserX className="size-3 mr-0.5" />
                                      Block
                                    </Button>
                                  )}
                                  {!isMe && u.role === "blocked" && (
                                    <Button
                                      variant="outline"
                                      size="xs"
                                      className="border-slate-300 text-slate-600 hover:bg-slate-50"
                                      disabled={
                                        actionLoading === `role-${u.email}`
                                      }
                                      onClick={() => setRole(u.email, "user")}
                                    >
                                      <UserCheck className="size-3 mr-0.5" />
                                      Unblock
                                    </Button>
                                  )}
                                  {!isMe && u.role !== "admin" && u.role !== "blocked" && (
                                    <Button
                                      variant="outline"
                                      size="xs"
                                      className="border-indigo-300 text-indigo-600 hover:bg-indigo-50"
                                      disabled={
                                        actionLoading === `role-${u.email}`
                                      }
                                      onClick={() => setRole(u.email, "admin")}
                                    >
                                      <Shield className="size-3 mr-0.5" />
                                      Admin
                                    </Button>
                                  )}
                                  {!isMe && u.role === "admin" && (
                                    <Button
                                      variant="outline"
                                      size="xs"
                                      className="border-slate-300 text-slate-600 hover:bg-slate-50"
                                      disabled={
                                        actionLoading === `role-${u.email}`
                                      }
                                      onClick={() => setRole(u.email, "user")}
                                    >
                                      Revoke
                                    </Button>
                                  )}
                                  {!isMe && (
                                    <>
                                      {confirmDelete === u.email ? (
                                        <div className="flex items-center gap-1">
                                          <Button
                                            variant="destructive"
                                            size="xs"
                                            disabled={
                                              actionLoading ===
                                              `delete-${u.email}`
                                            }
                                            onClick={() => deleteUser(u.email)}
                                          >
                                            Confirm
                                          </Button>
                                          <Button
                                            variant="ghost"
                                            size="xs"
                                            onClick={() =>
                                              setConfirmDelete(null)
                                            }
                                          >
                                            Cancel
                                          </Button>
                                        </div>
                                      ) : (
                                        <Button
                                          variant="outline"
                                          size="xs"
                                          className="border-red-300 text-red-600 hover:bg-red-50"
                                          onClick={() =>
                                            setConfirmDelete(u.email)
                                          }
                                        >
                                          <Trash2 className="size-3" />
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
        </TabsContent>

        {/* ================================================================
            TAB 3: Feedback
            ================================================================ */}
        <TabsContent value="feedback">
          <div className="space-y-6 pt-2">
            <div className="flex items-center justify-between">
              <SectionHeading icon={MessageSquare}>
                Feedback ({feedback.length})
              </SectionHeading>
              {feedback.length > 0 && !confirmClearFeedback && (
                <Button
                  variant="outline"
                  size="xs"
                  className="border-red-300 text-red-600 hover:bg-red-50"
                  onClick={() => setConfirmClearFeedback(true)}
                >
                  <Trash2 className="size-3 mr-1" />
                  Clear all
                </Button>
              )}
              {confirmClearFeedback && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">
                    Delete all {feedback.length}?
                  </span>
                  <Button
                    variant="destructive"
                    size="xs"
                    disabled={actionLoading === "clear-fb"}
                    onClick={clearAllFeedback}
                  >
                    Yes
                  </Button>
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setConfirmClearFeedback(false)}
                  >
                    No
                  </Button>
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Bugs */}
              <div>
                <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-700 mb-3">
                  <CircleAlert className="size-3.5 text-red-400" />
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
                      <FeedbackCard key={f.id} f={f} />
                    ))}
                  </div>
                )}
              </div>

              {/* Suggestions */}
              <div>
                <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-700 mb-3">
                  <CircleCheck className="size-3.5 text-indigo-400" />
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
                      <FeedbackCard key={f.id} f={f} />
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Survey results bar chart */}
            {surveys.length > 0 && (
              <div>
                <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-700 mb-3">
                  <BarChart3 className="size-3.5 text-slate-400" />
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
                              <span className="text-slate-500 font-medium font-mono shrink-0">
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
          </div>
        </TabsContent>

        {/* ================================================================
            TAB 4: Polls
            ================================================================ */}
        <TabsContent value="polls">
          <div className="space-y-6 pt-2">
            <SectionHeading icon={BarChart3}>Polls</SectionHeading>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Create poll */}
              <Card className="bg-white">
                <CardContent>
                  <h3 className="text-sm font-semibold text-slate-700 mb-3">
                    Create Poll
                  </h3>
                  <div className="space-y-3">
                    <div>
                      <label className="text-xs text-slate-500 mb-1 block">
                        Title
                      </label>
                      <Input
                        placeholder="e.g. Feature Priority Q2"
                        value={pollTitle}
                        onChange={(e) => setPollTitle(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500 mb-1 block">
                        Question
                      </label>
                      <Input
                        placeholder="e.g. Which feature should we build next?"
                        value={pollQuestion}
                        onChange={(e) => setPollQuestion(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500 mb-1 block">
                        Options (comma-separated)
                      </label>
                      <Input
                        placeholder="e.g. Dark mode, API access, Mobile app"
                        value={pollOptions}
                        onChange={(e) => setPollOptions(e.target.value)}
                      />
                    </div>
                    <Button
                      onClick={createPoll}
                      disabled={
                        pollCreating ||
                        !pollTitle.trim() ||
                        !pollQuestion.trim() ||
                        pollOptions
                          .split(",")
                          .filter((o) => o.trim()).length < 2
                      }
                      className="w-full bg-indigo-600 text-white hover:bg-indigo-700"
                    >
                      {pollCreating ? "Creating..." : "Create"}
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Active polls */}
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
                            <h4 className="text-sm font-semibold text-slate-800">
                              {poll.title}
                            </h4>
                            <p className="text-sm text-slate-600 mt-0.5">
                              {poll.question}
                            </p>
                          </div>
                          <Badge className="bg-green-100 text-green-700 shrink-0 ml-2">
                            active
                          </Badge>
                        </div>

                        <div className="mb-3">
                          {poll.options.map((opt) => {
                            const count = poll.votes[opt] || 0;
                            const votePct =
                              poll.total_votes > 0
                                ? (count / poll.total_votes) * 100
                                : 0;
                            return (
                              <div key={opt} className="mb-2">
                                <div className="flex justify-between text-sm mb-1">
                                  <span className="text-slate-700">{opt}</span>
                                  <span className="text-slate-500 font-mono">
                                    {count} ({votePct.toFixed(0)}%)
                                  </span>
                                </div>
                                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                                  <div
                                    className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                                    style={{ width: `${votePct}%` }}
                                  />
                                </div>
                              </div>
                            );
                          })}
                        </div>

                        <div className="flex items-center justify-between">
                          <span className="text-xs text-slate-400">
                            {poll.total_votes} vote
                            {poll.total_votes !== 1 ? "s" : ""}
                          </span>
                          <Button
                            variant="outline"
                            size="xs"
                            className="border-amber-300 text-amber-600 hover:bg-amber-50"
                            disabled={
                              actionLoading === `poll-archive-${poll.id}`
                            }
                            onClick={() => archivePoll(poll.id)}
                          >
                            Archive
                          </Button>
                          <Button
                            variant="outline"
                            size="xs"
                            onClick={() => setAddingOptionTo(addingOptionTo === poll.id ? null : poll.id)}
                          >
                            + Option
                          </Button>
                        </div>
                        {addingOptionTo === poll.id && (
                          <div className="flex gap-2 mt-2">
                            <Input
                              className="h-7 text-xs flex-1"
                              placeholder="New option text..."
                              value={newOptionText}
                              onChange={(e) => setNewOptionText(e.target.value)}
                              onKeyDown={async (e) => {
                                if (e.key === "Enter" && newOptionText.trim()) {
                                  await adminFetch(`/api/polls/${poll.id}/add-options`, {
                                    method: "POST",
                                    body: JSON.stringify({ options: [newOptionText.trim()] }),
                                  });
                                  setNewOptionText("");
                                  setAddingOptionTo(null);
                                  loadData();
                                }
                              }}
                            />
                            <Button
                              size="xs"
                              className="bg-indigo-600 hover:bg-indigo-700 text-white"
                              onClick={async () => {
                                if (newOptionText.trim()) {
                                  await adminFetch(`/api/polls/${poll.id}/add-options`, {
                                    method: "POST",
                                    body: JSON.stringify({ options: [newOptionText.trim()] }),
                                  });
                                  setNewOptionText("");
                                  setAddingOptionTo(null);
                                  loadData();
                                }
                              }}
                            >
                              Add
                            </Button>
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  ))
                )}
              </div>
            </div>

            {/* Archived polls */}
            {archivedPolls.length > 0 && (
              <div>
                <button
                  className="flex items-center gap-1.5 text-sm font-semibold text-slate-700 mb-3 hover:text-slate-900"
                  onClick={() => setArchivedExpanded(!archivedExpanded)}
                >
                  <ChevronRight
                    className={`size-3.5 transition-transform ${archivedExpanded ? "rotate-90" : ""}`}
                  />
                  Archived Polls ({archivedPolls.length})
                </button>
                {archivedExpanded && (
                  <div className="space-y-3">
                    {archivedPolls.map((poll) => (
                      <Card key={poll.id} className="bg-white">
                        <CardContent>
                          <div className="flex items-start justify-between mb-3">
                            <div>
                              <h4 className="text-sm font-semibold text-slate-800">
                                {poll.title}
                              </h4>
                              <p className="text-sm text-slate-600 mt-0.5">
                                {poll.question}
                              </p>
                            </div>
                            <Badge className="bg-slate-100 text-slate-500 shrink-0 ml-2">
                              archived
                            </Badge>
                          </div>

                          <div className="mb-3">
                            {poll.options.map((opt) => {
                              const count = poll.votes[opt] || 0;
                              const votePct =
                                poll.total_votes > 0
                                  ? (count / poll.total_votes) * 100
                                  : 0;
                              return (
                                <div key={opt} className="mb-2">
                                  <div className="flex justify-between text-sm mb-1">
                                    <span className="text-slate-700">{opt}</span>
                                    <span className="text-slate-500 font-mono">
                                      {count} ({votePct.toFixed(0)}%)
                                    </span>
                                  </div>
                                  <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                                    <div
                                      className="h-full bg-slate-400 rounded-full"
                                      style={{ width: `${votePct}%` }}
                                    />
                                  </div>
                                </div>
                              );
                            })}
                          </div>

                          <div className="flex items-center justify-between">
                            <div className="text-xs text-slate-400 space-x-3">
                              <span>
                                {poll.total_votes} vote
                                {poll.total_votes !== 1 ? "s" : ""}
                              </span>
                              <span>
                                Created{" "}
                                {new Date(poll.created_at).toLocaleDateString()}
                              </span>
                              {poll.archived_at && (
                                <span>
                                  Archived{" "}
                                  {new Date(
                                    poll.archived_at
                                  ).toLocaleDateString()}
                                </span>
                              )}
                            </div>
                            <Button
                              variant="outline"
                              size="xs"
                              className="border-indigo-300 text-indigo-600 hover:bg-indigo-50"
                              disabled={
                                actionLoading === `poll-activate-${poll.id}`
                              }
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
        </TabsContent>

        {/* ================================================================
            TAB 5: Activity Timeline
            ================================================================ */}
        <TabsContent value="activity">
          <div className="space-y-4 pt-2">
            <SectionHeading icon={Clock}>Activity Timeline</SectionHeading>

            {/* Guest vs Registered summary */}
            {activityLog.length > 0 && (() => {
              const anonEntries = activityLog.filter(e => e.user_email?.startsWith("anon:"));
              const authEntries = activityLog.filter(e => e.user_email && !e.user_email.startsWith("anon:"));
              const uniqueGuests = new Set(anonEntries.map(e => e.user_email)).size;
              const uniqueRegistered = new Set(authEntries.map(e => e.user_email)).size;
              return (
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
                  <Card className="bg-white"><CardContent className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">Registered Users</div>
                    <div className="text-lg font-bold text-indigo-600">{uniqueRegistered}</div>
                    <div className="text-[10px] text-slate-400">{authEntries.length} requests</div>
                  </CardContent></Card>
                  <Card className="bg-white"><CardContent className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">Guest Visitors</div>
                    <div className="text-lg font-bold text-orange-500">{uniqueGuests}</div>
                    <div className="text-[10px] text-slate-400">{anonEntries.length} requests</div>
                  </CardContent></Card>
                  <Card className="bg-white"><CardContent className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">Total Requests</div>
                    <div className="text-lg font-bold text-slate-800">{activityLog.length}</div>
                    <div className="text-[10px] text-slate-400">last 200 shown</div>
                  </CardContent></Card>
                  <Card className="bg-white"><CardContent className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">Guest %</div>
                    <div className="text-lg font-bold text-orange-500">{activityLog.length > 0 ? Math.round(anonEntries.length / activityLog.length * 100) : 0}%</div>
                    <div className="text-[10px] text-slate-400">of total traffic</div>
                  </CardContent></Card>
                </div>
              );
            })()}

            {activityLog.length === 0 ? (
              <Card className="bg-white">
                <CardContent>
                  <p className="py-8 text-center text-sm text-slate-400">No activity recorded yet.</p>
                </CardContent>
              </Card>
            ) : (() => {
              // Group by date
              const grouped: Record<string, ActivityEntry[]> = {};
              activityLog.forEach((entry) => {
                const date = entry.created_at?.slice(0, 10) || "Unknown";
                if (!grouped[date]) grouped[date] = [];
                grouped[date].push(entry);
              });
              const dates = Object.keys(grouped).sort().reverse();

              // Friendly endpoint label
              function endpointLabel(ep: string): { label: string; icon: React.ReactNode; color: string } {
                if (ep.includes("/company/") && ep.includes("/financials")) return { label: "Viewed financials", icon: <BarChart3 className="size-3.5" />, color: "text-indigo-600 bg-indigo-50" };
                if (ep.includes("/company/") && ep.includes("/structure")) return { label: "Viewed structure", icon: <Users className="size-3.5" />, color: "text-purple-600 bg-purple-50" };
                if (ep.includes("/company/")) return { label: "Viewed company", icon: <Eye className="size-3.5" />, color: "text-blue-600 bg-blue-50" };
                if (ep.includes("/screener")) return { label: "Used screener", icon: <Search className="size-3.5" />, color: "text-emerald-600 bg-emerald-50" };
                if (ep.includes("/people")) return { label: "Searched people", icon: <Users className="size-3.5" />, color: "text-amber-600 bg-amber-50" };
                if (ep.includes("/favourites")) return { label: "Managed favourites", icon: <CircleCheck className="size-3.5" />, color: "text-pink-600 bg-pink-50" };
                if (ep.includes("/dashboard")) return { label: "Viewed dashboard", icon: <Globe className="size-3.5" />, color: "text-slate-600 bg-slate-50" };
                if (ep.includes("/feedback")) return { label: "Sent feedback", icon: <MessageSquare className="size-3.5" />, color: "text-orange-600 bg-orange-50" };
                if (ep.includes("/stats")) return { label: "Viewed stats", icon: <TrendingUp className="size-3.5" />, color: "text-cyan-600 bg-cyan-50" };
                if (ep.includes("/staatsblad")) return { label: "Loaded publications", icon: <Database className="size-3.5" />, color: "text-teal-600 bg-teal-50" };
                if (ep.includes("/nbb")) return { label: "Loaded NBB data", icon: <Database className="size-3.5" />, color: "text-violet-600 bg-violet-50" };
                return { label: ep.replace("/api/", ""), icon: <Globe className="size-3.5" />, color: "text-slate-500 bg-slate-50" };
              }

              function formatTime(ts: string): string {
                try { return new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; }
              }

              function formatDate(d: string): string {
                try {
                  const dt = new Date(d + "T00:00:00");
                  const today = new Date(); today.setHours(0,0,0,0);
                  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
                  if (dt.getTime() === today.getTime()) return "Today";
                  if (dt.getTime() === yesterday.getTime()) return "Yesterday";
                  return dt.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
                } catch { return d; }
              }

              return (
                <div className="space-y-6">
                  {dates.map((date) => (
                    <div key={date}>
                      {/* Date header */}
                      <div className="flex items-center gap-3 mb-3">
                        <div className="text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">
                          {formatDate(date)}
                        </div>
                        <div className="h-px flex-1 bg-slate-200" />
                        <span className="text-[10px] text-slate-400 font-mono">{grouped[date].length} events</span>
                      </div>

                      {/* Timeline entries */}
                      <div className="relative pl-6">
                        {/* Vertical line */}
                        <div className="absolute left-[9px] top-2 bottom-2 w-px bg-slate-200" />

                        <div className="space-y-1">
                          {grouped[date].map((entry, i) => {
                            const info = endpointLabel(entry.endpoint);
                            return (
                              <div key={`${date}-${i}`} className="relative flex items-start gap-3 py-1.5 group">
                                {/* Dot */}
                                <div className={`absolute -left-6 top-2.5 w-[7px] h-[7px] rounded-full border-2 border-white ${
                                  i === 0 && date === dates[0] ? "bg-indigo-500" : "bg-slate-300"
                                }`} />

                                {/* Icon */}
                                <div className={`shrink-0 p-1 rounded-md ${info.color}`}>
                                  {info.icon}
                                </div>

                                {/* Content */}
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium text-slate-800">{info.label}</span>
                                    <span className="text-[10px] text-slate-400 font-mono truncate max-w-[200px]">
                                      {entry.endpoint.replace("/api/", "")}
                                    </span>
                                  </div>
                                  <div className="text-[11px] text-slate-400 mt-0.5 flex items-center gap-1.5">
                                    {entry.user_email?.startsWith("anon:") ? (
                                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-orange-50 text-orange-600 text-[9px] font-semibold">
                                        <Globe className="size-2.5" /> Guest {entry.user_email.replace("anon:", "").split(".").slice(0, 2).join(".")}…
                                      </span>
                                    ) : (
                                      <span>{entry.user_email?.split("@")[0] || "unknown"}</span>
                                    )}
                                    <span className="text-slate-300">·</span>
                                    {formatTime(entry.created_at)}
                                  </div>
                                </div>

                                {/* Method badge */}
                                <span className={`shrink-0 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${
                                  entry.method === "POST" ? "bg-amber-50 text-amber-600" :
                                  entry.method === "DELETE" ? "bg-rose-50 text-rose-500" :
                                  "bg-slate-50 text-slate-400"
                                }`}>
                                  {entry.method}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}
          </div>
        </TabsContent>

        {/* ================================================================
            TAB: Revenue (Stripe Payments)
            ================================================================ */}
        <TabsContent value="revenue">
          <div className="space-y-6 pt-2">
            <SectionHeading icon={CreditCard}>Stripe Payments</SectionHeading>

            {!paymentsData ? (
              <Card className="bg-white">
                <CardContent>
                  <p className="py-8 text-center text-sm text-slate-400">
                    Loading payment data...
                  </p>
                </CardContent>
              </Card>
            ) : paymentsData.payments.length === 0 ? (
              <Card className="bg-white">
                <CardContent>
                  <div className="py-12 text-center">
                    <CreditCard className="size-8 text-slate-300 mx-auto mb-3" />
                    <h3 className="text-sm font-semibold text-slate-700 mb-1">
                      No Payments Yet
                    </h3>
                    <p className="text-sm text-slate-400">
                      Stripe payments will appear here once customers complete checkout.
                    </p>
                  </div>
                </CardContent>
              </Card>
            ) : (
              <>
                {/* Revenue KPIs */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  <Card className="bg-white">
                    <CardContent className="p-3 text-center">
                      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                        Total Revenue
                      </div>
                      <div className="text-xl font-bold text-emerald-600">
                        {(paymentsData.total_revenue / 100).toLocaleString("en", {
                          style: "currency",
                          currency: paymentsData.currency,
                        })}
                      </div>
                    </CardContent>
                  </Card>
                  <Card className="bg-white">
                    <CardContent className="p-3 text-center">
                      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                        Total Payments
                      </div>
                      <div className="text-xl font-bold text-slate-800">
                        {paymentsData.payments.length}
                      </div>
                    </CardContent>
                  </Card>
                  <Card className="bg-white">
                    <CardContent className="p-3 text-center">
                      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                        Successful
                      </div>
                      <div className="text-xl font-bold text-emerald-600">
                        {paymentsData.payments.filter((p) => p.status === "paid").length}
                      </div>
                    </CardContent>
                  </Card>
                  <Card className="bg-white">
                    <CardContent className="p-3 text-center">
                      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                        Subscriptions
                      </div>
                      <div className="text-xl font-bold text-indigo-600">
                        {paymentsData.payments.filter((p) => p.mode === "subscription").length}
                      </div>
                    </CardContent>
                  </Card>
                </div>

                {/* Recent payments table */}
                <Card className="bg-white">
                  <CardContent className="p-4">
                    <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <CreditCard className="size-3.5" /> Recent Payments
                    </h3>
                    <div className="overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="text-[11px]">Date</TableHead>
                            <TableHead className="text-[11px]">Email</TableHead>
                            <TableHead className="text-[11px]">Amount</TableHead>
                            <TableHead className="text-[11px]">Type</TableHead>
                            <TableHead className="text-[11px]">Status</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {paymentsData.payments.map((p) => (
                            <TableRow key={p.id}>
                              <TableCell className="text-xs text-slate-500 font-mono whitespace-nowrap">
                                {new Date(p.created).toLocaleDateString()}{" "}
                                <span className="text-slate-400">
                                  {new Date(p.created).toLocaleTimeString([], {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                  })}
                                </span>
                              </TableCell>
                              <TableCell className="text-xs text-slate-600 max-w-[200px] truncate">
                                {p.email || <span className="text-slate-300">--</span>}
                              </TableCell>
                              <TableCell className="text-xs font-mono font-semibold text-slate-800">
                                {(p.amount / 100).toLocaleString("en", {
                                  style: "currency",
                                  currency: p.currency,
                                })}
                              </TableCell>
                              <TableCell>
                                <Badge
                                  variant="secondary"
                                  className={`text-[10px] ${
                                    p.mode === "subscription"
                                      ? "bg-indigo-50 text-indigo-600"
                                      : "bg-slate-100 text-slate-600"
                                  }`}
                                >
                                  {p.mode === "subscription" ? "Subscription" : "One-time"}
                                </Badge>
                              </TableCell>
                              <TableCell>
                                <Badge
                                  variant="secondary"
                                  className={`text-[10px] ${
                                    p.status === "paid"
                                      ? "bg-emerald-50 text-emerald-600"
                                      : p.status === "unpaid"
                                        ? "bg-amber-50 text-amber-600"
                                        : "bg-slate-100 text-slate-500"
                                  }`}
                                >
                                  {p.status}
                                </Badge>
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
        </TabsContent>

        {/* ================================================================
            TAB 6: Settings
            ================================================================ */}
        <TabsContent value="settings">
          <div className="pt-2">
            <Card className="bg-white">
              <CardContent>
                <div className="py-12 text-center">
                  <Settings className="size-8 text-slate-300 mx-auto mb-3" />
                  <h3 className="text-sm font-semibold text-slate-700 mb-1">
                    Platform Settings
                  </h3>
                  <p className="text-sm text-slate-400">
                    Configuration options will be available here in a future update.
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
