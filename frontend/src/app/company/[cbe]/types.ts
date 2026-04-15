/* Shared types for company detail page and tab components */

export interface CompanyDetail {
  enterprise_number: string;
  status: string;
  start_date: string | null;
  jf_label: string | null;
  name: string | null;
  zipcode: string | null;
  city: string | null;
  municipality: string | null;
  street: string | null;
  house_number: string | null;
  nace_code: string | null;
  nace_label: string | null;
  website: string | null;
}

export interface FinancialRow {
  fiscal_year: number;
  deposit_key: string | null;
  filing_model: string | null;
  revenue: number | null;
  gross_margin: number | null;
  ebit: number | null;
  da: number | null;
  ebitda: number | null;
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
  ebitda_margin_pct: number | null;
}

export interface Administrator {
  name: string;
  role: string;
  role_label: string;
  mandate_start: string | null;
  mandate_end: string | null;
  identifier: string | null;
  person_type: string | null;
}

export interface Shareholder {
  name: string;
  ownership_pct: number | null;
  shareholder_type: string | null;
  identifier: string | null;
  fiscal_year: string | null;
}

export interface ParticipatingInterest {
  name: string;
  ownership_pct: number | null;
  country: string | null;
  identifier: string | null;
  fiscal_year: string | null;
}

export interface StaatsbladPub {
  pub_date: string;
  pub_type: string | null;
  reference: string | null;
  pdf_url: string | null;
}

export interface StructureData {
  administrators: Administrator[];
  participating_interests: ParticipatingInterest[];
  shareholders: Shareholder[];
  staatsblad_publications: StaatsbladPub[];
}

export interface FinancialsData {
  summary: FinancialRow[];
  rubric_data?: Record<string, Record<string, number | null>>;
}
