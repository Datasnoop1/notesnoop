"use client";

import Link from "next/link";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { useLimit } from "@/components/limit-provider";
import { ShieldAlert, UserPlus, Sparkles } from "lucide-react";

/** Human-readable labels for limit types */
const LIMIT_LABELS: Record<string, string> = {
  searches_per_day: "searches per day",
  company_views_per_day: "company views per day",
  ai_enrichments_per_day: "AI enrichments per day",
  export_per_day: "exports per day",
  page_views_per_day: "page views per day",
};

export default function LimitPopup() {
  const { limitInfo, clearLimit } = useLimit();

  if (!limitInfo) return null;

  const isGuest = limitInfo.tier === "guest";
  const limitLabel = LIMIT_LABELS[limitInfo.limitType] || limitInfo.limitType.replace(/_/g, " ");

  return (
    <Dialog open={!!limitInfo} onOpenChange={(open) => { if (!open) clearLimit(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2 mb-1">
            <div className="flex items-center justify-center w-10 h-10 rounded-full bg-indigo-50">
              <ShieldAlert className="h-5 w-5 text-indigo-600" />
            </div>
            <DialogTitle className="text-lg">
              {isGuest ? "Daily limit reached" : "Daily limit reached"}
            </DialogTitle>
          </div>
          <DialogDescription>
            {isGuest ? (
              <>
                You&apos;ve used all <strong className="text-slate-700">{limitInfo.limit} {limitLabel}</strong> available
                to guests. Create a free account to unlock higher limits.
              </>
            ) : (
              <>
                You&apos;ve used all <strong className="text-slate-700">{limitInfo.limit} {limitLabel}</strong> included
                in your plan today. Upgrade to Pro for unlimited access.
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <div className="flex items-center justify-between">
            <span>Today&apos;s usage</span>
            <span className="font-medium text-slate-900">
              {limitInfo.used} / {limitInfo.limit}
            </span>
          </div>
          <div className="mt-2 h-2 rounded-full bg-slate-200 overflow-hidden">
            <div
              className="h-full rounded-full bg-indigo-500"
              style={{ width: "100%" }}
            />
          </div>
          <p className="mt-1.5 text-xs text-slate-500">
            Limits reset daily at midnight.
          </p>
        </div>

        <DialogFooter>
          {isGuest ? (
            <Link
              href="/login"
              onClick={clearLimit}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
            >
              <UserPlus className="h-4 w-4" />
              Sign up free
            </Link>
          ) : (
            <Link
              href="/account"
              onClick={clearLimit}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
            >
              <Sparkles className="h-4 w-4" />
              Upgrade to Pro
            </Link>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
