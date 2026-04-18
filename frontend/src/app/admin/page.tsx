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
  Crown,
  Layers,
  Save,
  Check,
  Image,
  Loader2,
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

interface ARRData {
  arr_eur: number;
  last_4w_eur: number;
  multiplier: number;
  currency: string;
  weekly: {
    week_start: string;
    week_end: string;
    gross_cents: number;
    gross_eur: number;
    charges: number;
  }[];
  active_subscribers: number;
  window_days: number;
  as_of: string;
  note?: string;
}

interface InvoiceRow {
  id: number;
  sender: string | null;
  subject: string | null;
  received_at: string | null;
  invoice_date: string | null;
  amount_cents: number | null;
  currency: string | null;
  vendor: string | null;
  category: string | null;
  confirmed: boolean;
}

interface InvoicesData {
  invoices: InvoiceRow[];
  monthly: { ym: string; cents_total: number; eur_total: number; invoices: number }[];
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

interface AdoptionData {
  kpis: {
    total_registered: number;
    active_7d: number;
    active_30d: number;
    sessions_today: number;
    active_prev_7d: number;
    active_prev_30d: number;
    sessions_yesterday: number;
  };
  daily_trend: { day: string; dau: number; page_views: number }[];
  features: { feature: string; requests: number; unique_users: number }[];
  top_users: { email: string; session_days: number; total_requests: number; last_active: string }[];
  recent: { user_email: string; endpoint: string; method: string; created_at_be: string }[];
}

interface TractionData {
  kpis: Record<string, number>;
  engagement: Record<string, number>;
  daily_trend: { day: string; unique_guests: number; unique_registered: number; total_requests: number }[];
  hourly_today: { hour: number; requests: number; guests: number; registered: number }[];
  guest_pages: { feature: string; requests: number; unique_guests: number }[];
  registered_pages: { feature: string; requests: number; unique_users: number }[];
  signups: { day: string; new_users: number }[];
  stickiness: { days_active: number; user_count: number }[];
  top_guests: { ip: string; unique_pages: number; total_requests: number; first_seen: string; last_seen: string }[];
}

interface CostItem {
  name: string;
  amount: number;
  frequency: "monthly" | "yearly" | "one-time";
}

interface CostsData {
  openrouter_usage_usd: number;
  openrouter_limit_usd: number;
  cost_items: CostItem[];
  ai_calls_30d: Record<string, number>;
}

interface LlmCostBreakdownRow {
  kind: string;
  calls: number;
  est_cost_per_call_usd: number;
  est_total_usd: number;
}

interface LlmCostBreakdown {
  window_days: number;
  calls_total: number;
  est_total_usd: number;
  est_avg_per_call_usd: number;
  breakdown: LlmCostBreakdownRow[];
  note: string;
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

interface TierConfig {
  tier: string;
  page_views_per_day: number;
  searches_per_day: number;
  company_views_per_day: number;
  ai_enrichments_per_day: number;
  export_per_day: number;
  screener_results_limit: number;
  enabled: boolean;
  updated_at: string;
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

/** Format a timestamp string to Belgian timezone (Europe/Brussels). */
function toBelgianTime(ts: string, options?: Intl.DateTimeFormatOptions): string {
  try {
    const defaults: Intl.DateTimeFormatOptions = {
      timeZone: "Europe/Brussels",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    };
    return new Date(ts).toLocaleString("en-BE", { ...defaults, ...options });
  } catch {
    return ts;
  }
}

function toBelgianDate(ts: string): string {
  try {
    return new Date(ts).toLocaleDateString("en-BE", {
      timeZone: "Europe/Brussels",
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return ts;
  }
}

function toBelgianTimeOnly(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString("en-BE", {
      timeZone: "Europe/Brussels",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return ts;
  }
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

/* Two-sheet consolidation. See docs/architecture.md or roadmap notes —
   the user wanted "max 2 very intuitive sheets" instead of 10 flat tabs.
   We collapse the 10 into:
     - Pulse: growth & health metrics (what's the platform doing this week)
     - Operations: people, configuration, money (the day-to-day ops desk)
   The actual TabsContent panels are unchanged; only the visible TabsList
   gets filtered by the current sheet. */
const PULSE_TABS = ["traction", "readiness", "usage"] as const;
const OPS_TABS = ["users", "feedback", "polls", "tiers", "activity", "revenue", "settings"] as const;
type AdminSheet = "pulse" | "operations";
type AdminTabKey = (typeof PULSE_TABS)[number] | (typeof OPS_TABS)[number];

const SHEET_FOR_TAB: Record<AdminTabKey, AdminSheet> = {
  traction: "pulse", readiness: "pulse", usage: "pulse",
  users: "operations", feedback: "operations", polls: "operations",
  tiers: "operations", activity: "operations", revenue: "operations", settings: "operations",
};

export default function AdminPanel() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [feedback, setFeedback] = useState<FeedbackRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<AdminSheet>("pulse");
  const [activeTab, setActiveTab] = useState<AdminTabKey>("traction");

  // Keep the active tab in sync with the active sheet — switching sheets
  // jumps to the first tab inside it.
  useEffect(() => {
    const visible = sheet === "pulse" ? PULSE_TABS : OPS_TABS;
    if (!visible.includes(activeTab as never)) {
      setActiveTab(visible[0]);
    }
  }, [sheet, activeTab]);
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
  const [adoptionData, setAdoptionData] = useState<AdoptionData | null>(null);
  const [tractionData, setTractionData] = useState<TractionData | null>(null);
  const [costsData, setCostsData] = useState<CostsData | null>(null);
  const [llmCosts, setLlmCosts] = useState<LlmCostBreakdown | null>(null);
  const [costItems, setCostItems] = useState<CostItem[]>([]);
  const [costSaving, setCostSaving] = useState(false);
  const [newCostName, setNewCostName] = useState("");
  const [newCostAmount, setNewCostAmount] = useState("");
  const [newCostFreq, setNewCostFreq] = useState<"monthly" | "yearly" | "one-time">("monthly");
  const [paymentsData, setPaymentsData] = useState<PaymentsData | null>(null);
  const [arrData, setArrData] = useState<ARRData | null>(null);
  const [invoicesData, setInvoicesData] = useState<InvoicesData | null>(null);
  const [tiers, setTiers] = useState<TierConfig[]>([]);
  const [tierEdits, setTierEdits] = useState<Record<string, Partial<TierConfig>>>({});
  const [tierSaving, setTierSaving] = useState<string | null>(null);
  const [tierToggling, setTierToggling] = useState(false);
  const [siteLogo, setSiteLogo] = useState<string>("/logos/dog-telescope.jpg");
  const [logoSaving, setLogoSaving] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: sessionData } = await supabase.auth.getSession();
      setMyEmail(sessionData.session?.user?.email || "");

      const [s, u, f, a, p, fby, alog, ins, usage, pay, tc, sc, adopt, trac, costs, llmCosts, arr, invs] = await Promise.all([
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
        adminFetch<TierConfig[]>("/api/admin/tiers").catch(() => [] as TierConfig[]),
        adminFetch<{ site_logo: string }>("/api/admin/site-config").catch(() => ({ site_logo: "/logos/dog-telescope.jpg" })),
        adminFetch<AdoptionData>("/api/admin/adoption").catch(() => null),
        adminFetch<TractionData>("/api/admin/traction").catch(() => null),
        adminFetch<CostsData>("/api/admin/costs").catch(() => null),
        adminFetch<LlmCostBreakdown>("/api/admin/llm-cost-breakdown").catch(() => null),
        adminFetch<ARRData>("/api/admin/arr").catch(() => null),
        adminFetch<InvoicesData>("/api/admin/invoices").catch(() => null),
      ]);
      setArrData(arr);
      setInvoicesData(invs);
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
      setTiers(tc);
      if (sc?.site_logo) setSiteLogo(sc.site_logo);
      setAdoptionData(adopt);
      setTractionData(trac);
      setCostsData(costs);
      if (costs?.cost_items) setCostItems(costs.cost_items);
      setLlmCosts(llmCosts);
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

  /* ---- Tier actions ---- */

  function getTierValue(tier: string, field: keyof TierConfig): number {
    const edit = tierEdits[tier];
    if (edit && edit[field] !== undefined) return edit[field] as number;
    const row = tiers.find((t) => t.tier === tier);
    return row ? (row[field] as number) : 0;
  }

  function setTierField(tier: string, field: string, value: number) {
    setTierEdits((prev) => ({
      ...prev,
      [tier]: { ...prev[tier], [field]: value },
    }));
  }

  async function saveTier(tier: string) {
    const edits = tierEdits[tier];
    if (!edits || Object.keys(edits).length === 0) return;
    setTierSaving(tier);
    try {
      const updated = await adminFetch<TierConfig>(`/api/admin/tiers/${tier}`, {
        method: "PUT",
        body: JSON.stringify(edits),
      });
      setTiers((prev) =>
        prev.map((t) => (t.tier === tier ? { ...t, ...updated } : t))
      );
      setTierEdits((prev) => {
        const next = { ...prev };
        delete next[tier];
        return next;
      });
    } catch {
      /* ignore */
    } finally {
      setTierSaving(null);
    }
  }

  async function toggleAllLimits() {
    const currentlyEnabled = tiers.some((t) => t.enabled);
    const newEnabled = !currentlyEnabled;
    setTierToggling(true);
    try {
      await adminFetch("/api/admin/tiers/toggle", {
        method: "POST",
        body: JSON.stringify({ enabled: newEnabled }),
      });
      setTiers((prev) => prev.map((t) => ({ ...t, enabled: newEnabled })));
    } catch {
      /* ignore */
    } finally {
      setTierToggling(false);
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
            <span>{toBelgianDate(f.created_at)}</span>
          </div>

          {f.reply ? (
            <div className="mt-3 border-t border-slate-100 pt-3">
              <div className="flex items-center gap-2 mb-1">
                <Badge className="bg-green-100 text-green-700 text-[10px]">
                  Replied
                </Badge>
                {f.replied_at && (
                  <span className="text-[10px] text-slate-400">
                    {toBelgianDate(f.replied_at)}
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
    <div className="mx-auto w-full max-w-[1200px] space-y-6">
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

      {/* Sheet toggle — Pulse vs Operations. Reframes the 10 admin
          panels into 2 intuitive groups; the underlying TabsContent
          panels are unchanged. */}
      <div className="mb-3 inline-flex rounded-lg border border-slate-200 bg-white p-0.5 shadow-sm">
        {(["pulse", "operations"] as AdminSheet[]).map((s) => (
          <button
            key={s}
            onClick={() => setSheet(s)}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition ${
              sheet === s
                ? "bg-indigo-600 text-white"
                : "text-slate-500 hover:text-slate-700"
            }`}
            title={
              s === "pulse"
                ? "Growth & health: traction, data readiness, usage"
                : "Day-to-day ops: users, feedback, polls, tiers, activity, P&L, settings"
            }
          >
            {s === "pulse" ? "Pulse" : "Operations"}
          </button>
        ))}
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as AdminTabKey)}>
        <TabsList className="overflow-x-auto w-full">
          {sheet === "pulse" ? (
            <>
              <TabsTrigger value="traction">
                <HeartPulse className="size-3.5 mr-1.5" />
                Traction
              </TabsTrigger>
              <TabsTrigger value="readiness">
                <Gauge className="size-3.5 mr-1.5" />
                Readiness
              </TabsTrigger>
              <TabsTrigger value="usage">
                <Activity className="size-3.5 mr-1.5" />
                Usage
              </TabsTrigger>
            </>
          ) : (
            <>
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
              <TabsTrigger value="tiers">
                <Layers className="size-3.5 mr-1.5" />
                Tiers
              </TabsTrigger>
              <TabsTrigger value="activity">
                <Clock className="size-3.5 mr-1.5" />
                Activity
              </TabsTrigger>
              <TabsTrigger value="revenue">
                <CreditCard className="size-3.5 mr-1.5" />
                P&L
              </TabsTrigger>
              <TabsTrigger value="settings">
                <Settings className="size-3.5 mr-1.5" />
                Settings
              </TabsTrigger>
            </>
          )}
        </TabsList>

        {/* ================================================================
            TAB 0: Traction
            ================================================================ */}
        <TabsContent value="traction">
          <div className="space-y-6 pt-2">
            {tractionData ? (
              <>
                {/* KPI Cards */}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                  {[
                    { label: "Guests Today", value: tractionData.kpis.guests_today, icon: Globe },
                    { label: "Guests 7d", value: tractionData.kpis.guests_7d, icon: Globe },
                    { label: "Guests 30d", value: tractionData.kpis.guests_30d, icon: Globe },
                    { label: "Registered Today", value: tractionData.kpis.registered_today, icon: UserCheck },
                    { label: "Registered 7d", value: tractionData.kpis.registered_7d, icon: UserCheck },
                    { label: "Registered 30d", value: tractionData.kpis.registered_30d, icon: UserCheck },
                  ].map((kpi) => {
                    const Icon = kpi.icon;
                    return (
                      <Card key={kpi.label} className="bg-white">
                        <CardContent className="pt-3 pb-3">
                          <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                            <Icon className="size-3" /> {kpi.label}
                          </div>
                          <div className="text-xl font-bold text-slate-900 font-mono">{fmt(kpi.value)}</div>
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>

                {/* Engagement KPIs */}
                {tractionData.engagement && (
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <Card className="bg-white">
                      <CardContent className="pt-3 pb-3 text-center">
                        <div className="text-[10px] text-slate-400 mb-1">Avg Pages / Guest</div>
                        <div className="text-2xl font-bold text-indigo-600 font-mono">{tractionData.engagement.avg_pages_per_guest ?? "--"}</div>
                      </CardContent>
                    </Card>
                    <Card className="bg-white">
                      <CardContent className="pt-3 pb-3 text-center">
                        <div className="text-[10px] text-slate-400 mb-1">Avg Requests / Guest</div>
                        <div className="text-2xl font-bold text-indigo-600 font-mono">{tractionData.engagement.avg_requests_per_guest ?? "--"}</div>
                      </CardContent>
                    </Card>
                    <Card className="bg-white">
                      <CardContent className="pt-3 pb-3 text-center">
                        <div className="text-[10px] text-slate-400 mb-1">Requests 30d</div>
                        <div className="text-2xl font-bold text-slate-900 font-mono">{fmt(tractionData.kpis.requests_30d)}</div>
                      </CardContent>
                    </Card>
                  </div>
                )}

                {/* Daily Trend Chart */}
                {tractionData.daily_trend.length > 0 && (
                  <Card className="bg-white">
                    <CardContent className="pt-4 pb-4">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Daily Unique Visitors (30d)</h3>
                      <ResponsiveContainer width="100%" height={250}>
                        <BarChart data={tractionData.daily_trend}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                          <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                          <YAxis tick={{ fontSize: 10 }} />
                          <Tooltip contentStyle={{ fontSize: 11 }} />
                          <Legend wrapperStyle={{ fontSize: 11 }} />
                          <Bar dataKey="unique_guests" name="Guests" fill="#818cf8" stackId="a" />
                          <Bar dataKey="unique_registered" name="Registered" fill="#34d399" stackId="a" />
                        </BarChart>
                      </ResponsiveContainer>
                    </CardContent>
                  </Card>
                )}

                {/* Hourly usage today */}
                {(() => {
                  // Fill all 24 hours with data (0 for missing hours)
                  const hourMap = new Map<number, { hour: number; requests: number; guests: number; registered: number }>();
                  for (let h = 0; h < 24; h++) hourMap.set(h, { hour: h, requests: 0, guests: 0, registered: 0 });
                  for (const d of tractionData.hourly_today || []) hourMap.set(d.hour, d);
                  const hourlyFull = Array.from(hourMap.values()).sort((a, b) => a.hour - b.hour);
                  const currentHour = new Date().getHours(); // approximate — shows where "now" is
                  const hasData = hourlyFull.some((h) => h.requests > 0);

                  return hasData ? (
                    <Card className="bg-white">
                      <CardContent className="pt-4 pb-4">
                        <div className="flex items-center justify-between mb-3">
                          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Today&apos;s Activity (Belgian time, excl. admins)</h3>
                          <span className="text-[10px] text-slate-400 font-mono">{new Date().toLocaleDateString("en-BE", { timeZone: "Europe/Brussels", weekday: "short", day: "numeric", month: "short" })}</span>
                        </div>
                        <ResponsiveContainer width="100%" height={200}>
                          <BarChart data={hourlyFull} barGap={0} barCategoryGap="10%">
                            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                            <XAxis
                              dataKey="hour"
                              tick={{ fontSize: 9 }}
                              tickFormatter={(h: number) => h % 3 === 0 ? `${String(h).padStart(2, "0")}:00` : ""}
                              interval={0}
                            />
                            <YAxis tick={{ fontSize: 9 }} width={35} allowDecimals={false} />
                            <Tooltip
                              contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
                              labelFormatter={(h) => `${String(h).padStart(2, "0")}:00 \u2013 ${String(Number(h) + 1).padStart(2, "0")}:00`}
                            />
                            <Legend wrapperStyle={{ fontSize: 10, paddingTop: 8 }} />
                            <Bar dataKey="guests" name="Guests" fill="#818cf8" radius={[2, 2, 0, 0]} stackId="a" />
                            <Bar dataKey="registered" name="Registered" fill="#34d399" radius={[2, 2, 0, 0]} stackId="a" />
                          </BarChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  ) : null;
                })()}

                {/* Guest vs Registered Feature Usage — side by side */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {/* Guest behavior */}
                  <Card className="bg-white">
                    <CardContent className="pt-4 pb-4">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
                        <Globe className="size-3 inline mr-1" /> What Guests Do (7d)
                      </h3>
                      <Table>
                        <TableHeader>
                          <TableRow><TableHead className="text-[10px]">Feature</TableHead><TableHead className="text-[10px] text-right">Unique Guests</TableHead><TableHead className="text-[10px] text-right">Requests</TableHead></TableRow>
                        </TableHeader>
                        <TableBody>
                          {tractionData.guest_pages.map((p) => (
                            <TableRow key={p.feature}>
                              <TableCell className="text-xs py-1.5">{p.feature}</TableCell>
                              <TableCell className="text-xs text-right font-mono py-1.5">{p.unique_guests}</TableCell>
                              <TableCell className="text-xs text-right font-mono text-slate-400 py-1.5">{p.requests}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>
                  {/* Registered behavior */}
                  <Card className="bg-white">
                    <CardContent className="pt-4 pb-4">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
                        <UserCheck className="size-3 inline mr-1" /> What Registered Users Do (7d)
                      </h3>
                      <Table>
                        <TableHeader>
                          <TableRow><TableHead className="text-[10px]">Feature</TableHead><TableHead className="text-[10px] text-right">Unique Users</TableHead><TableHead className="text-[10px] text-right">Requests</TableHead></TableRow>
                        </TableHeader>
                        <TableBody>
                          {tractionData.registered_pages.map((p) => (
                            <TableRow key={p.feature}>
                              <TableCell className="text-xs py-1.5">{p.feature}</TableCell>
                              <TableCell className="text-xs text-right font-mono py-1.5">{p.unique_users}</TableCell>
                              <TableCell className="text-xs text-right font-mono text-slate-400 py-1.5">{p.requests}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>
                </div>

                {/* Stickiness + Signups side by side */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {/* User Stickiness */}
                  {tractionData.stickiness.length > 0 && (
                    <Card className="bg-white">
                      <CardContent className="pt-4 pb-4">
                        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Registered User Stickiness (7d)</h3>
                        <ResponsiveContainer width="100%" height={180}>
                          <BarChart data={tractionData.stickiness}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                            <XAxis dataKey="days_active" tick={{ fontSize: 10 }} label={{ value: "Days Active", position: "bottom", fontSize: 10, offset: -5 }} />
                            <YAxis tick={{ fontSize: 10 }} />
                            <Tooltip contentStyle={{ fontSize: 11 }} />
                            <Bar dataKey="user_count" name="Users" fill="#6366f1" />
                          </BarChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  )}
                  {/* Signups */}
                  {tractionData.signups.length > 0 && (
                    <Card className="bg-white">
                      <CardContent className="pt-4 pb-4">
                        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">New Signups (30d)</h3>
                        <ResponsiveContainer width="100%" height={180}>
                          <BarChart data={tractionData.signups}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                            <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                            <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                            <Tooltip contentStyle={{ fontSize: 11 }} />
                            <Bar dataKey="new_users" name="Signups" fill="#34d399" />
                          </BarChart>
                        </ResponsiveContainer>
                      </CardContent>
                    </Card>
                  )}
                </div>

                {/* Most Engaged Guests */}
                {tractionData.top_guests.length > 0 && (
                  <Card className="bg-white">
                    <CardContent className="pt-4 pb-4">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Most Engaged Guests (7d)</h3>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="text-[10px]">IP</TableHead>
                            <TableHead className="text-[10px] text-right">Pages</TableHead>
                            <TableHead className="text-[10px] text-right">Requests</TableHead>
                            <TableHead className="text-[10px]">First Seen</TableHead>
                            <TableHead className="text-[10px]">Last Seen</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {tractionData.top_guests.map((g) => (
                            <TableRow key={g.ip}>
                              <TableCell className="text-xs font-mono py-1.5">{g.ip}</TableCell>
                              <TableCell className="text-xs text-right font-mono py-1.5">{g.unique_pages}</TableCell>
                              <TableCell className="text-xs text-right font-mono text-slate-400 py-1.5">{g.total_requests}</TableCell>
                              <TableCell className="text-[10px] text-slate-400 py-1.5">{toBelgianTime(g.first_seen)}</TableCell>
                              <TableCell className="text-[10px] text-slate-400 py-1.5">{toBelgianTime(g.last_seen)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              <div className="text-center py-8 text-sm text-slate-400">Loading traction data...</div>
            )}
          </div>
        </TabsContent>

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
                        companies enriched
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
            TAB: Adoption Dashboard
            ================================================================ */}
        <TabsContent value="usage">
          <div className="space-y-6 pt-2">
            <SectionHeading icon={Activity}>Adoption Dashboard</SectionHeading>

            {!adoptionData ? (
              <Card className="bg-white"><CardContent><p className="py-8 text-center text-sm text-slate-400">Loading adoption data...</p></CardContent></Card>
            ) : (
              <>
                {/* ---- 1. Adoption KPI Cards ---- */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {[
                    {
                      label: "Registered Users",
                      value: adoptionData.kpis.total_registered,
                      icon: <Users className="size-4 text-indigo-500" />,
                      color: "text-indigo-700",
                      bg: "bg-indigo-50 border-indigo-100",
                      sub: null,
                    },
                    {
                      label: "Active (7 days)",
                      value: adoptionData.kpis.active_7d,
                      icon: <UserCheck className="size-4 text-emerald-500" />,
                      color: "text-emerald-700",
                      bg: "bg-emerald-50 border-emerald-100",
                      sub: adoptionData.kpis.active_prev_7d,
                    },
                    {
                      label: "Active (30 days)",
                      value: adoptionData.kpis.active_30d,
                      icon: <HeartPulse className="size-4 text-violet-500" />,
                      color: "text-violet-700",
                      bg: "bg-violet-50 border-violet-100",
                      sub: adoptionData.kpis.active_prev_30d,
                    },
                    {
                      label: "Sessions Today",
                      value: adoptionData.kpis.sessions_today,
                      icon: <Activity className="size-4 text-amber-500" />,
                      color: "text-amber-700",
                      bg: "bg-amber-50 border-amber-100",
                      sub: adoptionData.kpis.sessions_yesterday,
                    },
                  ].map((card) => (
                    <Card key={card.label} className={`border ${card.bg}`}>
                      <CardContent className="p-4">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[10px] text-slate-500 uppercase tracking-wider font-medium">{card.label}</span>
                          {card.icon}
                        </div>
                        <div className={`text-2xl font-bold ${card.color}`}>
                          {card.value?.toLocaleString() ?? 0}
                        </div>
                        {card.sub != null && (
                          <div className="mt-1">
                            <TrendBadge current={card.value ?? 0} previous={card.sub ?? 0} />
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {/* ---- 2. Usage Trend Chart (DAU + Page Views, 30 days) ---- */}
                <Card className="bg-white">
                  <CardContent className="p-4">
                    <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-4 flex items-center gap-1.5">
                      <TrendingUp className="size-3.5" /> Usage Trend — Last 30 Days
                    </h3>
                    {adoptionData.daily_trend.length === 0 ? (
                      <p className="text-xs text-slate-400 py-6 text-center">No data yet</p>
                    ) : (() => {
                      const chartData = adoptionData.daily_trend.map((d) => ({
                        date: d.day.slice(5),
                        "Active Users": d.dau,
                        "Page Views": d.page_views,
                      }));
                      return (
                        <ResponsiveContainer width="100%" height={280}>
                          <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                            <XAxis
                              dataKey="date"
                              tick={{ fontSize: 10, fill: "#94a3b8" }}
                              axisLine={{ stroke: "#cbd5e1" }}
                              tickLine={false}
                            />
                            <YAxis
                              yAxisId="left"
                              tick={{ fontSize: 10, fill: "#94a3b8" }}
                              axisLine={false}
                              tickLine={false}
                              allowDecimals={false}
                              label={{ value: "Active Users", angle: -90, position: "insideLeft", style: { fontSize: 10, fill: "#94a3b8" } }}
                            />
                            <YAxis
                              yAxisId="right"
                              orientation="right"
                              tick={{ fontSize: 10, fill: "#94a3b8" }}
                              axisLine={false}
                              tickLine={false}
                              allowDecimals={false}
                              label={{ value: "Page Views", angle: 90, position: "insideRight", style: { fontSize: 10, fill: "#94a3b8" } }}
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
                              yAxisId="left"
                              type="monotone"
                              dataKey="Active Users"
                              stroke="#6366f1"
                              strokeWidth={2.5}
                              dot={{ r: 2.5, fill: "#6366f1" }}
                              activeDot={{ r: 4 }}
                            />
                            <Line
                              yAxisId="right"
                              type="monotone"
                              dataKey="Page Views"
                              stroke="#94a3b8"
                              strokeWidth={1.5}
                              dot={false}
                              strokeDasharray="4 3"
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      );
                    })()}
                  </CardContent>
                </Card>

                {/* ---- 3. Feature Usage + Top Users (side by side) ---- */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {/* Feature Breakdown (bar chart) */}
                  <Card className="bg-white">
                    <CardContent className="p-4">
                      <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                        <BarChart3 className="size-3.5" /> Feature Usage (last 7 days)
                      </h3>
                      {adoptionData.features.length === 0 ? (
                        <p className="text-xs text-slate-400 py-6 text-center">No feature data yet</p>
                      ) : (() => {
                        const barData = adoptionData.features.slice(0, 10).map((f) => ({
                          feature: f.feature,
                          Requests: f.requests,
                          Users: f.unique_users,
                        }));
                        return (
                          <ResponsiveContainer width="100%" height={Math.max(200, barData.length * 36)}>
                            <BarChart data={barData} layout="vertical" margin={{ top: 0, right: 20, left: 10, bottom: 0 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                              <XAxis type="number" tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                              <YAxis
                                dataKey="feature"
                                type="category"
                                width={80}
                                tick={{ fontSize: 10, fill: "#64748b" }}
                                axisLine={false}
                                tickLine={false}
                              />
                              <Tooltip
                                contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
                              />
                              <Bar dataKey="Requests" fill="#6366f1" radius={[0, 4, 4, 0]} barSize={18} />
                            </BarChart>
                          </ResponsiveContainer>
                        );
                      })()}
                    </CardContent>
                  </Card>

                  {/* Top Users table */}
                  <Card className="bg-white">
                    <CardContent className="p-4">
                      <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                        <Crown className="size-3.5" /> Top Users (last 30 days)
                      </h3>
                      {adoptionData.top_users.length === 0 ? (
                        <p className="text-xs text-slate-400 py-6 text-center">No user activity yet</p>
                      ) : (
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="text-[10px]">Email</TableHead>
                              <TableHead className="text-[10px] text-right">Days Active</TableHead>
                              <TableHead className="text-[10px] text-right">Requests</TableHead>
                              <TableHead className="text-[10px] text-right">Last Active</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {adoptionData.top_users.map((u, i) => (
                              <TableRow key={i}>
                                <TableCell className="text-xs text-indigo-600 font-medium truncate max-w-[180px]">
                                  {u.email}
                                </TableCell>
                                <TableCell className="text-xs text-right font-mono">
                                  {u.session_days}
                                </TableCell>
                                <TableCell className="text-xs text-right font-mono text-slate-500">
                                  {u.total_requests.toLocaleString()}
                                </TableCell>
                                <TableCell className="text-[10px] text-right text-slate-400">
                                  {toBelgianTime(u.last_active)}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      )}
                    </CardContent>
                  </Card>
                </div>
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
                  className="pl-8 h-10 md:h-8"
                />
              </div>
            </div>

            <Card className="bg-white overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead className="hidden md:table-cell">Joined</TableHead>
                    <TableHead className="hidden lg:table-cell">Last Active</TableHead>
                    <TableHead className="hidden md:table-cell text-right">Requests (7d)</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading
                    ? Array.from({ length: 3 }).map((_, i) => (
                        <TableRow key={i}>
                          <TableCell><Skeleton className="h-4 w-24" /></TableCell>
                          <TableCell><Skeleton className="h-4 w-24" /></TableCell>
                          <TableCell className="hidden md:table-cell"><Skeleton className="h-4 w-24" /></TableCell>
                          <TableCell className="hidden lg:table-cell"><Skeleton className="h-4 w-24" /></TableCell>
                          <TableCell className="hidden md:table-cell"><Skeleton className="h-4 w-24" /></TableCell>
                          <TableCell><Skeleton className="h-4 w-24" /></TableCell>
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
                                      : u.role === "pro"
                                        ? "bg-amber-100 text-amber-700"
                                        : u.role === "blocked"
                                          ? "bg-red-100 text-red-700"
                                          : ""
                                  }
                                >
                                  {u.role}
                                </Badge>
                              </TableCell>
                              <TableCell className="hidden md:table-cell text-sm text-slate-500">
                                {u.created_at
                                  ? toBelgianDate(u.created_at)
                                  : "--"}
                              </TableCell>
                              <TableCell className="hidden lg:table-cell text-sm text-slate-500">
                                {act
                                  ? toBelgianTime(act.last_active)
                                  : "--"}
                              </TableCell>
                              <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                {act ? fmt(act.total_requests) : "--"}
                              </TableCell>
                              <TableCell className="text-right">
                                {/* Row actions — wrap on mobile so 3-4 small
                                    buttons don't push the table off-screen. */}
                                <div className="flex flex-wrap items-center justify-end gap-1.5">
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
                                  {u.role !== "pro" && u.role !== "admin" && u.role !== "blocked" && (
                                    <Button
                                      variant="outline"
                                      size="xs"
                                      className="border-amber-300 text-amber-600 hover:bg-amber-50"
                                      disabled={
                                        actionLoading === `role-${u.email}`
                                      }
                                      onClick={() => setRole(u.email, "pro")}
                                    >
                                      <Crown className="size-3 mr-0.5" />
                                      Pro
                                    </Button>
                                  )}
                                  {u.role === "pro" && (
                                    <Button
                                      variant="outline"
                                      size="xs"
                                      className="border-slate-300 text-slate-600 hover:bg-slate-50"
                                      disabled={
                                        actionLoading === `role-${u.email}`
                                      }
                                      onClick={() => setRole(u.email, "user")}
                                    >
                                      Revoke Pro
                                    </Button>
                                  )}
                                  {u.role !== "admin" && u.role !== "blocked" && (
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
                                  {u.role === "admin" && (
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
                              className="h-10 md:h-7 text-base md:text-xs flex-1"
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
                                {toBelgianDate(poll.created_at)}
                              </span>
                              {poll.archived_at && (
                                <span>
                                  Archived{" "}
                                  {toBelgianDate(poll.archived_at)}
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
            TAB: Tiers
            ================================================================ */}
        <TabsContent value="tiers">
          <div className="space-y-6 pt-2">
            {/* Master toggle */}
            <Card className="bg-white">
              <CardContent>
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-700">
                      Enforce usage limits
                    </h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      When enabled, users will be rate-limited according to their tier. Currently for configuration only.
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {tiers.length > 0 && (
                      <Badge
                        variant="secondary"
                        className={
                          tiers.some((t) => t.enabled)
                            ? "bg-amber-50 text-amber-700 border border-amber-200"
                            : "bg-emerald-50 text-emerald-700 border border-emerald-200"
                        }
                      >
                        {tiers.some((t) => t.enabled) ? "Enforced" : "Not enforced"}
                      </Badge>
                    )}
                    <Button
                      size="sm"
                      variant={tiers.some((t) => t.enabled) ? "default" : "outline"}
                      onClick={toggleAllLimits}
                      disabled={tierToggling || tiers.length === 0}
                      className="min-w-[80px]"
                    >
                      {tierToggling
                        ? "..."
                        : tiers.some((t) => t.enabled)
                        ? "Disable"
                        : "Enable"}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Tier cards */}
            {loading ? (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {[1, 2, 3].map((i) => (
                  <Card key={i} className="bg-white">
                    <CardContent className="space-y-4">
                      <Skeleton className="h-6 w-24" />
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                      <Skeleton className="h-8 w-full" />
                    </CardContent>
                  </Card>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {(["guest", "registered", "premium"] as const).map((tierName) => {
                  const tier = tiers.find((t) => t.tier === tierName);
                  if (!tier) return null;

                  const iconMap = {
                    guest: Shield,
                    registered: UserCheck,
                    premium: Crown,
                  };
                  const colorMap = {
                    guest: "text-slate-500",
                    registered: "text-indigo-600",
                    premium: "text-amber-500",
                  };
                  const bgMap = {
                    guest: "bg-slate-50 border-slate-200",
                    registered: "bg-indigo-50 border-indigo-200",
                    premium: "bg-amber-50 border-amber-200",
                  };
                  const TierIcon = iconMap[tierName];
                  const hasEdits = tierEdits[tierName] && Object.keys(tierEdits[tierName]).length > 0;

                  const fields: { key: string; label: string }[] = [
                    { key: "page_views_per_day", label: "Page views / day" },
                    { key: "searches_per_day", label: "Searches / day" },
                    { key: "company_views_per_day", label: "Company views / day" },
                    { key: "ai_enrichments_per_day", label: "AI enrichments / day" },
                    { key: "export_per_day", label: "Exports / day" },
                    { key: "screener_results_limit", label: "Screener results limit" },
                  ];

                  return (
                    <Card key={tierName} className={`border ${bgMap[tierName]}`}>
                      <CardContent className="space-y-4">
                        <div className="flex items-center gap-2">
                          <TierIcon className={`size-5 ${colorMap[tierName]}`} />
                          <h3 className="text-sm font-bold capitalize text-slate-800">
                            {tierName}
                          </h3>
                        </div>

                        {fields.map(({ key, label }) => (
                          <div key={key}>
                            <label className="text-[11px] font-medium text-slate-500 mb-1 block">
                              {label}
                            </label>
                            <Input
                              type="number"
                              value={getTierValue(tierName, key as keyof TierConfig)}
                              onChange={(e) =>
                                setTierField(
                                  tierName,
                                  key,
                                  parseInt(e.target.value, 10) || 0
                                )
                              }
                              className="h-10 md:h-8 text-base md:text-sm bg-white"
                            />
                          </div>
                        ))}

                        <p className="text-[10px] text-slate-400">
                          -1 = unlimited
                        </p>

                        <Button
                          size="sm"
                          className="w-full"
                          onClick={() => saveTier(tierName)}
                          disabled={!hasEdits || tierSaving === tierName}
                        >
                          {tierSaving === tierName ? (
                            "Saving..."
                          ) : (
                            <>
                              <Save className="size-3.5 mr-1.5" />
                              Save {tierName}
                            </>
                          )}
                        </Button>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </div>
        </TabsContent>

        {/* ================================================================
            TAB 5: Recent Activity (grouped by user, Belgian timezone)
            ================================================================ */}
        <TabsContent value="activity">
          <div className="space-y-4 pt-2">
            <SectionHeading icon={Clock}>Recent Activity</SectionHeading>
            <p className="text-xs text-slate-400 -mt-2 mb-2">Last 50 actions, grouped by user. All times in Europe/Brussels (CET/CEST).</p>

            {!adoptionData || adoptionData.recent.length === 0 ? (
              <Card className="bg-white">
                <CardContent>
                  <p className="py-8 text-center text-sm text-slate-400">No activity recorded yet.</p>
                </CardContent>
              </Card>
            ) : (() => {
              // Group recent activity by user
              type RecentEntry = AdoptionData["recent"][number];
              const byUser = new Map<string, RecentEntry[]>();
              for (const entry of adoptionData.recent) {
                const key = entry.user_email || "unknown";
                if (!byUser.has(key)) byUser.set(key, []);
                byUser.get(key)!.push(entry);
              }
              // Sort users by most recent action first
              const userGroups = Array.from(byUser.entries()).sort(
                (a, b) => (b[1][0]?.created_at_be || "").localeCompare(a[1][0]?.created_at_be || "")
              );

              function endpointLabel(ep: string): { label: string; icon: React.ReactNode; color: string } {
                if (ep.includes("/company/") && ep.includes("/financials")) return { label: "Viewed financials", icon: <BarChart3 className="size-3.5" />, color: "text-indigo-600 bg-indigo-50" };
                if (ep.includes("/company/") && ep.includes("/structure")) return { label: "Viewed structure", icon: <Users className="size-3.5" />, color: "text-purple-600 bg-purple-50" };
                if (ep.includes("/company/")) return { label: "Viewed company", icon: <Eye className="size-3.5" />, color: "text-blue-600 bg-blue-50" };
                if (ep.includes("/screener")) return { label: "Used screener", icon: <Search className="size-3.5" />, color: "text-emerald-600 bg-emerald-50" };
                if (ep.includes("/people")) return { label: "Searched people", icon: <Users className="size-3.5" />, color: "text-amber-600 bg-amber-50" };
                if (ep.includes("/favourites")) return { label: "Managed favourites", icon: <CircleCheck className="size-3.5" />, color: "text-pink-600 bg-pink-50" };
                if (ep.includes("/dashboard")) return { label: "Viewed dashboard", icon: <Globe className="size-3.5" />, color: "text-slate-600 bg-slate-50" };
                if (ep.includes("/feedback")) return { label: "Sent feedback", icon: <MessageSquare className="size-3.5" />, color: "text-orange-600 bg-orange-50" };
                if (ep.includes("/staatsblad")) return { label: "Loaded publications", icon: <Database className="size-3.5" />, color: "text-teal-600 bg-teal-50" };
                if (ep.includes("/nbb") || ep.includes("/load")) return { label: "Loaded NBB data", icon: <Database className="size-3.5" />, color: "text-violet-600 bg-violet-50" };
                if (ep.includes("/ai") || ep.includes("/enrich")) return { label: "AI Insights", icon: <Activity className="size-3.5" />, color: "text-fuchsia-600 bg-fuchsia-50" };
                if (ep.includes("/export")) return { label: "Exported data", icon: <ArrowUpRight className="size-3.5" />, color: "text-cyan-600 bg-cyan-50" };
                return { label: ep.replace("/api/", ""), icon: <Globe className="size-3.5" />, color: "text-slate-500 bg-slate-50" };
              }

              return (
                <div className="space-y-4">
                  {userGroups.map(([userEmail, entries]) => {
                    const isGuest = userEmail.startsWith("anon:");
                    const displayName = isGuest
                      ? `Guest ${userEmail.replace("anon:", "").split(".").slice(0, 2).join(".")}...`
                      : userEmail;
                    return (
                      <Card key={userEmail} className="bg-white">
                        <CardContent className="p-4">
                          {/* User header */}
                          <div className="flex items-center gap-2 mb-3 pb-2 border-b border-slate-100">
                            <div className={`shrink-0 p-1.5 rounded-full ${isGuest ? "bg-orange-50" : "bg-indigo-50"}`}>
                              {isGuest
                                ? <Globe className="size-3.5 text-orange-500" />
                                : <UserCheck className="size-3.5 text-indigo-500" />
                              }
                            </div>
                            <span className={`text-xs font-semibold ${isGuest ? "text-orange-600" : "text-indigo-600"}`}>
                              {displayName}
                            </span>
                            <span className="text-[10px] text-slate-400 ml-auto">
                              {entries.length} action{entries.length !== 1 ? "s" : ""}
                            </span>
                          </div>

                          {/* Activity entries */}
                          <div className="space-y-1.5">
                            {entries.map((entry, i) => {
                              const info = endpointLabel(entry.endpoint);
                              // created_at_be is already in Brussels time from the backend
                              const timeStr = entry.created_at_be
                                ? toBelgianTime(entry.created_at_be)
                                : "";
                              return (
                                <div key={i} className="flex items-center gap-2.5 py-1">
                                  <div className={`shrink-0 p-1 rounded-md ${info.color}`}>
                                    {info.icon}
                                  </div>
                                  <span className="text-xs text-slate-700 flex-1 min-w-0 truncate">{info.label}</span>
                                  <span className={`shrink-0 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${
                                    entry.method === "POST" ? "bg-amber-50 text-amber-600" :
                                    entry.method === "DELETE" ? "bg-rose-50 text-rose-500" :
                                    "bg-slate-50 text-slate-400"
                                  }`}>
                                    {entry.method}
                                  </span>
                                  <span className="text-[10px] text-slate-400 font-mono shrink-0 w-28 text-right">
                                    {timeStr}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </CardContent>
                      </Card>
                    );
                  })}
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
            {/* ── ARR headline (last 4 weeks × 13) ── */}
            {arrData && (
              <Card className="bg-gradient-to-br from-emerald-50 to-white border-l-4 border-l-emerald-500">
                <CardContent className="p-4 md:p-5">
                  <div className="flex items-start justify-between flex-wrap gap-3">
                    <div>
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 mb-1">Annualised Recurring Revenue</div>
                      <div className="text-3xl md:text-4xl font-bold text-emerald-700 font-mono">
                        {arrData.currency === "eur" ? "€" : ""}{arrData.arr_eur.toLocaleString("en", { maximumFractionDigits: 0 })}
                      </div>
                      <div className="text-[11px] text-slate-500 mt-1">
                        €{arrData.last_4w_eur.toLocaleString("en", { maximumFractionDigits: 0 })} in the last {arrData.window_days} days × {arrData.multiplier}
                      </div>
                      {arrData.note && (
                        <div className="text-[11px] text-amber-600 mt-1">{arrData.note}</div>
                      )}
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Active subscribers</div>
                      <div className="text-2xl font-bold text-slate-700 font-mono">{arrData.active_subscribers}</div>
                    </div>
                  </div>

                  {arrData.weekly.length > 0 && (
                    <div className="mt-4 border-t pt-3">
                      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2">Weekly breakdown</div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        {arrData.weekly.map((w) => (
                          <div key={w.week_start} className="text-center bg-white rounded border border-slate-200 p-2">
                            <div className="text-[9px] text-slate-400">{w.week_start.slice(5)} – {w.week_end.slice(5)}</div>
                            <div className="text-sm font-mono font-bold text-slate-700 mt-1">€{w.gross_eur.toLocaleString("en", { maximumFractionDigits: 0 })}</div>
                            <div className="text-[9px] text-slate-400">{w.charges} charges</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {/* ── Invoices from invoice@datasnoop.be ── */}
            {invoicesData && (
              <Card className="bg-white border-l-4 border-l-rose-400">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between mb-3 gap-3 flex-wrap">
                    <div>
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Platform invoices (ingested)</h3>
                      <p className="text-[11px] text-slate-400 mt-0.5">Ingested nightly from invoice@datasnoop.be. Amounts are best-effort; click "confirm" to lock.</p>
                    </div>
                    {invoicesData.monthly.length > 0 && (
                      <div className="text-right">
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-0.5">Last month</div>
                        <div className="text-lg font-bold text-rose-600 font-mono">
                          €{(invoicesData.monthly[0]?.eur_total ?? 0).toLocaleString("en", { maximumFractionDigits: 0 })}
                        </div>
                      </div>
                    )}
                  </div>
                  {invoicesData.monthly.length > 0 && (
                    <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mb-3">
                      {invoicesData.monthly.slice().reverse().map((m) => (
                        <div key={m.ym} className="text-center border border-slate-200 rounded p-1.5">
                          <div className="text-[9px] text-slate-400">{m.ym}</div>
                          <div className="text-xs font-mono font-bold text-slate-700">€{m.eur_total.toLocaleString("en", { maximumFractionDigits: 0 })}</div>
                          <div className="text-[9px] text-slate-400">{m.invoices} inv</div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="max-h-64 overflow-y-auto">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-slate-50">
                        <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                          <th className="py-1.5 px-2">Date</th>
                          <th className="py-1.5 px-2">From</th>
                          <th className="py-1.5 px-2">Subject</th>
                          <th className="py-1.5 px-2 text-right">Amount</th>
                          <th className="py-1.5 px-2">OK?</th>
                        </tr>
                      </thead>
                      <tbody>
                        {invoicesData.invoices.length === 0 && (
                          <tr><td colSpan={5} className="py-4 text-center text-slate-400">No invoices ingested yet.</td></tr>
                        )}
                        {invoicesData.invoices.map((inv) => (
                          <tr key={inv.id} className="border-b border-slate-100 hover:bg-slate-50">
                            <td className="py-1 px-2 font-mono text-[11px] text-slate-600 whitespace-nowrap">{inv.invoice_date ?? (inv.received_at ? inv.received_at.slice(0, 10) : "—")}</td>
                            <td className="py-1 px-2 truncate max-w-[180px]" title={inv.sender ?? undefined}>{inv.sender ?? "—"}</td>
                            <td className="py-1 px-2 truncate max-w-[240px]" title={inv.subject ?? undefined}>{inv.subject ?? "—"}</td>
                            <td className="py-1 px-2 text-right font-mono">
                              {inv.amount_cents != null
                                ? `€${(inv.amount_cents / 100).toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                                : <span className="text-amber-500">? parse</span>}
                            </td>
                            <td className="py-1 px-2">
                              {inv.confirmed
                                ? <span className="text-[10px] text-emerald-600 font-semibold">✓</span>
                                : <span className="text-[10px] text-slate-400">todo</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* ── Mini P&L Summary (legacy, kept for reference) ── */}
            {(() => {
              const revEur = paymentsData ? paymentsData.total_revenue / 100 : 0;
              const orUsd = costsData?.openrouter_usage_usd ?? 0;
              const orEur = orUsd * 0.92;
              const itemsMonthly = costItems.map((c) => ({
                name: c.name,
                monthly: c.frequency === "yearly" ? c.amount / 12 : c.frequency === "one-time" ? 0 : c.amount,
              }));
              const totalCostsM = orEur + itemsMonthly.reduce((s, c) => s + c.monthly, 0);
              const netM = revEur - totalCostsM;
              const eur = (v: number) => v.toLocaleString("en", { style: "currency", currency: "EUR", minimumFractionDigits: 2 });
              return (
                <Card className="bg-white border-l-4 border-l-indigo-500">
                  <CardContent className="p-4">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Monthly P&L (estimate)</h3>
                    <Table>
                      <TableBody>
                        <TableRow className="bg-emerald-50/50">
                          <TableCell className="text-xs font-semibold text-emerald-700 py-1.5">Revenue (Stripe)</TableCell>
                          <TableCell className="text-xs font-mono text-right font-semibold text-emerald-700 py-1.5">{eur(revEur)}</TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">OpenRouter (AI)</TableCell>
                          <TableCell className="text-xs font-mono text-right text-rose-500 py-1">-{eur(orEur)}</TableCell>
                        </TableRow>
                        {itemsMonthly.filter((c) => c.monthly > 0).map((c) => (
                          <TableRow key={c.name}>
                            <TableCell className="text-xs text-slate-600 py-1">{c.name}</TableCell>
                            <TableCell className="text-xs font-mono text-right text-rose-500 py-1">-{eur(c.monthly)}</TableCell>
                          </TableRow>
                        ))}
                        <TableRow className={netM >= 0 ? "bg-emerald-50/50" : "bg-rose-50/50"}>
                          <TableCell className="text-xs font-bold py-1.5">Net Result</TableCell>
                          <TableCell className={`text-sm font-mono text-right font-bold py-1.5 ${netM >= 0 ? "text-emerald-700" : "text-rose-600"}`}>{eur(netM)}</TableCell>
                        </TableRow>
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              );
            })()}

            {/* ── AI Usage + OpenRouter ── */}
            {costsData && (
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <Card className="bg-white">
                  <CardContent className="p-3 text-center">
                    <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">OpenRouter Spend</div>
                    <div className="text-xl font-bold text-rose-500 font-mono">${costsData.openrouter_usage_usd.toFixed(2)}</div>
                    {costsData.openrouter_limit_usd > 0 && <div className="text-[10px] text-slate-400">of ${costsData.openrouter_limit_usd.toFixed(0)} limit</div>}
                  </CardContent>
                </Card>
                {Object.entries(costsData.ai_calls_30d).map(([k, v]) => (
                  <Card key={k} className="bg-white">
                    <CardContent className="p-3 text-center">
                      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">{k.replace(/_/g, " ")} (30d)</div>
                      <div className="text-xl font-bold text-slate-800 font-mono">{v}</div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}

            {/* ── LLM cost breakdown by call type (real) ── */}
            {llmCosts && (
              <Card className="bg-white">
                <CardContent className="p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-slate-800">
                      LLM cost by call type
                      <span className="ml-2 text-[11px] font-normal text-slate-400">
                        (last {llmCosts.window_days} days)
                      </span>
                    </h3>
                    <div className="text-right">
                      <div className="text-[11px] text-slate-400">total</div>
                      <div className="text-base font-bold text-rose-600 font-mono">
                        ${llmCosts.est_total_usd.toFixed(2)}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        avg ${llmCosts.est_avg_per_call_usd.toFixed(4)} / call &middot; {llmCosts.calls_total} calls
                      </div>
                    </div>
                  </div>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-[10px] uppercase tracking-wider text-slate-400 py-1">Call type</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider text-slate-400 text-right py-1">Calls</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider text-slate-400 text-right py-1">$/call</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider text-slate-400 text-right py-1">Total $</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {llmCosts.breakdown.map((r) => (
                        <TableRow key={r.kind}>
                          <TableCell className="text-xs py-1 text-slate-700">{r.kind}</TableCell>
                          <TableCell className="text-xs font-mono text-right text-slate-600 py-1">{r.calls.toLocaleString()}</TableCell>
                          <TableCell className="text-xs font-mono text-right text-slate-500 py-1">${r.est_cost_per_call_usd.toFixed(4)}</TableCell>
                          <TableCell className="text-xs font-mono text-right font-semibold text-slate-800 py-1">${r.est_total_usd.toFixed(2)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <p className="mt-2 text-[10px] italic text-slate-400">{llmCosts.note}</p>
                </CardContent>
              </Card>
            )}

            {/* ── Manage Cost Items ── */}
            {costsData && (
              <Card className="bg-white">
                <CardContent className="p-4">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Cost Items</h3>
                  {/* Existing items */}
                  <div className="space-y-2 mb-3">
                    {costItems.map((item, idx) => (
                      <div key={idx} className="flex flex-wrap sm:flex-nowrap items-center gap-2">
                        <Input
                          className="h-10 md:h-7 text-base md:text-xs flex-1 min-w-[160px]"
                          value={item.name}
                          onChange={(e) => {
                            const next = [...costItems];
                            next[idx] = { ...next[idx], name: e.target.value };
                            setCostItems(next);
                          }}
                        />
                        <Input
                          type="number"
                          step="0.01"
                          className="h-10 md:h-7 text-base md:text-xs font-mono w-24"
                          value={item.amount}
                          onChange={(e) => {
                            const next = [...costItems];
                            next[idx] = { ...next[idx], amount: parseFloat(e.target.value) || 0 };
                            setCostItems(next);
                          }}
                        />
                        <select
                          className="h-10 md:h-7 text-base md:text-xs border rounded px-2 md:px-1 bg-white text-slate-600"
                          value={item.frequency}
                          onChange={(e) => {
                            const next = [...costItems];
                            next[idx] = { ...next[idx], frequency: e.target.value as CostItem["frequency"] };
                            setCostItems(next);
                          }}
                        >
                          <option value="monthly">Monthly</option>
                          <option value="yearly">Yearly</option>
                          <option value="one-time">One-time</option>
                        </select>
                        <button
                          onClick={() => setCostItems(costItems.filter((_, i) => i !== idx))}
                          className="h-10 w-10 sm:h-auto sm:w-auto flex items-center justify-center text-slate-300 hover:text-rose-500 transition-colors"
                          title="Remove item"
                        >
                          <Trash2 className="w-4 h-4 sm:w-3.5 sm:h-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                  {/* Add new item */}
                  <div className="flex items-center gap-2 border-t border-slate-100 pt-2 flex-wrap md:flex-nowrap">
                    <Input
                      className="h-10 md:h-7 text-base md:text-xs flex-1 min-w-[160px]"
                      placeholder="Cost name..."
                      value={newCostName}
                      onChange={(e) => setNewCostName(e.target.value)}
                    />
                    <Input
                      type="number"
                      step="0.01"
                      className="h-10 md:h-7 text-base md:text-xs font-mono w-24"
                      placeholder="0.00"
                      value={newCostAmount}
                      onChange={(e) => setNewCostAmount(e.target.value)}
                    />
                    <select
                      className="h-10 md:h-7 text-base md:text-xs border rounded px-2 md:px-1 bg-white text-slate-600"
                      value={newCostFreq}
                      onChange={(e) => setNewCostFreq(e.target.value as CostItem["frequency"])}
                    >
                      <option value="monthly">Monthly</option>
                      <option value="yearly">Yearly</option>
                      <option value="one-time">One-time</option>
                    </select>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-[11px] px-2"
                      disabled={!newCostName.trim() || !newCostAmount}
                      onClick={() => {
                        setCostItems([...costItems, { name: newCostName.trim(), amount: parseFloat(newCostAmount) || 0, frequency: newCostFreq }]);
                        setNewCostName("");
                        setNewCostAmount("");
                      }}
                    >
                      + Add
                    </Button>
                  </div>
                  {/* Save */}
                  <Button
                    size="sm"
                    className="mt-3 h-7 text-[11px]"
                    disabled={costSaving}
                    onClick={async () => {
                      setCostSaving(true);
                      try {
                        await adminFetch("/api/admin/costs", { method: "POST", body: JSON.stringify({ items: costItems }) });
                        loadData();
                      } catch { /* ignore */ }
                      finally { setCostSaving(false); }
                    }}
                  >
                    {costSaving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Save className="w-3 h-3 mr-1" />}
                    Save costs
                  </Button>
                </CardContent>
              </Card>
            )}

            {/* ── Stripe Payments ── */}
            <SectionHeading icon={CreditCard}>Stripe Payments</SectionHeading>
            {!paymentsData || paymentsData.payments.length === 0 ? (
              <Card className="bg-white">
                <CardContent>
                  <p className="py-8 text-center text-sm text-slate-400">No payments yet.</p>
                </CardContent>
              </Card>
            ) : (
              <Card className="bg-white">
                <CardContent className="p-4">
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
                              {toBelgianDate(p.created)} <span className="text-slate-400">{toBelgianTimeOnly(p.created)}</span>
                            </TableCell>
                            <TableCell className="text-xs text-slate-600 max-w-[200px] truncate">{p.email || <span className="text-slate-300">--</span>}</TableCell>
                            <TableCell className="text-xs font-mono font-semibold text-slate-800">
                              {(p.amount / 100).toLocaleString("en", { style: "currency", currency: p.currency })}
                            </TableCell>
                            <TableCell>
                              <Badge variant="secondary" className={`text-[10px] ${p.mode === "subscription" ? "bg-indigo-50 text-indigo-600" : "bg-slate-100 text-slate-600"}`}>
                                {p.mode === "subscription" ? "Subscription" : "One-time"}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              <Badge variant="secondary" className={`text-[10px] ${p.status === "paid" ? "bg-emerald-50 text-emerald-600" : p.status === "unpaid" ? "bg-amber-50 text-amber-600" : "bg-slate-100 text-slate-500"}`}>
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
            )}
          </div>
        </TabsContent>

        {/* ================================================================
            TAB 6: Settings
            ================================================================ */}
        <TabsContent value="settings">
          <div className="pt-2 space-y-6">
            {/* Site Logo */}
            <Card className="bg-white">
              <CardContent>
                <SectionHeading icon={Image}>Site Logo</SectionHeading>
                <p className="text-sm text-slate-500 mb-4">
                  Choose which logo appears in the header across the platform.
                </p>

                {/* Current logo preview */}
                <div className="flex items-center gap-3 mb-6 p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <img
                    src={siteLogo}
                    alt="Current logo"
                    className="w-10 h-10 object-contain"
                  />
                  <div>
                    <div className="text-xs font-semibold text-slate-700">
                      Active logo
                    </div>
                    <div className="text-[11px] text-slate-400 font-mono">
                      {siteLogo}
                    </div>
                  </div>
                </div>

                {/* Logo grid */}
                <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-7 gap-3">
                  {[
                    { path: "/logo.svg", label: "Mountain peak" },
                    { path: "/logos/dog-a-warm.svg", label: "Dog - warm" },
                    { path: "/logos/dog-telescope.jpg", label: "Dog - indigo" },
                    { path: "/logos/dog-c-teal.svg", label: "Dog - teal" },
                    { path: "/logos/datasnoop-logo-1-magnifier.svg", label: "Magnifier" },
                    { path: "/logos/datasnoop-logo-2-eye.svg", label: "Eye" },
                    { path: "/logos/datasnoop-logo-3-radar.svg", label: "Radar" },
                  ].map((logo) => {
                    const isActive = siteLogo === logo.path;
                    return (
                      <button
                        key={logo.path}
                        disabled={logoSaving}
                        onClick={async () => {
                          setLogoSaving(true);
                          try {
                            await adminFetch("/api/admin/site-config", {
                              method: "PUT",
                              body: JSON.stringify({ site_logo: logo.path }),
                            });
                            setSiteLogo(logo.path);
                          } catch {
                            // silently fail
                          } finally {
                            setLogoSaving(false);
                          }
                        }}
                        className={`relative flex flex-col items-center gap-1.5 p-3 rounded-xl border-2 transition-all ${
                          isActive
                            ? "border-indigo-500 bg-indigo-50 ring-2 ring-indigo-200"
                            : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                        } ${logoSaving ? "opacity-50 cursor-wait" : "cursor-pointer"}`}
                      >
                        {isActive && (
                          <div className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-indigo-600 text-white flex items-center justify-center">
                            <Check className="w-3 h-3" />
                          </div>
                        )}
                        <img
                          src={logo.path}
                          alt={logo.label}
                          className="w-[60px] h-[60px] object-contain"
                        />
                        <span className="text-[10px] font-medium text-slate-500 text-center leading-tight">
                          {logo.label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </CardContent>
            </Card>

            {/* Placeholder for future settings */}
            <Card className="bg-white">
              <CardContent>
                <div className="py-8 text-center">
                  <Settings className="size-7 text-slate-300 mx-auto mb-2" />
                  <p className="text-sm text-slate-400">
                    More configuration options coming soon.
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
