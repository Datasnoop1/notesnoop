"use client";

import { useState, useCallback, useEffect } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { getScreener } from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import {
  Download,
  Search,
  RotateCcw,
  Loader2,
  Filter,
  Tag,
  MapPin,
  CircleDollarSign,
  TrendingUp,
  Users,
  Percent,
  ArrowUpDown,
  List,
} from "lucide-react";

/* ---------- types ---------- */

interface ScreenerRow {
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

interface Filters {
  nace: string;
  zipcode: string;
  rev_min: string;
  rev_max: string;
  ebit_min: string;
  ebit_max: string;
  fte_min: string;
  fte_max: string;
  margin_min: string;
  sort: string;
  limit: string;
}

const DEFAULT_FILTERS: Filters = {
  nace: "",
  zipcode: "",
  rev_min: "",
  rev_max: "",
  ebit_min: "",
  ebit_max: "",
  fte_min: "",
  fte_max: "",
  margin_min: "",
  sort: "ebit_desc",
  limit: "100",
};

const SORT_OPTIONS = [
  { value: "revenue_desc", label: "Revenue high-low" },
  { value: "ebit_desc", label: "EBIT high-low" },
  { value: "ebitda_desc", label: "EBITDA high-low" },
  { value: "fte_desc", label: "FTE high-low" },
  { value: "name_asc", label: "Name A-Z" },
];

const LIMIT_OPTIONS = ["50", "100", "250", "500"];

/* ---------- CSV helper ---------- */

function exportCsv(rows: ScreenerRow[]) {
  const headers = [
    "CBE",
    "Name",
    "NACE",
    "City",
    "FY",
    "Revenue",
    "EBIT",
    "EBITDA",
    "Margin %",
    "Net Profit",
    "FTE",
  ];
  const csvRows = rows.map((r) =>
    [
      fmtCbe(r.cbe),
      `"${(r.name ?? "").replace(/"/g, '""')}"`,
      `"${(r.nace ?? "").replace(/"/g, '""')}"`,
      r.city ?? "",
      r.fiscal_year ?? "",
      r.revenue ?? "",
      r.ebit ?? "",
      r.ebitda ?? "",
      r.margin_pct ?? "",
      r.net_profit ?? "",
      r.fte ?? "",
    ].join(",")
  );
  const blob = new Blob(
    [headers.join(",") + "\n" + csvRows.join("\n")],
    { type: "text/csv" }
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "screener_export.csv";
  a.click();
  URL.revokeObjectURL(url);
}

/* ---------- skeleton rows ---------- */

function SkeletonRows({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 11 }).map((_, j) => (
            <TableCell key={j}>
              <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/* ---------- main component ---------- */

export default function ScreenerPage() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [results, setResults] = useState<ScreenerRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const updateFilter = useCallback(
    (key: keyof Filters, value: string) => {
      setFilters((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
    setResults([]);
    setHasSearched(false);
  }, []);

  const applyFilters = useCallback(async () => {
    setLoading(true);
    setHasSearched(true);
    try {
      const params: Record<string, string> = {};
      if (filters.nace) params.nace = filters.nace;
      if (filters.zipcode) params.zipcode = filters.zipcode;
      if (filters.rev_min) params.rev_min = filters.rev_min;
      if (filters.rev_max) params.rev_max = filters.rev_max;
      if (filters.ebit_min) params.ebit_min = filters.ebit_min;
      if (filters.ebit_max) params.ebit_max = filters.ebit_max;
      if (filters.fte_min) params.fte_min = filters.fte_min;
      if (filters.fte_max) params.fte_max = filters.fte_max;
      if (filters.margin_min) params.margin_min = filters.margin_min;
      params.sort = filters.sort;
      params.limit = filters.limit;

      const data = await getScreener(params);
      setResults(data);
    } catch (err) {
      console.error("Screener fetch failed:", err);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") applyFilters();
    },
    [applyFilters]
  );

  // Auto-load on mount
  useEffect(() => {
    applyFilters();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-6">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">
          <Search className="w-5 h-5 inline mr-2" />
          Company Screener
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Filter and browse Belgian companies by financial metrics
        </p>
      </div>

      <div className="flex gap-6">
        {/* Left sidebar — filters */}
        <div className="w-80 shrink-0" onKeyDown={handleKeyDown}>
          <div className="space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
              <Filter className="w-3.5 h-3.5 inline mr-1.5" />
              Filters
            </h2>

            {/* Action buttons — top */}
            <div className="flex gap-2">
              <Button
                onClick={applyFilters}
                disabled={loading}
                className="flex-1 bg-indigo-600 text-white hover:bg-indigo-700"
              >
                {loading ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <Search className="mr-1.5 h-4 w-4" />
                )}
                Apply Filters
              </Button>
              <Button variant="outline" onClick={resetFilters}>
                <RotateCcw className="mr-1.5 h-4 w-4" />
                Reset
              </Button>
            </div>

            {/* --- Identification --- */}
            <div className="border-t border-slate-200 pt-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="nace" className="text-xs text-slate-500">
                    <Tag className="w-3.5 h-3.5 inline mr-1" />
                    NACE sector
                  </Label>
                  <Input
                    id="nace"
                    placeholder="e.g. 45"
                    value={filters.nace}
                    onChange={(e) => updateFilter("nace", e.target.value)}
                  />
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="zipcode" className="text-xs text-slate-500">
                    <MapPin className="w-3.5 h-3.5 inline mr-1" />
                    Zipcode
                  </Label>
                  <Input
                    id="zipcode"
                    placeholder="2000, 9..."
                    value={filters.zipcode}
                    onChange={(e) => updateFilter("zipcode", e.target.value)}
                  />
                </div>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                NACE code or prefix (e.g. 28, 461, 6920)
              </p>
            </div>

            {/* --- Revenue --- */}
            <div className="border-t border-slate-200 pt-3">
              <Label className="text-xs text-slate-500">
                <CircleDollarSign className="w-3.5 h-3.5 inline mr-1" />
                Revenue
              </Label>
              <div className="mt-1.5 grid grid-cols-2 gap-3">
                <Input
                  type="number"
                  placeholder="Min"
                  value={filters.rev_min}
                  onChange={(e) => updateFilter("rev_min", e.target.value)}
                />
                <Input
                  type="number"
                  placeholder="Max"
                  value={filters.rev_max}
                  onChange={(e) => updateFilter("rev_max", e.target.value)}
                />
              </div>
            </div>

            {/* --- EBIT --- */}
            <div className="border-t border-slate-200 pt-3">
              <Label className="text-xs text-slate-500">
                <TrendingUp className="w-3.5 h-3.5 inline mr-1" />
                EBIT
              </Label>
              <div className="mt-1.5 grid grid-cols-2 gap-3">
                <Input
                  type="number"
                  placeholder="Min"
                  value={filters.ebit_min}
                  onChange={(e) => updateFilter("ebit_min", e.target.value)}
                />
                <Input
                  type="number"
                  placeholder="Max"
                  value={filters.ebit_max}
                  onChange={(e) => updateFilter("ebit_max", e.target.value)}
                />
              </div>
            </div>

            {/* --- FTE --- */}
            <div className="border-t border-slate-200 pt-3">
              <Label className="text-xs text-slate-500">
                <Users className="w-3.5 h-3.5 inline mr-1" />
                FTE
              </Label>
              <div className="mt-1.5 grid grid-cols-2 gap-3">
                <Input
                  type="number"
                  placeholder="Min"
                  value={filters.fte_min}
                  onChange={(e) => updateFilter("fte_min", e.target.value)}
                />
                <Input
                  type="number"
                  placeholder="Max"
                  value={filters.fte_max}
                  onChange={(e) => updateFilter("fte_max", e.target.value)}
                />
              </div>
            </div>

            {/* --- Margin --- */}
            <div className="border-t border-slate-200 pt-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-slate-500">
                  <Percent className="w-3.5 h-3.5 inline mr-1" />
                  EBITDA margin min %
                </Label>
                <Input
                  type="number"
                  placeholder="0"
                  value={filters.margin_min}
                  onChange={(e) => updateFilter("margin_min", e.target.value)}
                />
              </div>
            </div>

            {/* --- Sort & Limit --- */}
            <div className="border-t border-slate-200 pt-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-xs text-slate-500">
                    <ArrowUpDown className="w-3.5 h-3.5 inline mr-1" />
                    Sort by
                  </Label>
                  <Select
                    value={filters.sort}
                    onValueChange={(v) => updateFilter("sort", v ?? "")}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SORT_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs text-slate-500">
                    <List className="w-3.5 h-3.5 inline mr-1" />
                    Limit
                  </Label>
                  <Select
                    value={filters.limit}
                    onValueChange={(v) => updateFilter("limit", v ?? "")}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LIMIT_OPTIONS.map((opt) => (
                        <SelectItem key={opt} value={opt}>
                          {opt}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right area — results */}
        <div className="flex-1 min-w-0">
          {loading && (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Company</TableHead>
                    <TableHead>NACE</TableHead>
                    <TableHead>City</TableHead>
                    <TableHead className="text-right">Revenue</TableHead>
                    <TableHead className="text-right">EBIT</TableHead>
                    <TableHead className="text-right">EBITDA</TableHead>
                    <TableHead className="text-right">Margin %</TableHead>
                    <TableHead className="text-right">Net Profit</TableHead>
                    <TableHead className="text-right">FTE</TableHead>
                    <TableHead className="text-right">FY</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <SkeletonRows count={10} />
                </TableBody>
              </Table>
            </div>
          )}

          {!loading && hasSearched && results.length === 0 && (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16">
              <p className="text-sm font-medium text-slate-500">
                No companies match your filters
              </p>
              <p className="mt-1 text-xs text-slate-400">
                Try broadening your search criteria
              </p>
            </div>
          )}

          {!loading && results.length > 0 && (
            <>
              {/* Summary bar */}
              <div className="mb-4 flex items-center justify-between">
                <Badge variant="secondary" className="text-indigo-700 bg-indigo-50 border-indigo-200">
                  {results.length.toLocaleString()} companies found
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => exportCsv(results)}
                >
                  <Download className="mr-1.5 h-3.5 w-3.5" />
                  Export CSV
                </Button>
              </div>

              {/* Results table */}
              <div className="rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-slate-50">
                      <TableHead className="min-w-[200px]">Company</TableHead>
                      <TableHead className="min-w-[180px]">NACE</TableHead>
                      <TableHead>City</TableHead>
                      <TableHead className="text-right">Revenue</TableHead>
                      <TableHead className="text-right">EBIT</TableHead>
                      <TableHead className="text-right">EBITDA</TableHead>
                      <TableHead className="text-right">Margin %</TableHead>
                      <TableHead className="text-right">Net Profit</TableHead>
                      <TableHead className="text-right">FTE</TableHead>
                      <TableHead className="text-right">FY</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {results.map((row) => (
                      <TableRow key={row.cbe} className="hover:bg-indigo-50/40">
                        <TableCell className="font-medium">
                          <Link
                            href={`/company/${row.cbe}`}
                            className="text-indigo-600 hover:text-indigo-800 hover:underline"
                          >
                            {row.name || fmtCbe(row.cbe)}
                          </Link>
                        </TableCell>
                        <TableCell
                          className="max-w-[220px] truncate text-xs text-slate-600"
                          title={row.nace}
                        >
                          {row.nace}
                        </TableCell>
                        <TableCell className="text-slate-600">
                          {row.city ?? "\u2014"}
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmtEur(row.revenue)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmtEur(row.ebit)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmtEur(row.ebitda)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmtPct(row.margin_pct)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmtEur(row.net_profit)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm">
                          {fmtNumber(row.fte)}
                        </TableCell>
                        <TableCell className="text-right text-xs text-slate-500">
                          {row.fiscal_year ?? "\u2014"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
