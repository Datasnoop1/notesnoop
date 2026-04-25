"use client";

import { useState, useCallback, useRef, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
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
import { searchPeople } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import { Search, Loader2, ChevronRight, User, UserSearch } from "lucide-react";
import { useTranslation } from "@/components/language-provider";

/* ---------- types ---------- */

interface PersonRow {
  name: string;
  company_count?: number;
  companies?: number;
  roles?: number;
  holdings?: number;
  top_companies?: (string | { name: string; cbe: string })[];
}

/* AdminRole / Holding / ConnectionData types were consumed by the
 * inline-expand UI; rows now navigate to the full profile page at
 * /people/[name] so those types live there instead. */

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
  const router = useRouter();
  const [results, setResults] = useState<PersonRow[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
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
    doSearch(value);
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
          <Badge variant="secondary" className="mb-3 text-[color:var(--brand-ink)] bg-brand-soft border-brand/30">
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
                  <TableRow
                    key={person.name}
                    className="cursor-pointer hover:bg-brand-soft/40"
                    onClick={() => router.push(`/people/${encodeURIComponent(person.name)}`)}
                  >
                    <TableCell className="w-8">
                      <ChevronRight className="h-4 w-4 text-slate-400" />
                    </TableCell>
                    <TableCell className="font-medium text-slate-900">
                      <div className="flex items-center gap-2">
                        <span className="text-brand">
                          {person.name}
                        </span>
                      </div>
                      {person.top_companies && person.top_companies.length > 0 && (
                        <div className="text-[11px] text-slate-400 mt-0.5 truncate max-w-[480px]">
                          {person.top_companies.slice(0, 3).map((c) => typeof c === "string" ? c : c.name).join(" \u00b7 ")}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {fmtNumber(person.company_count)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </div>
      )}
    </div>
  );
}
