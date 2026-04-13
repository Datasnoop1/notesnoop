import { createClient } from "./supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };

  // Attach auth token if available
  try {
    const supabase = createClient();
    const { data } = await supabase.auth.getSession();
    if (data.session?.access_token) {
      headers["Authorization"] = `Bearer ${data.session.access_token}`;
    }
  } catch {
    // No auth available — continue without token
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  return res.json();
}

// ── Dashboard ──────────────────────────────────────────────
export interface DashboardKPIs {
  enterprise_count: number;
  financial_count: number;
  filing_count: number;
  admin_count: number;
  snapshot_date: string | null;
}

export interface TopCompany {
  cbe: string;
  name: string;
  metric_value: number | null;
  ebitda: number | null;
  revenue: number | null;
  ebitda_margin_pct: number | null;
  fte_total: number | null;
  fiscal_year: number | null;
  nace_code: string | null;
  sector: string | null;
  city: string | null;
}

export const getDashboard = () => apiFetch<DashboardKPIs>("/api/dashboard");

export const getTopCompanies = (metric = "revenue", limit = 15) =>
  apiFetch<TopCompany[]>(`/api/dashboard/top-companies?metric=${metric}&limit=${limit}`);

// ── Screener ───────────────────────────────────────────────
export interface ScreenerRow {
  cbe: string;
  name: string;
  nace: string;
  city: string;
  fiscal_year: number | null;
  revenue: number | null;
  ebit: number | null;
  ebitda: number | null;
  margin_pct: number | null;
  net_profit: number | null;
  fte: number | null;
}

export interface ScreenerFilters {
  nace?: string;
  zipcode?: string;
  ebit_min?: number;
  ebit_max?: number;
  ebitda_min?: number;
  ebitda_max?: number;
  rev_min?: number;
  rev_max?: number;
  fte_min?: number;
  fte_max?: number;
  margin_min?: number;
  sort?: string;
  limit?: number;
}

export function getScreener(filters: ScreenerFilters) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v != null && v !== "" && v !== 0) params.set(k, String(v));
  }
  return apiFetch<ScreenerRow[]>(`/api/screener?${params}`);
}

// ── Companies ──────────────────────────────────────────────
export interface SearchResult {
  enterprise_number: string;
  name: string;
  status: string;
  jf_label: string | null;
  city: string | null;
  sector: string | null;
  start_date: string | null;
  revenue: number | null;
  ebitda: number | null;
  ebitda_margin_pct: number | null;
  fte_total: number | null;
  fiscal_year: number | null;
}

export interface CompanyDetail {
  enterprise_number: string;
  status: string;
  start_date: string | null;
  jf_label: string | null;
  name: string | null;
  zipcode: string | null;
  municipality: string | null;
  city: string | null;
  street: string | null;
  house_number: string | null;
  nace_code: string | null;
  nace_label: string | null;
}

export interface FinancialYear {
  fiscal_year: number;
  revenue: number | null;
  ebit: number | null;
  ebitda: number | null;
  ebitda_margin_pct: number | null;
  net_profit: number | null;
  equity: number | null;
  total_assets: number | null;
  fte_total: number | null;
  personnel_costs: number | null;
  da: number | null;
  lt_financial_debt: number | null;
  st_financial_debt: number | null;
  cash: number | null;
}

export interface CompanyFinancials {
  summary: FinancialYear[];
  rubrics: Record<string, Record<string, number>>;
}

export interface Administrator {
  name: string;
  role: string | null;
  person_type: string | null;
  identifier: string | null;
  mandate_start: string | null;
  mandate_end: string | null;
  representative_name: string | null;
}

export interface Shareholder {
  name: string;
  identifier: string | null;
  ownership_pct: number | null;
  shareholder_type: string | null;
  shares_held: number | null;
}

export interface ParticipatingInterest {
  name: string;
  identifier: string | null;
  ownership_pct: number | null;
  country: string | null;
  equity_value: number | null;
}

