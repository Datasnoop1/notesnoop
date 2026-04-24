"use client";

/**
 * Search page section components — V2.
 *
 * Four sections in fixed visual hierarchy:
 *   1. Commercial companies  (primary, largest grid)
 *   2. People                (equally prominent, side by side on lg+)
 *   3. Non-profits & public  (demoted, collapsed by default)
 *   4. Events                (smallest, at the bottom)
 *
 * All cards link to `/company/{cbe}` or `/people?q={name}` respectively.
 * Favourite toggles are wired by callbacks from the parent page so we
 * don't duplicate Supabase auth fetches.
 */

import Link from "next/link";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Building, Users, Star, Calendar, ChevronDown, ChevronRight, Landmark } from "lucide-react";
import { fmtEur, fmtCbe, fmtPct } from "@/lib/format";
import { useTranslation } from "@/components/language-provider";
import type {
  CompanySearchResultV2,
  PersonResult,
  StaatsbladEvent,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Shared card primitives
// ---------------------------------------------------------------------------

function CompanyCard({
  company,
  isFav,
  onToggleFav,
  tone,
}: {
  company: CompanySearchResultV2;
  isFav: boolean;
  onToggleFav: (cbe: string, e: React.MouseEvent) => void;
  tone: "primary" | "muted";
}) {
  // Primary tone = indigo, muted tone = slate (for nonprofit/public section).
  const iconBg =
    tone === "primary" ? "bg-indigo-50 text-indigo-500" : "bg-slate-100 text-slate-500";
  const hoverBorder =
    tone === "primary" ? "hover:border-indigo-200" : "hover:border-slate-300";
  const hoverText =
    tone === "primary" ? "group-hover:text-indigo-600" : "group-hover:text-slate-700";
  const Icon = tone === "primary" ? Building : Landmark;

  return (
    <Link
      href={`/company/${company.enterprise_number}`}
      className={`flex items-center gap-3 px-4 py-3 min-h-[44px] rounded-xl bg-white border border-slate-200 ${hoverBorder} hover:shadow-md transition-all group`}
    >
      <div className={`p-2 rounded-lg ${iconBg} shrink-0`}>
        <Icon className="w-4 h-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className={`text-sm font-semibold text-slate-800 ${hoverText} truncate`}>
          {company.name || fmtCbe(company.enterprise_number)}
        </div>
        <div className="text-[11px] text-slate-400 truncate">
          {fmtCbe(company.enterprise_number)}
          {company.city && <span> · {company.city}</span>}
          {company.sector && tone === "primary" && (
            <span className="hidden sm:inline"> · {company.sector}</span>
          )}
        </div>
      </div>
      {company.revenue != null && (
        <div className="text-right shrink-0 hidden sm:block">
          <div className="text-xs font-mono text-slate-600">{fmtEur(company.revenue)}</div>
          {company.ebitda_margin_pct != null && (
            <div
              className={`text-[11px] font-mono ${
                company.ebitda_margin_pct >= 15
                  ? "text-emerald-500"
                  : company.ebitda_margin_pct >= 5
                    ? "text-amber-500"
                    : "text-rose-400"
              }`}
            >
              {fmtPct(company.ebitda_margin_pct)}
            </div>
          )}
        </div>
      )}
      <button
        onClick={(e) => onToggleFav(company.enterprise_number, e)}
        aria-label={isFav ? "Remove favourite" : "Add favourite"}
        className="p-2.5 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-md hover:bg-slate-100 transition-colors shrink-0"
      >
        <Star
          className={`w-4 h-4 ${
            isFav ? "fill-amber-400 text-amber-400" : "text-slate-300 hover:text-slate-400"
          }`}
        />
      </button>
    </Link>
  );
}

function PersonCard({
  person,
  isFav,
  onToggleFav,
}: {
  person: PersonResult;
  isFav: boolean;
  onToggleFav: (name: string, e: React.MouseEvent) => void;
}) {
  const count =
    (person as PersonResult & { company_count?: number }).company_count ??
    (person as PersonResult & { companies?: number }).companies ??
    0;
  const tops = person.top_companies || [];
  return (
    <Link
      href={`/people?q=${encodeURIComponent(person.name)}`}
      className="flex items-center gap-3 px-4 py-3 min-h-[44px] rounded-xl bg-white border border-slate-200 hover:border-emerald-200 hover:shadow-md transition-all group"
    >
      <div className="p-2 rounded-lg bg-emerald-50 text-emerald-500 shrink-0">
        <Users className="w-4 h-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-slate-800 group-hover:text-emerald-600 truncate">
          {person.name}
        </div>
        <div className="text-[11px] text-slate-400 truncate">
          {tops.length > 0 ? (
            <>
              <span className="text-slate-500">{tops.slice(0, 2).join(" \u00b7 ")}</span>
              {count > tops.length && (
                <span className="text-slate-400"> +{count - tops.length} more</span>
              )}
            </>
          ) : (
            <span>
              {(person as PersonResult & { roles?: number }).roles
                ? `${(person as PersonResult & { roles?: number }).roles} roles`
                : ""}
            </span>
          )}
        </div>
      </div>
      <Badge variant="secondary" className="text-[10px] shrink-0">
        {count} {count === 1 ? "co." : "cos."}
      </Badge>
      <button
        onClick={(e) => onToggleFav(person.name, e)}
        aria-label={isFav ? "Remove favourite" : "Add favourite"}
        className="p-2.5 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-md hover:bg-slate-100 transition-colors shrink-0"
      >
        <Star
          className={`w-4 h-4 ${
            isFav ? "fill-amber-400 text-amber-400" : "text-slate-300 hover:text-slate-400"
          }`}
        />
      </button>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Section headers
// ---------------------------------------------------------------------------

function SectionHeader({
  icon: Icon,
  label,
  count,
  accent,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  count: number;
  accent: "indigo" | "emerald" | "slate";
}) {
  const border = {
    indigo: "border-indigo-500",
    emerald: "border-emerald-400",
    slate: "border-slate-300",
  }[accent];
  const iconTint = {
    indigo: "text-indigo-500",
    emerald: "text-emerald-500",
    slate: "text-slate-500",
  }[accent];
  return (
    <div className={`flex items-center gap-2 mb-3 border-l-[3px] ${border} pl-2`}>
      <Icon className={`w-4 h-4 ${iconTint}`} />
      <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">{label}</h2>
      <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
        {count}
      </Badge>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Commercial companies section
// ---------------------------------------------------------------------------

export function CommercialSection({
  companies,
  total,
  favCompanies,
  onToggleFav,
}: {
  companies: CompanySearchResultV2[];
  total: number;
  favCompanies: Set<string>;
  onToggleFav: (cbe: string, e: React.MouseEvent) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <SectionHeader icon={Building} label={t("search.sections.commercial")} count={total} accent="indigo" />
      {companies.length === 0 ? (
        <p className="text-[12px] text-slate-400 px-1">{t("search.noResultsBucket.commercial")}</p>
      ) : (
        <div className="space-y-2">
          {companies.map((c) => (
            <CompanyCard
              key={c.enterprise_number}
              company={c}
              isFav={favCompanies.has(c.enterprise_number)}
              onToggleFav={onToggleFav}
              tone="primary"
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// People section
// ---------------------------------------------------------------------------

export function PeopleSection({
  people,
  favPeople,
  onToggleFav,
}: {
  people: PersonResult[];
  favPeople: Set<string>;
  onToggleFav: (name: string, e: React.MouseEvent) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <SectionHeader icon={Users} label={t("search.sections.people")} count={people.length} accent="emerald" />
      {people.length === 0 ? (
        <p className="text-[12px] text-slate-400 px-1">{t("search.noResultsBucket.people")}</p>
      ) : (
        <div className="space-y-2">
          {people.slice(0, 20).map((p, i) => (
            <PersonCard
              key={`person-${i}-${p.name}`}
              person={p}
              isFav={favPeople.has(p.name)}
              onToggleFav={onToggleFav}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Non-profits & public — collapsed by default, demoted visual weight
// ---------------------------------------------------------------------------

export function NonprofitSection({
  companies,
  total,
  favCompanies,
  onToggleFav,
}: {
  companies: CompanySearchResultV2[];
  total: number;
  favCompanies: Set<string>;
  onToggleFav: (cbe: string, e: React.MouseEvent) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  if (companies.length === 0) {
    // Still render an explicit empty marker so users know we did look
    // — matches the commercial section's empty-state UX.
    return (
      <div className="rounded-lg border border-dashed border-slate-200 p-3">
        <SectionHeader
          icon={Landmark}
          label={t("search.sections.nonprofitPublic")}
          count={0}
          accent="slate"
        />
        <p className="text-[12px] text-slate-400 pl-1">{t("search.noResultsBucket.nonprofit")}</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/40 p-3">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 text-left"
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-slate-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-400" />
        )}
        <Landmark className="w-4 h-4 text-slate-500" />
        <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
          {t("search.sections.nonprofitPublic")}
        </h2>
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
          {total}
        </Badge>
        {!expanded && (
          <span className="text-[11px] text-slate-400 ml-auto">
            {t("search.showHidden", { n: total })}
          </span>
        )}
      </button>
      {expanded && (
        <div className="space-y-2 mt-3">
          {companies.map((c) => (
            <CompanyCard
              key={c.enterprise_number}
              company={c}
              isFav={favCompanies.has(c.enterprise_number)}
              onToggleFav={onToggleFav}
              tone="muted"
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Events (Staatsblad) — stays as-is from V1, smaller section at the bottom
// ---------------------------------------------------------------------------

export function EventsSection({ events }: { events: StaatsbladEvent[] }) {
  if (events.length === 0) return null;
  return (
    <div>
      <h2 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-emerald-400 pl-2">
        <Calendar className="w-3.5 h-3.5" />
        Events ({events.length})
      </h2>
      <div className="space-y-1">
        {events.map((ev) => {
          const who = ev.person_name || ev.entity_name || "";
          const tLabel = (ev.event_type || "").replace(/_/g, " ");
          return (
            <Link
              key={ev.id}
              href={`/company/${ev.enterprise_number}`}
              className="flex items-center gap-3 px-3 py-2 min-h-[44px] rounded-lg bg-white border border-slate-200 hover:border-emerald-300 hover:shadow-sm transition-all"
            >
              <span className="font-mono text-[11px] text-slate-500 w-24 shrink-0">
                {ev.event_date || ev.pub_date}
              </span>
              <Badge
                variant="secondary"
                className="text-[10px] capitalize bg-emerald-50 text-emerald-700 border-emerald-200 shrink-0"
              >
                {tLabel}
              </Badge>
              <span className="text-sm font-medium text-slate-700 truncate">
                {ev.company_name || fmtCbe(ev.enterprise_number)}
              </span>
              {who && (
                <span className="text-xs text-slate-500 truncate hidden md:inline">— {who}</span>
              )}
              <span
                className="ml-auto text-xs text-slate-400 truncate hidden md:inline max-w-[40%]"
                title={ev.summary || undefined}
              >
                {ev.summary}
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section skeleton (loading state) — matches card geometry so no layout shift
// ---------------------------------------------------------------------------

export function SectionSkeleton({
  icon: Icon,
  label,
  accent,
  rows = 4,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  accent: "indigo" | "emerald" | "slate";
  rows?: number;
}) {
  return (
    <div>
      <SectionHeader icon={Icon} label={label} count={0} accent={accent} />
      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-[56px] rounded-xl bg-slate-100 animate-pulse"
            aria-hidden
          />
        ))}
      </div>
    </div>
  );
}
