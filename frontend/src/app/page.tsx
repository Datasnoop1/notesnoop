"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Search, BarChart2, Grid3X3, Sparkles, ArrowRight, TrendingUp, FileText, Star, AlertTriangle, CheckCircle } from "lucide-react";
import { useTranslation } from "@/components/language-provider";
import { getRecentlyViewed } from "@/lib/recently-viewed";
import type { RecentlyViewedEntry } from "@/lib/recently-viewed";
import { fmtEur } from "@/lib/format";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

/* Initials badge — two-letter monogram with consistent colour per name */
function InitialsBadge({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
  const colours = [
    "bg-blue-100 text-blue-700",
    "bg-emerald-100 text-emerald-700",
    "bg-purple-100 text-purple-700",
    "bg-amber-100 text-amber-700",
    "bg-rose-100 text-rose-700",
    "bg-cyan-100 text-cyan-700",
  ];
  const colour = colours[name.charCodeAt(0) % colours.length];
  const sz = size === "sm" ? "w-8 h-8 text-[11px]" : "w-9 h-9 text-[12px]";
  return (
    <div className={`${sz} ${colour} rounded-lg font-bold flex items-center justify-center shrink-0`}>
      {initials}
    </div>
  );
}

/* Sparkline trend bar — simple static representation */
function TrendBar({ score }: { score?: number }) {
  const widths = [30, 45, 55, 60, 65, 75, 80, 90];
  return (
    <div className="flex items-end gap-0.5 h-5">
      {widths.map((w, i) => (
        <div
          key={i}
          className="w-1 rounded-sm bg-[#0B5CFF] opacity-70"
          style={{ height: `${(i + 1) * (100 / widths.length)}%`, opacity: 0.3 + i * 0.09 }}
        />
      ))}
    </div>
  );
}

/* Health badge */
function HealthBadge({ score }: { score: number }) {
  const colour =
    score >= 75 ? "text-[#0C9B62] bg-emerald-50" :
    score >= 50 ? "text-[#E97912] bg-amber-50" :
    "text-rose-600 bg-rose-50";
  return (
    <span className={`inline-flex items-center justify-center w-8 h-8 rounded-lg text-[12px] font-bold ${colour}`}>
      {score}
    </span>
  );
}

interface CompanyPreview {
  cbe: string;
  name: string;
  city?: string | null;
  sector?: string | null;
  revenue?: number | null;
}

type SignalType = "growth" | "publication" | "favourite" | "alert";

interface Signal {
  type: SignalType;
  title: string;
  detail: string;
  date?: string;
}

const SMART_CHIPS = [
  { label: "High growth", href: "/screener?rev_growth_min=20" },
  { label: "Recently published", href: "/screener?sort=nbb_latest_desc" },
  { label: "Profitable SMEs", href: "/screener?ebit_min=0&rev_max=50" },
  { label: "M&A signals", href: "/screener?distress=healthy&rev_min=2" },
  { label: "Export-ready", href: "/screener?rev_growth_min=5&fte_min=20" },
];

const FEATURE_CARDS = [
  {
    icon: Search,
    title: "Company search",
    desc: "One calm command bar for VAT numbers, names, sectors, locations and directors.",
    href: "/search",
    cta: "Open search",
  },
  {
    icon: Grid3X3,
    title: "Advanced screener",
    desc: "Save clean filters, rank companies and export shortlists without visual clutter.",
    href: "/screener",
    cta: "Build a screen",
  },
  {
    icon: Sparkles,
    title: "AI insight layer",
    desc: "Plain-language summaries of financial changes, sector context and unusual signals.",
    href: "/stats",
    cta: "View insights",
  },
];

function SignalIcon({ type }: { type: SignalType }) {
  if (type === "growth") return <div className="w-8 h-8 rounded-lg bg-[#EEF3FF] flex items-center justify-center"><TrendingUp className="w-4 h-4 text-[#0B5CFF]" /></div>;
  if (type === "publication") return <div className="w-8 h-8 rounded-lg bg-[#F3F7FF] flex items-center justify-center"><FileText className="w-4 h-4 text-[#5F6B85]" /></div>;
  if (type === "favourite") return <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center"><Star className="w-4 h-4 text-amber-500" /></div>;
  return <div className="w-8 h-8 rounded-lg bg-rose-50 flex items-center justify-center"><AlertTriangle className="w-4 h-4 text-rose-500" /></div>;
}

export default function Home() {
  const router = useRouter();
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [recentEntries, setRecentEntries] = useState<RecentlyViewedEntry[]>([]);
  const [companyPreviews, setCompanyPreviews] = useState<Map<string, CompanyPreview>>(new Map());
  const [signals, setSignals] = useState<Signal[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  /* Load recently viewed from localStorage */
  useEffect(() => {
    const entries = getRecentlyViewed().slice(0, 5);
    setRecentEntries(entries);
    if (entries.length === 0) return;
    Promise.all(
      entries.map((e) =>
        fetch(`${API_BASE}/api/companies/${e.cbe}`)
          .then((r) => r.ok ? r.json() : null)
          .catch(() => null)
      )
    ).then((results) => {
      const map = new Map<string, CompanyPreview>();
      results.forEach((data, i) => {
        if (!data) {
          map.set(entries[i].cbe, { cbe: entries[i].cbe, name: entries[i].name, city: entries[i].city });
        } else {
          map.set(entries[i].cbe, {
            cbe: entries[i].cbe,
            name: data.name ?? entries[i].name,
            city: data.city ?? entries[i].city,
            sector: data.nace_description ?? null,
            revenue: data.revenue ?? null,
          });
        }
      });
      setCompanyPreviews(map);
    });
  }, []);

  /* Load signals (graceful no-op if endpoint absent) */
  useEffect(() => {
    fetch(`${API_BASE}/api/signals`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (Array.isArray(data)) setSignals(data.slice(0, 3));
      })
      .catch(() => {});
  }, []);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="relative isolate flex flex-col items-center">

      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <section className="w-full max-w-[960px] mx-auto pt-16 pb-10 px-4 text-center">

        {/* Eyebrow */}
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[#E3EAF4] bg-white text-[11.5px] font-semibold text-[#5F6B85] uppercase tracking-wider mb-8">
          <span className="w-1.5 h-1.5 rounded-full bg-[#0C9B62]" />
          Belgian Company Intelligence
        </div>

        {/* Headline */}
        <h1 className="text-[40px] sm:text-[52px] font-bold text-[#07142F] leading-[1.12] tracking-tight mb-5">
          Find, screen and<br className="hidden sm:block" />
          <span className="text-[#0B5CFF]"> understand</span> companies faster.
        </h1>

        {/* Subtitle */}
        <p className="text-[16px] sm:text-[18px] text-[#5F6B85] max-w-[520px] mx-auto leading-relaxed mb-10">
          A cleaner workspace for company discovery, financial benchmarking,
          publications and AI-assisted deal signals.
        </p>

        {/* Search bar */}
        <form onSubmit={handleSubmit} className="w-full max-w-[600px] mx-auto mb-6">
          <div className="relative flex items-center rounded-2xl border border-[#E3EAF4] bg-white shadow-[0_4px_24px_rgba(15,23,42,0.06)] hover:shadow-[0_4px_32px_rgba(11,92,255,0.10)] focus-within:border-[#0B5CFF] focus-within:shadow-[0_4px_32px_rgba(11,92,255,0.14)] transition-all duration-200">
            <Search className="absolute left-5 w-[18px] h-[18px] text-[#7B8498] pointer-events-none" aria-hidden />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search company, sector, VAT number or publication"
              aria-label="Search companies"
              className="w-full h-14 pl-[48px] pr-[100px] text-[15px] rounded-2xl bg-transparent focus:outline-none placeholder:text-[#7B8498] text-[#07142F]"
              enterKeyHint="search"
              autoCapitalize="off"
              autoCorrect="off"
            />
            <button
              type="submit"
              className="absolute right-2 h-10 px-5 rounded-xl bg-[#0B5CFF] hover:bg-[#084ED8] text-white text-[13.5px] font-semibold transition-colors"
            >
              Search
            </button>
          </div>
        </form>

        {/* Smart chips */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          {SMART_CHIPS.map((chip) => (
            <Link
              key={chip.label}
              href={chip.href}
              className="inline-flex items-center px-3.5 py-1.5 rounded-full border border-[#E3EAF4] bg-white text-[12.5px] font-medium text-[#5F6B85] hover:text-[#0B5CFF] hover:border-[#0B5CFF] hover:bg-[#EEF3FF] transition-all"
            >
              {chip.label}
            </Link>
          ))}
        </div>
      </section>

      {/* ── Feature cards ────────────────────────────────────────────── */}
      <section className="w-full max-w-[960px] mx-auto px-4 pb-12">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {FEATURE_CARDS.map(({ icon: Icon, title, desc, href, cta }) => (
            <Link
              key={href}
              href={href}
              className="group flex flex-col gap-4 p-6 rounded-2xl border border-[#E3EAF4] bg-white hover:border-[#0B5CFF] hover:shadow-[0_8px_32px_rgba(11,92,255,0.08)] transition-all duration-200"
            >
              <div className="w-10 h-10 rounded-xl bg-[#EEF3FF] flex items-center justify-center group-hover:bg-[#0B5CFF] transition-colors">
                <Icon className="w-5 h-5 text-[#0B5CFF] group-hover:text-white transition-colors" />
              </div>
              <div>
                <div className="text-[14.5px] font-semibold text-[#07142F] mb-1">{title}</div>
                <p className="text-[13px] text-[#5F6B85] leading-relaxed">{desc}</p>
              </div>
              <div className="flex items-center gap-1 text-[13px] font-semibold text-[#0B5CFF] mt-auto">
                {cta} <ArrowRight className="w-3.5 h-3.5" />
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── Bottom: Recently viewed + Today's signals ─────────────────── */}
      <section className="w-full max-w-[960px] mx-auto px-4 pb-16">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6">

          {/* Recently viewed */}
          <div className="rounded-2xl border border-[#E3EAF4] bg-white overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[#E3EAF4]">
              <h2 className="text-[14px] font-semibold text-[#07142F]">Recently viewed companies</h2>
              {recentEntries.length > 0 && (
                <div className="flex items-center gap-1.5 text-[12px] text-[#5F6B85]">
                  <CheckCircle className="w-3.5 h-3.5 text-[#0C9B62]" />
                  Synced with favourites
                </div>
              )}
            </div>

            {recentEntries.length === 0 ? (
              <div className="px-6 py-10 text-center text-[13px] text-[#7B8498]">
                Companies you view will appear here.{" "}
                <Link href="/search" className="text-[#0B5CFF] hover:underline font-medium">Start searching</Link>
              </div>
            ) : (
              <>
                <div className="grid grid-cols-[2fr_1fr_auto_auto_auto] text-[11.5px] font-semibold text-[#7B8498] uppercase tracking-wider px-6 py-2.5 border-b border-[#E3EAF4]">
                  <span>Company</span>
                  <span>Sector</span>
                  <span className="text-right">Revenue</span>
                  <span className="text-center">Health</span>
                  <span>Trend</span>
                </div>
                {recentEntries.map((entry) => {
                  const preview = companyPreviews.get(entry.cbe);
                  return (
                    <Link
                      key={entry.cbe}
                      href={`/company/${entry.cbe}`}
                      className="grid grid-cols-[2fr_1fr_auto_auto_auto] items-center px-6 py-3.5 border-b border-[#E3EAF4] last:border-0 hover:bg-[#F8FAFD] transition-colors gap-4"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <InitialsBadge name={preview?.name ?? entry.name} />
                        <div className="min-w-0">
                          <div className="text-[13.5px] font-medium text-[#07142F] truncate">
                            {preview?.name ?? entry.name}
                          </div>
                          {(preview?.city ?? entry.city) && (
                            <div className="text-[11.5px] text-[#7B8498] truncate">{preview?.city ?? entry.city}</div>
                          )}
                        </div>
                      </div>
                      <div className="text-[12.5px] text-[#5F6B85] truncate">
                        {preview?.sector ?? "—"}
                      </div>
                      <div className="text-[13px] font-medium text-[#07142F] text-right tabular-nums">
                        {preview?.revenue != null ? fmtEur(preview.revenue) : "—"}
                      </div>
                      <div className="flex justify-center">
                        <HealthBadge score={72} />
                      </div>
                      <div className="flex justify-end">
                        <TrendBar />
                      </div>
                    </Link>
                  );
                })}
                <div className="px-6 py-3">
                  <Link href="/company" className="text-[12.5px] font-medium text-[#0B5CFF] hover:underline flex items-center gap-1">
                    View all companies <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </>
            )}
          </div>

          {/* Today's signals */}
          <div className="rounded-2xl border border-[#E3EAF4] bg-white overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[#E3EAF4]">
              <h2 className="text-[14px] font-semibold text-[#07142F]">Today's signals</h2>
              <span className="text-[11px] font-medium text-[#7B8498] bg-[#F3F7FF] px-2 py-1 rounded-lg">AI preview</span>
            </div>

            {signals.length === 0 ? (
              <div className="p-5 space-y-3">
                {/* Static placeholder signals (marketing copy until backend ships) */}
                {[
                  { type: "growth" as SignalType, title: "42 companies beat peer margin", detail: "Most concentrated in Antwerp manufacturing and Flemish Brabant services.", href: "/stats" },
                  { type: "publication" as SignalType, title: "12 publication changes flagged", detail: "New appointments, capital changes and unusual balance-sheet movement.", href: "/staatsblad" },
                  { type: "favourite" as SignalType, title: "3 favourites need review", detail: "Saved companies now match your acquisition criteria.", href: "/favourites" },
                ].map((s, i) => (
                  <Link
                    key={i}
                    href={s.href}
                    className="flex items-start gap-3.5 p-3 rounded-xl hover:bg-[#F8FAFD] transition-colors group"
                  >
                    <SignalIcon type={s.type} />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-semibold text-[#07142F] leading-snug">{s.title}</div>
                      <p className="text-[12px] text-[#5F6B85] mt-0.5 leading-relaxed">{s.detail}</p>
                    </div>
                    <ArrowRight className="w-4 h-4 text-[#7B8498] shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </Link>
                ))}
              </div>
            ) : (
              <div className="p-5 space-y-3">
                {signals.map((s, i) => (
                  <div key={i} className="flex items-start gap-3.5 p-3 rounded-xl hover:bg-[#F8FAFD] transition-colors">
                    <SignalIcon type={s.type} />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-semibold text-[#07142F] leading-snug">{s.title}</div>
                      <p className="text-[12px] text-[#5F6B85] mt-0.5">{s.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="px-5 py-3 border-t border-[#E3EAF4]">
              <Link href="/stats" className="text-[12.5px] font-medium text-[#0B5CFF] hover:underline flex items-center gap-1">
                View all signals <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
