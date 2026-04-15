import { createClient } from "./supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };

  // Attach auth token if available (only in browser)
  if (typeof window !== "undefined") {
    try {
      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      if (data.session?.access_token) {
        headers["Authorization"] = `Bearer ${data.session.access_token}`;
      }
    } catch {
      // No auth available — continue without token
    }
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
  jf_label: string | null;
  start_date: string | null;
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

export interface NaceSuggestion {
  nace_code: string;
  description: string;
  company_count: number | null;
}

export const getNaceSuggestions = (q: string) =>
  apiFetch<NaceSuggestion[]>(`/api/screener/nace-suggestions?q=${encodeURIComponent(q)}`);

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
  website: string | null;
}

export interface FinancialYear {
  fiscal_year: number;
  revenue: number | null;
  gross_margin: number | null;
  ebit: number | null;
  da: number | null;
  ebitda: number | null;
  ebitda_margin_pct: number | null;
  net_profit: number | null;
  equity: number | null;
  lt_debt: number | null;
  lt_financial_debt: number | null;
  st_financial_debt: number | null;
  cash: number | null;
  total_assets: number | null;
  fixed_assets: number | null;
  inventories: number | null;
  trade_receivables: number | null;
  trade_payables: number | null;
  financial_charges: number | null;
  current_investments: number | null;
  fte_total: number | null;
  personnel_costs: number | null;
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

// ── Deep Network (hidden connections through 3rd/4th degree) ──
export interface DeepNetworkNode {
  id: string;
  name: string;
  type: string;
  depth: number;
}

export interface DeepNetworkEdge {
  source: string;
  target: string;
  relationship: string;
  label: string;
}

export interface DeepNetworkResponse {
  nodes: DeepNetworkNode[];
  edges: DeepNetworkEdge[];
  truncated: boolean;
  depth_reached: number;
}

export const getDeepNetwork = (cbe: string, depth?: number) =>
  apiFetch<DeepNetworkResponse>(`/api/companies/${cbe}/deep-network${depth ? `?depth=${depth}` : ''}`);

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

export interface MarginBucket {
  margin_bucket: number;
  n: number;
}

export interface SizeBucket {
  size_bucket: string;
  sort_key: number;
  companies: number;
  revenue_m: number;
}

export interface EvolutionYear {
  fiscal_year: number;
  companies: number;
  revenue_m: number;
  ebitda_m: number;
  ebit_m: number;
  net_profit_m: number;
  nfd_m: number;
}

export interface ProvinceStats {
  province: string;
  companies: number;
  revenue_m: number;
  ebitda_m: number;
  med_margin: number | null;
  total_fte: number;
  med_fte: number | null;
}

export const getStatsMarginDistribution = (province?: string) =>
  apiFetch<MarginBucket[]>(`/api/stats/margin-distribution${province ? `?province=${province}` : ""}`);

export const getStatsSizeDistribution = (province?: string) =>
  apiFetch<SizeBucket[]>(`/api/stats/size-distribution${province ? `?province=${province}` : ""}`);

export const getStatsEvolution = (yMin = 2021, yMax = 2024, province?: string) =>
  apiFetch<EvolutionYear[]>(`/api/stats/evolution?y_min=${yMin}&y_max=${yMax}${province ? `&province=${province}` : ""}`);

export const getStatsProvinces = () =>
  apiFetch<ProvinceStats[]>(`/api/stats/provinces`);

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

// ── Favourite Projects ────────────────────────────────────────
export interface ProjectMember {
  enterprise_number: string;
  name: string | null;
  city: string | null;
  nace_code: string | null;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
}

export interface FavouriteProject {
  id: number;
  name: string;
  created_at: string;
  members: ProjectMember[];
}

export const getFavouriteProjects = () =>
  apiFetch<FavouriteProject[]>("/api/favourites/projects");

export const createFavouriteProject = (name: string) =>
  apiFetch<FavouriteProject>("/api/favourites/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const addProjectMember = (projectId: number, enterprise_number: string) =>
  apiFetch<{ status: string }>(`/api/favourites/projects/${projectId}/add`, {
    method: "POST",
    body: JSON.stringify({ enterprise_number }),
  });

export const removeProjectMember = (projectId: number, cbe: string) =>
  apiFetch<{ status: string }>(`/api/favourites/projects/${projectId}/remove/${cbe}`, {
    method: "DELETE",
  });

export const deleteFavouriteProject = (projectId: number) =>
  apiFetch<{ status: string }>(`/api/favourites/projects/${projectId}`, {
    method: "DELETE",
  });

// ── NBB Load ──────────────────────────────────────────────
export interface NbbLoadResult {
  enterprise_number: string;
  filings_found: number;
  filings_loaded: number;
  rubrics_loaded: number;
  status?: string;
}

export const loadCompanyNBB = (cbe: string) =>
  apiFetch<NbbLoadResult>(`/api/companies/${cbe}/load`, { method: "POST" });

// ── Staatsblad Publications On-Demand ─────────────────────
export interface StaatsbladLoadResult {
  enterprise_number: string;
  publications_found: number;
  publications_stored: number;
}

export const loadPublications = (cbe: string) =>
  apiFetch<StaatsbladLoadResult>(`/api/staatsblad/${cbe}/load`, { method: "POST" });

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

// ── Notifications ──────────────────────────────────────────
export interface FavNotification {
  enterprise_number: string;
  name: string;
  loaded_at: string;
  fiscal_year: number;
}

export const getNotifications = () =>
  apiFetch<{ notifications: FavNotification[]; count: number }>("/api/favourites/notifications");

export const markNotificationsRead = () =>
  apiFetch<{ status: string }>("/api/favourites/notifications/mark-read", { method: "POST" });

// ── People Favourites ─────────────────────────────────────
export interface PeopleFavourite {
  person_name: string;
  notes: string | null;
  added_at: string;
  company_count: number;
  companies: string | null;
}

export const getPeopleFavourites = () =>
  apiFetch<PeopleFavourite[]>("/api/favourites/people");

export const addPeopleFavourite = (personName: string, notes?: string) =>
  apiFetch<{ person_name: string; status: string }>("/api/favourites/people", {
    method: "POST",
    body: JSON.stringify({ person_name: personName, notes }),
  });

export const removePeopleFavourite = (personName: string) =>
  apiFetch<{ person_name: string; status: string }>(
    `/api/favourites/people/${encodeURIComponent(personName)}`,
    { method: "DELETE" }
  );

// ── Customers & Suppliers ─────────────────────────────────
export interface CustomerSupplierItem {
  enterprise_number: string;
  name: string | null;
  custom_name: string | null;
  city: string | null;
  revenue: number | null;
  ebitda: number | null;
  margin_pct: number | null;
  fte_total: number | null;
  added_at: string;
  notes: string | null;
}

export interface CsUploadResult {
  matched: number;
  not_found: number;
  total: number;
  not_found_cbes: string[];
}

export const getCustomers = () =>
  apiFetch<CustomerSupplierItem[]>("/api/favourites/customers");

export const getSuppliers = () =>
  apiFetch<CustomerSupplierItem[]>("/api/favourites/suppliers");

export const uploadCustomers = (enterprise_numbers: string[]) =>
  apiFetch<CsUploadResult>("/api/favourites/customers/upload", {
    method: "POST",
    body: JSON.stringify({ enterprise_numbers }),
  });

export const uploadSuppliers = (enterprise_numbers: string[]) =>
  apiFetch<CsUploadResult>("/api/favourites/suppliers/upload", {
    method: "POST",
    body: JSON.stringify({ enterprise_numbers }),
  });

export const removeCustomer = (cbe: string) =>
  apiFetch<{ status: string }>(`/api/favourites/customers/${cbe}`, { method: "DELETE" });

export const removeSupplier = (cbe: string) =>
  apiFetch<{ status: string }>(`/api/favourites/suppliers/${cbe}`, { method: "DELETE" });

// ── Sector Benchmark ───────────────────────────────────────
export interface BenchmarkMetric {
  metric: string;
  format: string;
  value: number | null;
  percentile: number | null;
  p25: number | null;
  median: number | null;
  p75: number | null;
  peer_count: number;
}

export interface SectorBenchmark {
  nace_code: string;
  nace_label: string;
  fiscal_year: number;
  peer_count: number;
  benchmarks: BenchmarkMetric[];
  error?: string;
}

export const getSectorBenchmark = (cbe: string) =>
  apiFetch<SectorBenchmark>(`/api/companies/${cbe}/sector-benchmark`);

export const getSimilarCompanies = (cbe: string) =>
  apiFetch<{ enterprise_number: string; name: string; city: string; revenue: number | null; ebitda: number | null; fte_total: number | null; fiscal_year: number }[]>(`/api/companies/${cbe}/similar`);

// ── AI Enrichment ─────────────────────────────────────────
export const enrichCompany = (cbe: string) =>
  apiFetch<{ summary: string }>(`/api/companies/${cbe}/enrich`, { method: "POST" });

export const getEnrichment = (cbe: string) =>
  apiFetch<{ summary: string; generated_at: string } | null>(`/api/companies/${cbe}/enrichment`);
