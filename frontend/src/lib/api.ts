import { createClient } from "./supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

/** Custom event fired when the backend returns a 429 tier limit response. */
export interface LimitExceededDetail {
  tier: "guest" | "registered";
  limitType: string;
  limit: number;
  used: number;
}

export const LIMIT_EXCEEDED_EVENT = "datasnoop:limit-exceeded";

/** Read the persisted UI locale (set by language-provider via localStorage).
 *  Returns ``undefined`` server-side or when no locale has been set.
 *  Used to thread ``?lang=`` into AI endpoints so the model writes in the
 *  user's chosen language. */
export function getStoredLocale(): "en" | "nl" | "fr" | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const v = localStorage.getItem("datasnoop_locale");
    if (v === "en" || v === "nl" || v === "fr") return v;
  } catch {
    // localStorage unavailable
  }
  return undefined;
}

/** Append ``?lang=<locale>`` (or ``&lang=...``) to a URL when a locale is set. */
function withLang(path: string): string {
  const lang = getStoredLocale();
  if (!lang) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}lang=${lang}`;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
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
    // Check for tier limit exceeded (429 with limit_exceeded detail)
    if (res.status === 429 && typeof window !== "undefined") {
      try {
        const body = await res.clone().json();
        if (body.detail === "limit_exceeded") {
          window.dispatchEvent(
            new CustomEvent(LIMIT_EXCEEDED_EVENT, {
              detail: {
                tier: body.tier,
                limitType: body.limit_type,
                limit: body.limit,
                used: body.used,
              } satisfies LimitExceededDetail,
            })
          );
        }
      } catch {
        // JSON parsing failed — fall through to generic error
      }
    }
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
  juridical_situation: string | null;
  start_date: string | null;
  fixed_assets: number | null;
  fte_growth_3y_pct?: number | null;
  rev_growth_pct?: number | null;
  ebitda_growth_pct?: number | null;
  rev_history?: (number | null)[] | null;
  ebitda_history?: (number | null)[] | null;
  year_history?: (number | null)[] | null;
  rev_rank_pct?: number | null;
  ebitda_rank_pct?: number | null;
  margin_rank_pct?: number | null;
  peer_count?: number | null;
  semantic_keywords?: string[] | null;
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
    if (v != null && v !== "") params.set(k, String(v));
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

// ── Search V2 — bucketed company search ──────────────────────────────────
// Backend returns `{commercial, nonprofit_or_public, total}` so the frontend
// can render separate sections. Each result carries its juridical-form
// category and an internal relevance score (score is exposed only for
// future ranking adjustments; the array order is already correct).
export interface CompanySearchResultV2 {
  enterprise_number: string;
  name: string;
  status: string | null;
  juridical_form: string | null;
  form_category: "commercial" | "nonprofit" | "public" | "other";
  city: string | null;
  sector: string | null;
  start_date: string | null;
  revenue: number | null;
  ebitda: number | null;
  ebitda_margin_pct: number | null;
  fte_total: number | null;
  fiscal_year: number | null;
  score: number;
}

export interface CompanySearchResponseV2 {
  q: string;
  commercial: CompanySearchResultV2[];
  nonprofit_or_public: CompanySearchResultV2[];
  total: { commercial: number; nonprofit_or_public: number };
}

// ── Search V2 — autocomplete payload ─────────────────────────────────────
export interface SuggestCompany {
  cbe: string;
  name: string;
  city: string | null;
  category: "commercial" | "nonprofit" | "public" | "other";
}
export interface SuggestPerson {
  name: string;
  company_count: number;
}
export interface SuggestCbeMatch {
  cbe: string;
  name: string;
}
export interface SuggestAddress {
  street: string | null;
  city: string | null;
  zipcode: string | null;
  cbe: string;
}
export interface SuggestResponse {
  q?: string;
  companies: SuggestCompany[];
  people: SuggestPerson[];
  cbe_match: SuggestCbeMatch | null;
  addresses: SuggestAddress[];
}

export interface CompanyDetail {
  enterprise_number: string;
  status: string;
  status_assessment?: {
    code: "active" | "in_liquidation" | "dissolved" | "stopped";
    since: string | null;
  };
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
  role_label?: string | null;
  person_type: string | null;
  identifier: string | null;
  mandate_start: string | null;
  mandate_end: string | null;
  representative_name: string | null;
  // Stage 3: provenance + freshness annotations
  source?: "nbb" | "staatsblad" | "merged" | null;
  as_of?: string | null;
  pub_reference?: string | null;
  summary?: string | null;
}

export interface AdministratorEvent {
  pub_date: string;
  pub_reference: string | null;
  sub_type: string | null;
  event_date: string | null;
  person_name: string | null;
  person_role: string | null;
  entity_name: string | null;
  summary: string | null;
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
  administrator_events?: AdministratorEvent[];
  shareholders: Shareholder[];
  participating_interests: ParticipatingInterest[];
  // Backend returns `staatsblad_publications` (snake_case preserved from
  // the DB column). Older clients read via unknown-cast; the typed field
  // is the canonical name going forward.
  staatsblad_publications: Publication[];
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

// V2 bucketed response — used by `/search` page which renders commercial
// and non-profit sections separately. Optional location filters (postal
// code / municipality / street) narrow results to companies whose
// registered address matches all provided fields.
export interface LocationFilter {
  postalCode?: string;
  municipality?: string;
  street?: string;
}

export const searchCompaniesBucketed = (
  q: string,
  loc?: LocationFilter,
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams({ q });
  if (loc?.postalCode?.trim()) params.set("postal_code", loc.postalCode.trim());
  if (loc?.municipality?.trim()) params.set("municipality", loc.municipality.trim());
  if (loc?.street?.trim()) params.set("street", loc.street.trim());
  return apiFetch<CompanySearchResponseV2>(
    `/api/companies/search?${params.toString()}`,
    { signal },
  );
};

// Legacy-compatible flat list. Most callers (aggregate page, compare,
// favourites picker, company picker, valuation tab) just want a flat
// ranked list to power a name-picker. We flatten commercial +
// nonprofit_or_public here and map the V2 fields back onto the old
// `SearchResult` shape so those callers don't need to change.
export const searchCompanies = async (q: string): Promise<SearchResult[]> => {
  const res = await apiFetch<CompanySearchResponseV2>(
    `/api/companies/search?q=${encodeURIComponent(q)}`,
  );
  const all = [...(res.commercial ?? []), ...(res.nonprofit_or_public ?? [])];
  return all.map((r) => ({
    enterprise_number: r.enterprise_number,
    name: r.name,
    status: r.status ?? "",
    // V1 callers read `jf_label` as the juridical-form code string.
    jf_label: r.juridical_form ?? null,
    city: r.city,
    sector: r.sector,
    start_date: r.start_date,
    revenue: r.revenue,
    ebitda: r.ebitda,
    ebitda_margin_pct: r.ebitda_margin_pct,
    fte_total: r.fte_total,
    fiscal_year: r.fiscal_year,
  }));
};

export const semanticSearch = (q: string) =>
  apiFetch<SearchResult[]>(`/api/companies/semantic-search?q=${encodeURIComponent(q)}`);

// V2: grouped autocomplete for the header combobox. Safe to call
// on every keystroke (debounced 150ms client-side). Supports
// AbortSignal so stale requests get cancelled.
export const suggestSearch = (q: string, signal?: AbortSignal) =>
  apiFetch<SuggestResponse>(
    `/api/search/suggest?q=${encodeURIComponent(q)}&limit=5`,
    { signal },
  );

// ── Stage 3e: Staatsblad structured-event search ──
export interface StaatsbladEvent {
  id: number;
  enterprise_number: string;
  pub_reference: string | null;
  pub_date: string;
  event_type: string;
  sub_type: string | null;
  event_date: string | null;
  person_name: string | null;
  person_role: string | null;
  entity_name: string | null;
  amount_eur: number | null;
  amount_shares: number | null;
  summary: string;
  extracted_at: string | null;
  extraction_model?: string | null;
  company_name?: string | null;
  vec_score?: number | null;
  trgm_score?: number | null;
}

export interface EventsSearchResponse {
  query: string;
  results: StaatsbladEvent[];
  count: number;
}

export const searchEvents = (
  q: string,
  opts?: { event_type?: string; since_date?: string; enterprise_number?: string; limit?: number },
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams({ q });
  if (opts?.event_type) params.set("event_type", opts.event_type);
  if (opts?.since_date) params.set("since_date", opts.since_date);
  if (opts?.enterprise_number) params.set("enterprise_number", opts.enterprise_number);
  if (opts?.limit) params.set("limit", String(opts.limit));
  return apiFetch<EventsSearchResponse>(
    `/api/events/search?${params.toString()}`,
    { signal },
  );
};

export const getCompanyEvents = (
  cbe: string,
  opts?: { event_type?: string; since_date?: string; limit?: number }
) => {
  const params = new URLSearchParams();
  if (opts?.event_type) params.set("event_type", opts.event_type);
  if (opts?.since_date) params.set("since_date", opts.since_date);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return apiFetch<{ events: StaatsbladEvent[] }>(
    `/api/companies/${cbe}/events${qs ? `?${qs}` : ""}`
  );
};

export const getCompanyDetail = (cbe: string) =>
  apiFetch<CompanyDetail>(`/api/companies/${cbe}`);

export const getCompanyFinancials = (cbe: string) =>
  apiFetch<CompanyFinancials>(`/api/companies/${cbe}/financials`);

export const getCompanyStructure = (cbe: string) =>
  apiFetch<CompanyStructure>(`/api/companies/${cbe}/structure`);

export const getCompanyNetwork = (cbe: string, maxDepth = 2) =>
  apiFetch<CompanyNetwork>(`/api/companies/${cbe}/network?max_depth=${maxDepth}`);

// ── Valuation (Vlerick M&A Monitor) ──
export interface ValuationSectorOption {
  key: string;
  label: string;
}

export interface ValuationYear {
  fiscal_year: number | null;
  ebitda: number | null;
  financial_debt: number;
  cash_and_equivalents: number;
  net_debt: number;
  by_size: { enterprise_value: number; equity_value: number | null };
  by_sector: { enterprise_value: number; equity_value: number | null };
}

export interface ValuationProfile {
  nace_code: string | null;
  size_bracket: string;
  size_bracket_label: string;
  size_multiple: number;
  vlerick_sector: string;
  vlerick_sector_label: string;
  vlerick_sector_source: "user_override" | "ai_classification" | "nace_mapping" | "fallback";
  ai_sector_confidence?: "high" | "medium" | "low" | null;
  ai_sector_reasoning?: string | null;
  sector_multiple: number;
  available_sectors: ValuationSectorOption[];
}

export interface ValuationReference {
  data_year: number;
  report: string;
  publisher: string;
  url: string;
  note: string;
}

export type MultipleSourceKey = "vlerick" | "damodaran" | "argos";

export interface MultipleSource {
  key: MultipleSourceKey;
  label: string;
  publisher?: string;
  url?: string;
  kind?: "transaction" | "listed";
  scope?: string;
  note?: string;
  has_size: boolean;
  has_sector: boolean;
  data_year?: number;
}

export interface ValuationGroupMember {
  cbe: string;
  name: string;
}

export interface ValuationGroup {
  primary_cbe: string;
  primary_name: string;
  included: ValuationGroupMember[];
  label: string;
  partial_years: number[];
}

export interface ValuationData {
  status: "ok" | "no_financial_data";
  profile?: ValuationProfile;
  group?: ValuationGroup | null;
  years: ValuationYear[];
  source?: MultipleSource;
  available_sources?: MultipleSource[];
  vlerick_reference: ValuationReference;
  pro_memoria_note?: string;
}

export const getCompanyValuation = (
  cbe: string,
  sectorOverride?: string,
  source?: MultipleSourceKey,
  includeCbes?: string[],
) => {
  const params = new URLSearchParams();
  if (sectorOverride) params.set("sector", sectorOverride);
  if (source) params.set("source", source);
  if (includeCbes && includeCbes.length > 0) params.set("include", includeCbes.join(","));
  const qs = params.toString();
  return apiFetch<ValuationData>(`/api/companies/${cbe}/valuation${qs ? `?${qs}` : ""}`);
};

export const getValuationAiCommentary = (
  cbe: string,
  sectorOverride?: string,
  source?: MultipleSourceKey,
  includeCbes?: string[],
) => {
  const params = new URLSearchParams();
  if (sectorOverride) params.set("sector", sectorOverride);
  if (source) params.set("source", source);
  if (includeCbes && includeCbes.length > 0) params.set("include", includeCbes.join(","));
  const qs = params.toString();
  return apiFetch<{
    sector_rationale?: string | null;
    valuation_remarks?: string | null;
    commentary?: string | null;
    reason?: string;
  }>(
    withLang(`/api/companies/${cbe}/valuation/ai-commentary${qs ? `?${qs}` : ""}`),
    { method: "POST" }
  );
};

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

export const getDeepNetwork = (
  cbe: string,
  depth?: number,
  includeHistorical?: boolean,
) => {
  const params = new URLSearchParams();
  if (depth) params.set("depth", String(depth));
  if (includeHistorical) params.set("include_historical", "true");
  const qs = params.toString();
  return apiFetch<DeepNetworkResponse>(
    `/api/companies/${encodeURIComponent(cbe)}/deep-network${qs ? `?${qs}` : ""}`,
  );
};

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

export interface SectorScatterPoint {
  cbe: string;
  name: string | null;
  city: string | null;
  revenue: number;
  ebitda: number;
  fte: number | null;
  margin_pct: number | null;
}

export const getStatsSectorScatter = (nace: string, limit = 300) =>
  apiFetch<SectorScatterPoint[]>(`/api/stats/sector-scatter?nace=${encodeURIComponent(nace)}&limit=${limit}`);

export const getStatsSizeDistribution = (province?: string) =>
  apiFetch<SizeBucket[]>(`/api/stats/size-distribution${province ? `?province=${province}` : ""}`);

export const getStatsEvolution = (yMin = 2021, yMax = 2024, province?: string) =>
  apiFetch<EvolutionYear[]>(`/api/stats/evolution?y_min=${yMin}&y_max=${yMax}${province ? `&province=${province}` : ""}`);

export const getStatsProvinces = () =>
  apiFetch<ProvinceStats[]>(`/api/stats/provinces`);

// ── Outperformer Buckets (experimental) ────────────────────
export type BucketName = "revenue_growers" | "high_margin" | "margin_growers" | "other";

export interface BucketSummary {
  count: number;
  median_metric_pct: number | null;
  metric_label: string;
  total_revenue_m: number;
}

export interface OutperformersOverview {
  base_year: number;
  end_year: number;
  universe: number;
  thresholds: {
    min_revenue: number;
    revenue_growth_pct: number;
    high_margin_pct: number;
    margin_growth_pct: number;
  };
  buckets: Record<BucketName, BucketSummary>;
}

export interface BucketSector {
  nace2: string;
  sector: string;
  companies: number;
  revenue_m: number;
  ebitda_m: number;
}

export interface BucketCompany {
  cbe: string;
  name: string;
  nace_code: string | null;
  sector: string | null;
  city: string | null;
  rev_23: number | null;
  rev_25: number | null;
  ebitda_23: number | null;
  ebitda_25: number | null;
  rev_growth_pct: number | null;
  margin_25: number | null;
  margin_23: number | null;
  margin_growth_pct: number | null;
}

export interface OutperformersBreakdown {
  bucket: BucketName;
  sectors: BucketSector[];
  companies: BucketCompany[];
}

export const getOutperformersOverview = () =>
  apiFetch<OutperformersOverview>(`/api/stats/outperformers/overview`);

export const getOutperformersBreakdown = (
  bucket: BucketName,
  topSectors = 15,
  topCompanies = 25,
) =>
  apiFetch<OutperformersBreakdown>(
    `/api/stats/outperformers/breakdown?bucket=${bucket}&top_sectors=${topSectors}&top_companies=${topCompanies}`,
  );

// ── People ─────────────────────────────────────────────────
// V2: top_companies is an array of {name, cbe} objects so each entry
// can render as a clickable /company/{cbe} link. The bare-string form
// is kept in the union for backward compatibility during rolling
// deploys (older servers still return string[]).
export interface PersonTopCompany {
  name: string;
  cbe: string;
  // True iff the person→company link came only from the affiliation
  // table (representing a corporate director elsewhere). Frontend
  // renders affiliation-only entries with a softer pill + tooltip so
  // operators can tell a direct mandate from a documented-affiliation.
  affiliation_only?: boolean;
}
export interface PersonResult {
  name: string;
  roles?: number;
  companies?: number;
  holdings?: number;
  company_count: number;
  top_companies?: (PersonTopCompany | string)[];
  score?: number;
}

export interface PersonConnection {
  company_name: string;
  enterprise_number: string;
  role: string;
  type: string;
}

// V3 person profile (#19) — richer shape for the new /people/[name]
// profile page. Backward compat types above stay for legacy callers.
export interface PersonAdminRole {
  enterprise_number: string;
  company_name: string | null;
  role: string | null;
  role_label: string | null;
  mandate_start: string | null;
  mandate_end: string | null;
  source: "nbb" | "staatsblad" | "merged" | null;
  as_of: string | null;
  pub_reference?: string | null;
  sub_type?: string | null;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  fiscal_year: number | string | null;
}

export interface PersonShareholding {
  enterprise_number: string;
  company_name: string | null;
  ownership_pct: number | null;
  shares_held: number | null;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  fiscal_year: number | string | null;
}

// Source filing that introduced one affiliation row. A single
// (person, company) affiliation can have multiple sources when several
// filings of the "via" company name the same rep — surface them as
// breadcrumbs so the user can verify provenance.
export interface PersonAffiliationSource {
  via_enterprise_number: string | null;
  via_company_name: string | null;
  via_deposit_key: string | null;
  fiscal_year: string | null;
}

export interface PersonAffiliation {
  enterprise_number: string;
  company_name: string | null;
  // First / latest filing that introduced the link. Older ones may
  // be stale (rep changed since), `last_seen_at` lets us flag that.
  first_seen_at: string | null;
  last_seen_at: string | null;
  affiliation_type: string;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  // The latest fiscal_year on the AFFILIATED company's financials,
  // not the via-filing's fiscal_year (which lives in `sources`).
  fiscal_year: number | string | null;
  sources: PersonAffiliationSource[];
}

export interface PersonProfile {
  name: string;
  total_companies: number;
  admin_count: number;
  holding_count: number;
  affiliation_count?: number;
  administrator_roles: PersonAdminRole[];
  shareholdings: PersonShareholding[];
  affiliations?: PersonAffiliation[];
}

export const searchPeople = (q: string, signal?: AbortSignal) =>
  apiFetch<PersonResult[]>(
    `/api/people/search?q=${encodeURIComponent(q)}`,
    { signal },
  );

export const getPersonConnections = (name: string) =>
  apiFetch<PersonProfile>(
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

// ── Bulk Import ────────────────────────────────────────────────
export interface ImportMatchRow {
  input_name: string;
  best_match_name: string | null;
  enterprise_number: string | null;
  city: string | null;
  score: number;
}

export interface ImportMatchResponse {
  results: ImportMatchRow[];
  input_count: number;
  matched_count: number;
}

export interface ImportConfirmResponse {
  added: number;
  skipped: number;
  not_found: string[];
}

// ── Timeline ──────────────────────────────────────────────
export type TimelineEventKind =
  | "founding"
  | "filing"
  | "publication"
  | "mandate_start"
  | "mandate_end";

export interface TimelineEvent {
  date: string;
  kind: TimelineEventKind;
  label: string;
  ref: string | null;
}

export const getCompanyTimeline = (cbe: string) =>
  apiFetch<{ events: TimelineEvent[] }>(`/api/companies/${cbe}/timeline`);

export const importMatchNames = (names: string[]) =>
  apiFetch<ImportMatchResponse>("/api/import/match", {
    method: "POST",
    body: JSON.stringify({ names }),
  });

export const importConfirmCbes = (enterprise_numbers: string[]) =>
  apiFetch<ImportConfirmResponse>("/api/import/confirm", {
    method: "POST",
    body: JSON.stringify({ enterprise_numbers }),
  });

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
  governance_loaded?: {
    administrators: number;
    shareholders: number;
    participating_interests: number;
    affiliations?: number;
  };
  status?: string;
  /** True when NBB has only PDF-only filings for this CBE (every recent
   *  deposit returned the "no published json xbrl" 404). */
  pdf_only?: boolean;
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

// ── Staatsblad Admin Extraction ──────────────────────────
export const extractAdminsFromStaatsblad = (cbe: string) =>
  apiFetch<{ extracted: number }>(`/api/companies/${cbe}/extract-admins`, { method: "POST" });

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

export interface SimilarCustomerSuggestion {
  enterprise_number: string;
  name: string;
  city: string;
  revenue: number | null;
  nace_code: string;
  reason: string;
}

export const suggestSimilarCustomers = () =>
  apiFetch<SimilarCustomerSuggestion[]>('/api/favourites/customers/suggest-similar', { method: 'POST' });

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

export interface SimilarCompany {
  enterprise_number: string;
  name: string;
  city: string;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  fiscal_year: number;
  ebit: number | null;
  net_profit: number | null;
  equity: number | null;
  total_assets: number | null;
  personnel_costs: number | null;
}

export const getSimilarCompanies = (cbe: string) =>
  apiFetch<SimilarCompany[]>(`/api/companies/${cbe}/similar`);

// ── AI Enrichment ─────────────────────────────────────────
export const enrichCompany = (cbe: string) =>
  apiFetch<{ summary: string }>(withLang(`/api/companies/${cbe}/enrich`), { method: "POST" });

// Threads ?lang= so cached AI is auto-translated to the user's site language.
export const getEnrichment = (cbe: string) =>
  apiFetch<{
    summary: string;
    generated_at: string;
    website_summary: string | null;
    linkedin_summary: string | null;
    website_url: string | null;
    ai_insights: string | null;
  } | null>(withLang(`/api/companies/${cbe}/enrichment`));

export const enrichPerson = (name: string) =>
  apiFetch<{ summary: string }>(withLang(`/api/people/${encodeURIComponent(name)}/enrich`), { method: "POST" });

export const getPersonEnrichment = (name: string) =>
  apiFetch<{ summary: string; generated_at: string } | null>(withLang(`/api/people/${encodeURIComponent(name)}/enrichment`));

// ── AI Insights: Website & LinkedIn ──────────────────────
export const scrapeCompanyWebsite = (cbe: string) =>
  apiFetch<{ summary: string; products: string; employees: string; key_people: string; website_url: string }>(
    `/api/companies/${cbe}/scrape-website`, { method: "POST" }
  );

export const scrapeCompanyLinkedIn = (cbe: string) =>
  apiFetch<{ summary: string; employee_count: string; industry: string; specialties: string; linkedin_url: string }>(
    `/api/companies/${cbe}/scrape-linkedin`, { method: "POST" }
  );

// ── Graveyard ─────────────────────────────────────────────
export interface GraveyardStatusBucket {
  status: string;
  label: string;
  count: number;
}

export interface GraveyardSituationBucket {
  code: string;
  label: string;
  count: number;
}

export interface GraveyardDecadeBucket {
  decade: number;
  count: number;
}

export interface GraveyardOverview {
  active_count: number;
  non_active_count: number;
  by_status: GraveyardStatusBucket[];
  by_situation: GraveyardSituationBucket[];
  by_decade: GraveyardDecadeBucket[];
}

export interface RepeatOffender {
  name: string;
  failed_count: number;
  active_count: number;
}

export interface RepeatOffendersResponse {
  offenders: RepeatOffender[];
  total: number;
}

export interface FailedCompanyDetail {
  enterprise_number: string;
  company_name: string;
  role: string | null;
  role_label: string | null;
  mandate_start: string | null;
  mandate_end: string | null;
  status?: string;
  status_label?: string;
  juridical_situation?: string;
  situation_label?: string;
  start_date?: string | null;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  fiscal_year: number | null;
}

export interface PersonCompaniesResponse {
  name: string;
  failed_companies: FailedCompanyDetail[];
  active_companies: FailedCompanyDetail[];
}

export const getGraveyardOverview = () =>
  apiFetch<GraveyardOverview>("/api/graveyard/overview");

export const getRepeatOffenders = (minFailed = 2, limit = 100) =>
  apiFetch<RepeatOffendersResponse>(
    `/api/graveyard/repeat-offenders?min_failed=${minFailed}&limit=${limit}`
  );

export const getPersonFailedCompanies = (name: string) =>
  apiFetch<PersonCompaniesResponse>(
    `/api/graveyard/person/${encodeURIComponent(name)}/companies`
  );

// ── Graveyard: In-Process (live bankruptcy / WCO cases) ───
export type InProcessBucket = "bankruptcy" | "wco";

export interface InProcessCase {
  enterprise_number: string;
  company_name: string;
  juridical_situation: string | null;
  situation_label: string | null;
  bucket: InProcessBucket;
  docket_number: string | null;
  court: string | null;
  opened_at: string | null;
  curator_name: string | null;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  fiscal_year: number | null;
}

export interface InProcessResponse {
  cases: InProcessCase[];
  total: number;
  bankruptcy_count: number;
  wco_count: number;
  curator_assigned_count: number;
}

export const getInProcessCases = (
  caseType?: "bankruptcy" | "wco",
  limit = 200,
) => {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (caseType) qs.set("case_type", caseType);
  return apiFetch<InProcessResponse>(`/api/graveyard/in-process?${qs}`);
};

// ── Graveyard: Director Aging (time before bankruptcy) ───
export interface DirectorAgingRow {
  name: string;
  total: number;
  at_bankruptcy: number;
  within_6m: number;
  within_1y: number;
  within_2y: number;
  within_3y: number;
  older: number;
}

export interface DirectorAgingBucketMeta {
  key: keyof Omit<DirectorAgingRow, "name" | "total">;
  label: string;
  order: number;
}

export interface DirectorAgingResponse {
  directors: DirectorAgingRow[];
  total: number;
  buckets: DirectorAgingBucketMeta[];
}

export const getDirectorAging = (minTotal = 2, limit = 200) =>
  apiFetch<DirectorAgingResponse>(
    `/api/graveyard/director-aging?min_total=${minTotal}&limit=${limit}`
  );

// ── AI Insights (structured multi-step pipeline) ─────────
export interface AiInsights {
  business_description: string;
  products: string[];
  customers: string;
  market_position: string;
  history: string;
  key_management?: {
    name: string;
    role: string;
    linkedin_url: string;
    /** Server-annotated source/freshness signal; lets the UI render a
     *  trust chip without re-querying the administrator table.
     *   - kbo_active   = name corroborated by an open KBO mandate.
     *   - kbo_resigned = name matches a historical KBO mandate (resigned).
     *   - website_only = no KBO match (could be stale or a non-board hire). */
    mandate_status?: "kbo_active" | "kbo_resigned" | "website_only";
  }[];
  group_context?: string;
  confidence?: string;
  source_attribution?: Record<string, string>;
  quality_warning?: boolean;
  website_url: string;
  linkedin_url: string;
  /** Phase 5 — server set true when the row was served from the
   * bulk_summary cache or KBO skeleton and the qwen+kimi elaboration is
   * running in the background. Frontend polls for the upgraded narrative. */
  upgrade_in_progress?: boolean;
  /** Phase 5 — `narrative_lite` / `bulk_only` / `bulk_escalated` / `skeleton`. */
  quality_tier?: string;
  from_cache?: boolean;
}

export const generateAiInsights = (cbe: string, signal?: AbortSignal) =>
  apiFetch<AiInsights>(withLang(`/api/companies/${cbe}/ai-insights`), { method: "POST", signal });

export const submitInsightsFeedback = (cbe: string, feedback: { overall: string; websiteCorrect?: boolean; linkedinCorrect?: boolean; insightCorrect?: boolean; comment?: string }) =>
  apiFetch<{ status: string }>(`/api/companies/${cbe}/ai-insights/feedback`, { method: "POST", body: JSON.stringify(feedback) });

export const summarizePublications = (cbe: string, refresh = false) =>
  apiFetch<{ summary: string | null; cached: boolean; error?: string }>(withLang(`/api/companies/${cbe}/summarize-publications`), {
    method: "POST",
    body: JSON.stringify({ refresh }),
  });

export const getAiSimilarCompanies = (cbe: string, limit?: number) =>
  apiFetch<SimilarCompany[]>(
    limit ? `/api/companies/${cbe}/similar/ai?limit=${limit}` : `/api/companies/${cbe}/similar/ai`,
  );
