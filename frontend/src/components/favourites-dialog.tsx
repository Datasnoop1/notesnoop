"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { getFavourites, type FavouriteItem } from "@/lib/api";
import { fmtCbe, fmtEur } from "@/lib/format";
import { Star, Plus, Loader2 } from "lucide-react";

interface FavouritesDialogProps {
  /** CBEs already selected (will be greyed out) */
  existingCbes: Set<string>;
  /** Called when user clicks a favourite to add it */
  onAdd: (cbe: string, name: string) => void;
  /** Max companies allowed */
  max?: number;
}

export default function FavouritesDialog({
  existingCbes,
  onAdd,
  max,
}: FavouritesDialogProps) {
  const [open, setOpen] = useState(false);
  const [favourites, setFavourites] = useState<FavouriteItem[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getFavourites();
      setFavourites(data);
    } catch {
      setFavourites([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const atMax = max != null && existingCbes.size >= max;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant="outline" size="sm">
            <Star className="h-4 w-4 mr-1.5 text-amber-500" />
            Load from Favourites
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add from Favourites</DialogTitle>
        </DialogHeader>

        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        )}

        {!loading && favourites.length === 0 && (
          <p className="text-sm text-slate-400 text-center py-6">
            No favourites yet. Star companies to see them here.
          </p>
        )}

        {!loading && favourites.length > 0 && (
          <div className="max-h-72 overflow-y-auto -mx-1 px-1 space-y-0.5">
            {favourites.map((fav) => {
              const already = existingCbes.has(fav.enterprise_number);
              return (
                <button
                  key={fav.enterprise_number}
                  disabled={already || atMax}
                  onClick={() => {
                    onAdd(
                      fav.enterprise_number,
                      fav.name || fav.enterprise_number
                    );
                  }}
                  className="w-full text-left px-3 py-2 rounded-md hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-between gap-2"
                >
                  <div className="min-w-0">
                    <span className="text-sm font-medium text-slate-900 truncate block">
                      {fav.name || fav.enterprise_number}
                    </span>
                    <span className="text-xs text-slate-400">
                      {fmtCbe(fav.enterprise_number)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {fav.revenue != null && (
                      <Badge variant="secondary" className="text-[10px]">
                        {fmtEur(fav.revenue)}
                      </Badge>
                    )}
                    {already ? (
                      <span className="text-[10px] text-slate-400">Added</span>
                    ) : (
                      <Plus className="h-3.5 w-3.5 text-indigo-500" />
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
