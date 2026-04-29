/* Shared types for company detail page and tab components */

export interface CompanyDetail {
  enterprise_number: string;
  status: string;
  status_assessment?: {
    code: "active" | "in_liquidation" | "dissolved" | "stopped";
    since: string | null;
  };
  start_date: string | null;
  jf_code: string | null;
  jf_label: string | null;
  jf_label_nl: string | null;
  jf_label_fr: string | null;
  jf_short: string | null;
  jf_category: string | null;
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

export interface RepresentationChainLink {
  /** CBE of the entity (null when the node is a natural person). */
  cbe: string | null;
  name: string;
  role: string | null;
  /** 'legal' | 'natural' */
  person_type: string;
  /** 1-based depth in the chain (1 = direct representative of this admin). */
  depth: number;
  /** True when this node was already seen in the path — chain stops here. */
  cycle: boolean;
}

export interface Administrator {
  name: string;
  role: string;
  role_label: string;
  mandate_start: string | null;
  mandate_end: string | null;
  identifier: string | null;
  person_type: string | null;
  // Stage 3 provenance/freshness
  source?: "nbb" | "staatsblad" | "merged" | null;
  as_of?: string | null;
  pub_reference?: string | null;
  summary?: string | null;
  // Representation chain (populated when person_type='legal' and chain exists)
  representation_chain?: RepresentationChainLink[] | null;
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

export interface ParentCompany {
  /** CBE of the declaring parent (always present — comes from
   *  participating_interest.enterprise_number on the parent's filing). */
  enterprise_number: string;
  /** Resolved company name; falls back to the CBE if denomination is missing. */
  name: string;
  ownership_pct: number | null;
  country: string | null;
  fiscal_year: string | null;
}

export interface StaatsbladPub {
  pub_date: string;
  pub_type: string | null;
  reference: string | null;
  pdf_url: string | null;
}

export interface CompanyAffiliation {
  person_name: string;
  via_enterprise_number: string | null;
  via_company_name: string | null;
  fiscal_year: string | null;
  affiliation_type: string | null;
  last_seen_at: string | null;
}

export interface StructureData {
  administrators: Administrator[];
  administrator_events?: AdministratorEvent[];
  participating_interests: ParticipatingInterest[];
  shareholders: Shareholder[];
  /** Reverse-lookup against participating_interest: parents that
   *  declare this CBE in their own filing. Surfaces parent ownership
   *  even when this company itself never filed a shareholder schedule. */
  parent_companies?: ParentCompany[];
  staatsblad_publications: StaatsbladPub[];
  affiliations?: CompanyAffiliation[];
}

export interface FinancialsData {
  summary: FinancialRow[];
  rubric_data?: Record<string, Record<string, number | null>>;
  /** True when NBB has only PDF-only filings for this CBE — every recent
   *  deposit returned the "no published json xbrl" 404 from the API.
   *  Drives the "Filed as PDF" banner on tabs that would otherwise be
   *  empty for these companies. */
  pdf_only?: boolean;
}