export interface Publication {
  pub_date: string;
  pub_type: string | null;
  reference: string | null;
  pdf_url: string | null;
}

export interface CompanyStructure {
  administrators: Administrator[];
  shareholders: Shareholder[];
  participating_interests: ParticipatingInterest[];
  publications: Publication[];
}

export interface NetworkNode {
  id: string;
  label: string;
  type: string;
}

export interface NetworkEdge {
  source: string;
  target: string;
  relation: string;
  pct: number | null;
}

export interface CompanyNetwork {
  nodes: NetworkNode[];
  edges: NetworkEdge[];
}

export const searchCompanies = (q: string) =>
  apiFetch<SearchResult[]>(`/api/companies/search?q=${encodeURIComponent(q)}`);

export const getCompanyDetail = (cbe: string) =>
  apiFetch<CompanyDetail>(`/api/companies/${cbe}`);

export const getCompanyFinancials = (cbe: string) =>
  apiFetch<CompanyFinancials>(`/api/companies/${cbe}/financials`);

export const getCompanyStructure = (cbe: string) =>
  apiFetch<CompanyStructure>(`/api/companies/${cbe}/structure`);

export const getCompanyNetwork = (cbe: string, maxDepth = 2) =>
  apiFetch<CompanyNetwork>(`/api/companies/${cbe}/network?max_depth=${maxDepth}`);

// ── Stats ──────────────────────────────────────────────────
export interface StatsOverview {
  n_companies: number;
  total_revenue: number;
  total_ebitda: number;
  total_fte: number;
  avg_fte: number;
  total_nfd: number;
  median_margin: number | null;
}

export interface StatsSector {
  nace2: string;
  sector: string;
  companies: number;
  revenue_m: number;
  ebitda_m: number;
  med_margin: number | null;
  med_fte: number | null;
  med_nfd_ebitda: number | null;
}

export const getStatsOverview = (province?: string) =>
  apiFetch<StatsOverview>(`/api/stats/overview${province ? `?province=${province}` : ""}`);

export const getStatsSectors = (province?: string, topN = 25) =>
  apiFetch<StatsSector[]>(`/api/stats/sectors?top_n=${topN}${province ? `&province=${province}` : ""}`);

// ── People ─────────────────────────────────────────────────
export interface PersonResult {
  name: string;
  roles: number;
  companies: number;
  holdings: number;
}

export interface PersonConnection {
  company_name: string;
  enterprise_number: string;
  role: string;
  type: string;
}

export const searchPeople = (q: string) =>
  apiFetch<PersonResult[]>(`/api/people/search?q=${encodeURIComponent(q)}`);

export const getPersonConnections = (name: string) =>
  apiFetch<{ admin_roles: PersonConnection[]; holdings: PersonConnection[] }>(
    `/api/people/${encodeURIComponent(name)}/connections`
  );

// ── Favourites ─────────────────────────────────────────────
export interface FavouriteItem {
  enterprise_number: string;
  name: string | null;
  city: string | null;
  nace_code: string | null;
  revenue: number | null;
  ebitda: number | null;
  margin_pct: number | null;
  fte_total: number | null;
  added_at: string;
  notes: string | null;
}

export const getFavourites = () => apiFetch<FavouriteItem[]>("/api/favourites");

export const addFavourite = (enterprise_number: string, notes?: string) =>
  apiFetch<{ status: string }>("/api/favourites", {
    method: "POST",
    body: JSON.stringify({ enterprise_number, notes }),
  });

export const removeFavourite = (cbe: string) =>
  apiFetch<{ status: string }>(`/api/favourites/${cbe}`, { method: "DELETE" });

// ── Feedback ───────────────────────────────────────────────
export const submitFeedback = (
  type: "bug" | "suggestion",
  description: string,
  page?: string,
  userEmail?: string
) =>
  apiFetch<{ status: string }>("/api/feedback", {
    method: "POST",
    body: JSON.stringify({ type, description, page, user_email: userEmail }),
  });
