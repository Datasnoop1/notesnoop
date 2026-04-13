"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
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
  getFavourites,
  removeFavourite,
  type FavouriteItem,
} from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import { Star, Trash2, Loader2 } from "lucide-react";

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

export default function FavouritesPage() {
  const [favourites, setFavourites] = useState<FavouriteItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [removing, setRemoving] = useState<string | null>(null);

  const loadFavourites = useCallback(async () => {
    try {
      const data = await getFavourites();
      setFavourites(data);
    } catch (err) {
      console.error("Failed to load favourites:", err);
      setFavourites([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFavourites();
  }, [loadFavourites]);

  async function handleRemove(cbe: string) {
    setRemoving(cbe);
    try {
      await removeFavourite(cbe);
      setFavourites((prev) => prev.filter((f) => f.enterprise_number !== cbe));
    } catch (err) {
      console.error("Failed to remove favourite:", err);
    } finally {
      setRemoving(null);
    }
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return "\u2014";
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            <Star className="w-4 h-4 inline mr-1.5" />
            Favourites
          </h1>
          <p className="mt-0.5 text-xs text-slate-500">
            Companies you are tracking for deal sourcing
          </p>
        </div>
        {!loading && favourites.length > 0 && (
          <Badge variant="secondary" className="text-indigo-700 bg-indigo-50 border-indigo-200">
            {favourites.length} {favourites.length === 1 ? "company" : "companies"}
          </Badge>
        )}
      </div>

      {/* Loading state */}
      {loading && (
        <Card className="bg-white overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead>Company</TableHead>
                <TableHead>NACE</TableHead>
                <TableHead className="text-right">Revenue</TableHead>
                <TableHead className="text-right">EBITDA</TableHead>
                <TableHead className="text-right">Margin</TableHead>
                <TableHead className="text-right">FTE</TableHead>
                <TableHead>Added</TableHead>
                <TableHead>Notes</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              <SkeletonRows cols={9} count={5} />
            </TableBody>
          </Table>
        </Card>
      )}

      {/* Empty state */}
      {!loading && favourites.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-10">
          <Star className="h-6 w-6 text-slate-300 mb-2" />
          <p className="text-sm font-medium text-slate-500">
            No favourites yet. Star companies to track them here.
          </p>
          <p className="mt-2 text-xs text-slate-400">
            Use the company page or screener to add companies to your favourites list.
          </p>
        </div>
      )}

      {/* Favourites table */}
      {!loading && favourites.length > 0 && (
        <Card className="bg-white overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="min-w-[200px]">Company</TableHead>
                <TableHead>NACE</TableHead>
                <TableHead className="text-right">Revenue</TableHead>
                <TableHead className="text-right">EBITDA</TableHead>
                <TableHead className="text-right">Margin</TableHead>
                <TableHead className="text-right">FTE</TableHead>
                <TableHead>Added</TableHead>
                <TableHead className="max-w-[200px]">Notes</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {favourites.map((fav) => (
                <TableRow key={fav.enterprise_number} className="hover:bg-indigo-50/40">
                  <TableCell className="font-medium py-1.5 text-sm">
                    <Link
                      href={`/company/${fav.enterprise_number}`}
                      className="text-indigo-600 hover:text-indigo-800 hover:underline"
                    >
                      {fav.name || fmtCbe(fav.enterprise_number)}
                    </Link>
                  </TableCell>
                  <TableCell className="text-slate-600 text-xs py-1.5">
                    {fav.nace_code ?? "\u2014"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs py-1.5">
                    {fmtEur(fav.revenue)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs py-1.5">
                    {fmtEur(fav.ebitda)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs py-1.5">
                    {fmtPct(fav.margin_pct)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs py-1.5">
                    {fmtNumber(fav.fte_total)}
                  </TableCell>
                  <TableCell className="text-xs text-slate-500 whitespace-nowrap py-1.5">
                    {formatDate(fav.added_at)}
                  </TableCell>
                  <TableCell className="max-w-[200px] truncate text-xs text-slate-500 py-1.5" title={fav.notes ?? ""}>
                    {fav.notes ?? "\u2014"}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 text-slate-400 hover:text-red-600 hover:bg-red-50"
                      onClick={() => handleRemove(fav.enterprise_number)}
                      disabled={removing === fav.enterprise_number}
                    >
                      {removing === fav.enterprise_number ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
