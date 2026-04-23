"use client";

import type { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  accentClass,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: LucideIcon;
  accentClass?: string;
}) {
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              {label}
            </div>
            <div
              className={cn(
                "text-3xl font-semibold tracking-tight text-slate-900",
                accentClass,
              )}
            >
              {value}
            </div>
            {hint ? <div className="body-sm text-slate-500">{hint}</div> : null}
          </div>
          {Icon ? (
            <div className="rounded-2xl bg-slate-100 p-3 text-slate-700">
              <Icon className="size-5" />
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
