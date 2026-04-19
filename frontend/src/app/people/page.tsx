"use client";

import { useState, useCallback, useRef, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { searchPeople, getPersonConnections } from "@/lib/api";
import { fmtEur, fmtPct, fmtNumber } from "@/lib/format";
import { Search, Loader2, ChevronDown, ChevronRight, User, UserSearch } from "lucide-react";
import { useTranslation } from "@/components/language-provider";

/* ---------- types ---------- */

interface PersonRow {
  name: string;
  company_count?: number;
  companies?: number;
  roles?: number;
  holdings?: number;
  top_companies?: string[];
}

interface AdminRole {
  enterprise_number: string;
  company_name: string;
  role: string | null;
  role_label: string | null;
  mandate_start: string | null;
  mandate_end: string | null;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
  // Stage 3c: provenance/freshness
  source?: "nbb" | "staatsblad" | "merged" | null;
  as_of?: string | null;
}

interface Holding {
  enterprise_number: string;
  company_name: string;
  ownership_pct: number | null;
  revenue: number | null;
  ebitda: number | null;
  fte_total: number | null;
}

interface ConnectionData {
  name: string;
  total_companies: number;
  admin_count: number;
  holding_count: number;
  administrator_roles: AdminRole[];
  shareholdings: Holding[];
}

/* ---------- skeleton ---------- */

function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-slate-200 ${className}`} />;
}

function SkeletonRows({ cols, count }: { cols: number; count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: cols }).map((_, j) => (
            <TableCell key={j}>
              <SkeletonBlock className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/* ---------- main component ---------- */

export default function PeoplePage() {
  return (
    <Suspense fallback={<div className="py-8 text-center text-sm text-slate-400">Loading...</div>}>
      <PeoplePageInner />
    </Suspense>
  );
}

function PeoplePageInner() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PersonRow[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [expandedName, setExpandedName] = useState<string | null>(null);
  const [connections, setConnections] = useState<ConnectionData | null>(null);
  const [loadingConnections, setLoadingConnections] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialLoadRef = useRef(false);

  /* debounced search */
  const doSearch = useCallback((q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (q.trim().length < 2) {
      setResults([]);
      setHasSearched(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      setHasSearched(true);
      try {
        const data = await searchPeople(q.trim());
        setResults(data as PersonRow[]);
      } catch (err) {
        console.error("People search failed:", err);
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  }, []);

  /* Pre-fill from URL ?q= parameter */
  useEffect(() => {
    if (initialLoadRef.current) return;
    const qParam = searchParams.get("q");
    if (qParam && qParam.trim().length >= 2) {
      initialLoadRef.current = true;
      setQuery(qParam);
      doSearch(qParam);
    }
  }, [searchParams, doSearch]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  function handleQueryChange(value: string) {
    setQuery(value);
    setExpandedName(null);
    setConnections(null);
    doSearch(value);
  }

  /* expand a person row */
  async function toggleExpand(name: string) {
    if (expandedName === name) {
      setExpandedName(null);
      setConnections(null);
      return;
    }
    setExpandedName(name);
    setConnections(null);
    setLoadingConnections(true);
    try {
      const data = await getPersonConnections(name);
      setConnections(data as unknown as ConnectionData);
    } catch (err) {
      console.error("Failed loading connections:", err);
      setConnections(null);
    } finally {
      setLoadingConnections(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[1200px] space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-slate-900">
          <UserSearch className="w-4 h-4 inline mr-1.5" />
          {t("people.title")}
        </h1>
        <p className="mt-0.5 text-xs text-slate-500">
          Find administrators and shareholders by name
        </p>
      </div>

      {/* Search */}
      <Card className="bg-white">
        <CardContent className="pt-3 pb-3">
          <div className="relative max-w-xl">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              placeholder={t("people.searchPlaceholder")}
              className="pl-10"
              value={query}
              onChange={(e) => handleQueryChange(e.target.value)}
            />
            {searching && (
              <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-slate-400" />
            )}
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {searching && !hasSearched && (
        <Card className="bg-white overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead />
                <TableHead>{t("people.name")}</TableHead>
                <TableHead className="text-right">{t("people.companies")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <SkeletonRows cols={3} count={6} />
            </TableBody>
          </Table>
        </Card>
      )}

      {!searching && hasSearched && results.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-10">
          <User className="h-6 w-6 text-slate-300 mb-2" />
          <p className="text-sm font-medium text-slate-500">{t("people.noResults")}</p>
          <p className="mt-1 text-xs text-slate-400">
            Try a different name or spelling
          </p>
        </div>
      )}

      {results.length > 0 && (
        <div>
          <Badge variant="secondary" className="mb-3 text-indigo-700 bg-indigo-50 border-indigo-200">
            {results.length} {results.length === 1 ? "result" : "results"}
          </Badge>

          <Card className="bg-white overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead className="w-8" />
                  <TableHead>{t("people.name")}</TableHead>
                  <TableHead className="text-right">{t("people.companies")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((person) => (
                  <>
                    <TableRow
                      key={person.name}
                      className="cursor-pointer hover:bg-indigo-50/40"
                      onClick={() => toggleExpand(person.name)}
                    >
                      <TableCell className="w-8">
                        {expandedName === person.name ? (
                          <ChevronDown className="h-4 w-4 text-indigo-600" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-slate-400" />
                        )}
                      </TableCell>
                      <TableCell className="font-medium text-slate-900">
                        <div>{person.name}</div>
                        {person.top_companies && person.top_companies.length > 0 && (
                          <div className="text-[11px] text-slate-400 mt-0.5 truncate max-w-[480px]">
                            {person.top_companies.slice(0, 3).join(" \u00b7 ")}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {fmtNumber(person.company_count)}
                      </TableCell>
                    </TableRow>

                    {/* Expanded connections */}
                    {expandedName === person.name && (
                      <TableRow key={`${person.name}-detail`}>
                        <TableCell colSpan={3} className="bg-slate-50/80 p-0">
                          <div className="px-4 py-3 space-y-3">
                            {loadingConnections && (
                              <div className="flex items-center gap-2 text-sm text-slate-500">
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Loading connections...
                              </div>
                            )}

                            {!loadingConnections && connections && (
                              <>
                                {/* Summary badges */}
                                <div className="flex flex-wrap gap-2">
                                  <Badge variant="secondary" className="bg-indigo-50 text-indigo-700 border-indigo-200">
                                    {connections.admin_count} admin {connections.admin_count === 1 ? "role" : "roles"}
                                  </Badge>
                                  <Badge variant="secondary" className="bg-indigo-50 text-indigo-700 border-indigo-200">
                                    {connections.holding_count} {connections.holding_count === 1 ? "holding" : "holdings"}
                                  </Badge>
                                  <Badge variant="secondary" className="bg-slate-100 text-slate-600">
                                    {connections.total_companies} unique {connections.total_companies === 1 ? "company" : "companies"}
                                  </Badge>
                                </div>

                                {/* Admin roles */}
                                {connections.administrator_roles.length > 0 && (
                                  <div>
                                    <h4 className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-2">
                                      Administrator Roles
                                    </h4>
                                    <div className="rounded-lg border bg-white overflow-x-auto">
                                      <Table className="md:min-w-[640px]">
                                        <TableHeader>
                                          <TableRow>
                                            <TableHead>Company</TableHead>
                                            <TableHead>Role</TableHead>
                                            <TableHead className="hidden md:table-cell text-right">Revenue</TableHead>
                                            <TableHead className="hidden md:table-cell text-right">EBITDA</TableHead>
                                            <TableHead className="hidden md:table-cell text-right">FTE</TableHead>
                                          </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                          {connections.administrator_roles.map((role, idx) => {
                                            const src = role.source ?? "nbb";
                                            const srcLabel =
                                              src === "staatsblad" ? "Staatsblad" :
                                              src === "merged" ? "Updated" : null;
                                            const srcCls =
                                              src === "staatsblad"
                                                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                                : src === "merged"
                                                ? "bg-amber-50 text-amber-700 border-amber-200"
                                                : "";
                                            return (
                                              <TableRow key={`${role.enterprise_number}-${idx}`}>
                                                <TableCell>
                                                  <Link
                                                    href={`/company/${role.enterprise_number}`}
                                                    className="text-indigo-600 hover:text-indigo-800 hover:underline font-medium"
                                                  >
                                                    {role.company_name}
                                                  </Link>
                                                  {role.as_of && (
                                                    <span className="ml-2 text-[10px] text-slate-400">
                                                      as of {role.as_of}
                                                    </span>
                                                  )}
                                                </TableCell>
                                                <TableCell className="text-slate-600 text-sm">
                                                  <div className="flex items-center gap-2">
                                                    <span>{role.role_label || role.role || "\u2014"}</span>
                                                    {srcLabel && (
                                                      <Badge
                                                        variant="secondary"
                                                        className={`text-[10px] ${srcCls}`}
                                                      >
                                                        {srcLabel}
                                                      </Badge>
                                                    )}
                                                  </div>
                                                </TableCell>
                                                <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                                  {fmtEur(role.revenue)}
                                                </TableCell>
                                                <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                                  {fmtEur(role.ebitda)}
                                                </TableCell>
                                                <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                                  {fmtNumber(role.fte_total)}
                                                </TableCell>
                                              </TableRow>
                                            );
                                          })}
                                        </TableBody>
                                      </Table>
                                    </div>
                                  </div>
                                )}

                                {/* Holdings */}
                                {connections.shareholdings.length > 0 && (
                                  <div>
                                    <h4 className="text-xs font-bold uppercase tracking-wide text-slate-500 mb-2">
                                      Holdings
                                    </h4>
                                    <div className="rounded-lg border bg-white overflow-x-auto">
                                      <Table className="md:min-w-[640px]">
                                        <TableHeader>
                                          <TableRow>
                                            <TableHead>Company</TableHead>
                                            <TableHead className="text-right">Ownership %</TableHead>
                                            <TableHead className="hidden md:table-cell text-right">Revenue</TableHead>
                                            <TableHead className="hidden md:table-cell text-right">EBITDA</TableHead>
                                            <TableHead className="hidden md:table-cell text-right">FTE</TableHead>
                                          </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                          {connections.shareholdings.map((h, idx) => (
                                            <TableRow key={`${h.enterprise_number}-${idx}`}>
                                              <TableCell>
                                                <Link
                                                  href={`/company/${h.enterprise_number}`}
                                                  className="text-indigo-600 hover:text-indigo-800 hover:underline font-medium"
                                                >
                                                  {h.company_name}
                                                </Link>
                                              </TableCell>
                                              <TableCell className="text-right font-mono text-sm">
                                                {fmtPct(h.ownership_pct)}
                                              </TableCell>
                                              <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                                {fmtEur(h.revenue)}
                                              </TableCell>
                                              <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                                {fmtEur(h.ebitda)}
                                              </TableCell>
                                              <TableCell className="hidden md:table-cell text-right font-mono text-sm">
                                                {fmtNumber(h.fte_total)}
                                              </TableCell>
                                            </TableRow>
                                          ))}
                                        </TableBody>
                                      </Table>
                                    </div>
                                  </div>
                                )}

                                {connections.administrator_roles.length === 0 &&
                                  connections.shareholdings.length === 0 && (
                                    <p className="text-sm text-slate-400">
                                      No connections found for this person
                                    </p>
                                  )}
                              </>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                ))}
              </TableBody>
            </Table>
          </Card>
        </div>
      )}
    </div>
  );
}
