export interface AdminStats {
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

export interface UserRow {
  email: string;
  role: string;
  created_at: string;
  favourites_count: number;
  feedback_count: number;
}

export interface FeedbackRow {
  id: number;
  type: string;
  page: string | null;
  description: string;
  user_email: string | null;
  created_at: string;
  reply: string | null;
  replied_at: string | null;
}

export interface ActivitySummary {
  user_email: string;
  total_requests: number;
  unique_pages: number;
  last_active: string;
}

export interface ActivityEntry {
  user_email: string;
  endpoint: string;
  method: string;
  created_at: string;
}

export interface StripePayment {
  id: string;
  amount: number;
  currency: string;
  status: string;
  email: string | null;
  created: string;
  mode: string;
}

export interface PaymentsData {
  payments: StripePayment[];
  total_revenue: number;
  currency: string;
}

export interface ARRData {
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

export interface InvoiceRow {
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

export interface InvoicesData {
  invoices: InvoiceRow[];
  monthly: {
    ym: string;
    cents_total: number;
    eur_total: number;
    invoices: number;
  }[];
}

export interface PnlPeriod {
  window_start: string;
  window_end: string;
  revenue_eur: number;
  openrouter_eur: number;
  invoices_by_category: {
    category: string;
    eur: number;
  }[];
  invoices_total_eur: number;
  net_eur: number;
}

export interface PnlSummary {
  monthly: PnlPeriod;
  sixMonth: PnlPeriod;
  yearly: PnlPeriod;
}

export interface Insights {
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
  top_companies: {
    cbe: string;
    name: string;
    view_count: number;
  }[];
}

export interface AdoptionData {
  kpis: {
    total_registered: number;
    active_7d: number;
    active_30d: number;
    sessions_today: number;
    active_prev_7d: number;
    active_prev_30d: number;
    sessions_yesterday: number;
  };
  daily_trend: {
    day: string;
    dau: number;
    page_views: number;
  }[];
  features: {
    feature: string;
    requests: number;
    unique_users: number;
  }[];
  top_users: {
    email: string;
    session_days: number;
    total_requests: number;
    last_active: string;
  }[];
  recent: {
    user_email: string;
    endpoint: string;
    method: string;
    created_at_be: string;
  }[];
}

export interface TractionData {
  kpis: Record<string, number>;
  engagement: Record<string, number>;
  daily_trend: {
    day: string;
    unique_guests: number;
    unique_registered: number;
    total_requests: number;
  }[];
  hourly_today: {
    hour: number;
    requests: number;
    guests: number;
    registered: number;
  }[];
  guest_pages: {
    feature: string;
    requests: number;
    unique_guests: number;
  }[];
  registered_pages: {
    feature: string;
    requests: number;
    unique_users: number;
  }[];
  signups: {
    day: string;
    new_users: number;
  }[];
  stickiness: {
    days_active: number;
    user_count: number;
  }[];
  top_guests: {
    ip: string;
    unique_pages: number;
    total_requests: number;
    first_seen: string;
    last_seen: string;
  }[];
}

export interface CostItem {
  name: string;
  amount: number;
  frequency: "monthly" | "yearly" | "one-time";
}

export interface CostsData {
  openrouter_usage_usd: number;
  openrouter_limit_usd: number;
  cost_items: CostItem[];
  ai_calls_30d: Record<string, number>;
}

export interface LlmCostBreakdownRow {
  kind: string;
  calls: number;
  est_cost_per_call_usd: number;
  est_total_usd: number;
}

export interface LlmCostBreakdown {
  window_days: number;
  calls_total: number;
  est_total_usd: number;
  est_avg_per_call_usd: number;
  breakdown: LlmCostBreakdownRow[];
  note: string;
}

export interface Poll {
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

export interface TierConfig {
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

export interface NbbBackloadProgress {
  active_targets: number;
  retired_no_filings: number;
  retired_pdf_only: number;
  companies_with_financial_history: number;
  financial_year_rows: number;
  fy2024_remaining: number;
  fy2023_remaining: number;
  fy2022_remaining: number;
  last_checkpoint: string | null;
  rows_1h: number;
  no_filings_1h: number;
  real_filings_1h: number;
  pdf_only_1h: number;
  rows_24h: number;
  no_filings_24h: number;
  real_filings_24h: number;
  pdf_only_24h: number;
  first_seen_24h: string | null;
  last_seen_24h: string | null;
  rows_7d: number;
  no_filings_7d: number;
  real_filings_7d: number;
  pdf_only_7d: number;
  eta_days_from_24h_pace: number | null;
  hourly_loads_24h: {
    hour_local: string;
    hour_label: string;
    total: number;
    no_filings: number;
    real_filings: number;
    pdf_only: number;
  }[];
  recent_real_filings: {
    enterprise_number: string;
    deposit_key: string;
    rubric_count: number;
    loaded_at: string;
  }[];
}

export interface StaatsbladBackloadProgress {
  done: number;
  pending: number;
  in_progress: number;
  failed: number;
  final_goal: number;
  resolved: number;
  completion_pct: number;
  resolved_pct: number;
  processed_24h: number;
  processed_7d: number;
  pubs_found_24h: number;
  eta_days_from_24h_pace: number | null;
  last_completed_at: string | null;
  hourly_loads_24h: {
    hour_local: string;
    hour_label: string;
    completed: number;
  }[];
  recent_completions: {
    cbe: string;
    pubs_found: number | null;
    completed_at: string;
    attempts: number;
  }[];
}

export interface SiteConfig {
  site_logo: string;
}

export interface OverviewData {
  insights: Insights | null;
  polls: Poll[];
}

export interface PeopleData {
  users: UserRow[];
  feedback: FeedbackRow[];
  polls: Poll[];
  tiers: TierConfig[];
}

export interface RevenueData {
  payments: PaymentsData | null;
  costs: CostsData | null;
  arr: ARRData | null;
  pnl: PnlSummary | null;
  llm: LlmCostBreakdown | null;
  invoices: InvoicesData | null;
}

export interface PipelineData {
  financialsByYear: {
    fiscal_year: number;
    companies: number;
    filings: number;
  }[];
  nbb: NbbBackloadProgress | null;
  staatsblad: StaatsbladBackloadProgress | null;
}

export interface AnalyticsData {
  insights: Insights | null;
  usage: {
    daily: {
      day: string;
      registered_requests: number;
      guest_requests: number;
      unique_registered: number;
      unique_guests: number;
    }[];
    top_pages: {
      page: string;
      requests: number;
      unique_users: number;
    }[];
    top_registered: {
      user_email: string;
      requests: number;
      unique_pages: number;
      last_seen: string;
    }[];
    top_guests: {
      ip: string;
      requests: number;
      unique_pages: number;
      last_seen: string;
    }[];
    totals: {
      total_requests_30d: number;
      guest_requests_30d: number;
      registered_requests_30d: number;
      unique_registered_30d: number;
      unique_guests_30d: number;
    };
  } | null;
  adoption: AdoptionData | null;
  traction: TractionData | null;
  activity: ActivityEntry[];
  activitySummary: ActivitySummary[];
}
