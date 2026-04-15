/** Shared types for export data preparation. */

export interface CompanyDetail {
  enterprise_number: string;
  name: string | null;
  status: string;
  start_date: string | null;
  jf_label: string | null;
  zipcode: string | null;
  city: string | null;
  street: string | null;
  house_number: string | null;
  nace_code: string | null;
  nace_label: string | null;
  website: string | null;
}

export interface FinancialRow {
  fiscal_year: number;
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

export interface StructureData {
  administrators: Administrator[];
  shareholders: Shareholder[];
  participating_interests: ParticipatingInterest[];
}

export interface BenchmarkMetric {
  metric: string;
  format: string;
  value: number | null;
  percentile: number | null;
  p25: number | null;
  median: number | null;
  p75: number | null;
}

export interface SectorBenchmark {
  nace_code: string;
  nace_label: string;
  fiscal_year: number;
  peer_count: number;
  benchmarks: BenchmarkMetric[];
}

// Derived row types
export interface PnlRow {
  fiscal_year: number;
  revenue: number | null;
  costOfSales: number | null;
  grossMargin: number | null;
  personnel: number | null;
  da: number | null;
  otherOpCosts: number | null;
  ebit: number | null;
  finCharges: number | null;
  pbt: number | null;
  tax: number | null;
  netProfit: number | null;
  ebitda: number | null;
  ebitdaMarginPct: number | null;
}

export interface CashFlowRow {
  fiscal_year: number;
  ebitda: number | null;
  deltaInv: number | null;
  deltaRec: number | null;
  deltaPay: number | null;
  wcChange: number | null;
  cashFromOps: number | null;
  capex: number | null;
  cashFromInvesting: number | null;
  deltaLtDebt: number | null;
  deltaStDebt: number | null;
  deltaEquity: number | null;
  cashFromFinancing: number | null;
  netCashChange: number | null;
  cashStart: number | null;
  cashEnd: number | null;
}

export interface BalanceSheetRow {
  fiscal_year: number;
  fixedAssets: number | null;
  currentAssets: number | null;
  inventories: number | null;
  tradeReceivables: number | null;
  cash: number | null;
  currentInvestments: number | null;
  otherCurrentAssets: number | null;
  totalAssets: number | null;
  equity: number | null;
  ltDebt: number | null;
  ltFinDebt: number | null;
  tradePayables: number | null;
  stFinDebt: number | null;
  otherCurrentLiab: number | null;
  totalCurrentLiab: number | null;
  totalLE: number | null;
}

export interface CreditRow {
  fiscal_year: number;
  netDebtEbitda: number | null;
  debtEquity: number | null;
  equityRatio: number | null;
  interestCoverage: number | null;
  ebitdaMargin: number | null;
  roe: number | null;
}

export interface ExportData {
  detail: CompanyDetail;
  cbe: string;
  pnl: PnlRow[];
  cashFlow: CashFlowRow[];
  balanceSheet: BalanceSheetRow[];
  credit: CreditRow[];
  administrators: Administrator[];
  shareholders: Shareholder[];
  participatingInterests: ParticipatingInterest[];
  benchmark: SectorBenchmark | null;
}
