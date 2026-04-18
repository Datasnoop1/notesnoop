import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/40 px-4 py-10 md:py-12 text-center",
        className
      )}
    >
      {Icon && <Icon className="mb-3 h-7 w-7 text-slate-300" aria-hidden />}
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-xs text-slate-400">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
