"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Search, Grid3X3, Sparkles, ArrowRight, BookOpen, Lightbulb } from "lucide-react";
import { useTranslation } from "@/components/language-provider";

const SMART_CHIPS = [
  { label: "High growth", href: "/screener?rev_growth_min=20", tone: "blue" },
  { label: "Recently published", href: "/screener?sort=nbb_latest_desc", tone: "neutral" },
  { label: "Profitable SMEs", href: "/screener?ebit_min=0&rev_max=50", tone: "green" },
  { label: "M&A signals", href: "/screener?distress=healthy&rev_min=2", tone: "amber" },
  { label: "Export-ready", href: "/screener?rev_growth_min=5&fte_min=20", tone: "neutral" },
];

const CHIP_TONES: Record<string, string> = {
  blue: "border-[#0B5CFF]/30 bg-[#EEF3FF] text-[#0B5CFF] hover:bg-[#0B5CFF] hover:text-white hover:border-[#0B5CFF]",
  green: "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-600 hover:text-white hover:border-emerald-600",
  amber: "border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-500 hover:text-white hover:border-amber-500",
  neutral: "border-[#E3EAF4] bg-white text-[#5F6B85] hover:border-[#0B5CFF] hover:text-[#0B5CFF] hover:bg-[#EEF3FF]",
};

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

/* Decorative hero illustration — magnifier + chart cards in muted blue.
   Mirrors the "search + analytics" feel of the mockup without needing an
   external asset. Pure inline SVG, scales with container. */
function HeroIllustration() {
  return (
    <svg viewBox="0 0 360 280" className="w-full h-auto" aria-hidden>
      {/* Document card behind */}
      <rect x="40" y="30" width="170" height="115" rx="14" fill="#FFFFFF" stroke="#E3EAF4" strokeWidth="1.5" />
      <rect x="56" y="48" width="88" height="6" rx="3" fill="#E3EAF4" />
      <rect x="56" y="62" width="60" height="6" rx="3" fill="#E3EAF4" />
      <rect x="56" y="80" width="138" height="3" rx="1.5" fill="#F3F7FF" />
      <rect x="56" y="90" width="138" height="3" rx="1.5" fill="#F3F7FF" />
      <rect x="56" y="100" width="100" height="3" rx="1.5" fill="#F3F7FF" />
      <rect x="56" y="110" width="138" height="3" rx="1.5" fill="#F3F7FF" />

      {/* Magnifier glass */}
      <circle cx="170" cy="140" r="46" fill="#FFFFFF" stroke="#0B5CFF" strokeWidth="2.5" />
      <circle cx="170" cy="140" r="46" fill="#EEF3FF" opacity="0.4" />
      <line x1="205" y1="174" x2="232" y2="201" stroke="#0B5CFF" strokeWidth="6" strokeLinecap="round" />

      {/* Chart card */}
      <rect x="180" y="155" width="150" height="110" rx="14" fill="#FFFFFF" stroke="#E3EAF4" strokeWidth="1.5" />
      <rect x="196" y="173" width="60" height="5" rx="2.5" fill="#E3EAF4" />
      {/* Mini chart bars */}
      <rect x="196" y="225" width="14" height="22" rx="2" fill="#0B5CFF" opacity="0.25" />
      <rect x="216" y="215" width="14" height="32" rx="2" fill="#0B5CFF" opacity="0.4" />
      <rect x="236" y="200" width="14" height="47" rx="2" fill="#0B5CFF" opacity="0.6" />
      <rect x="256" y="210" width="14" height="37" rx="2" fill="#0B5CFF" opacity="0.5" />
      <rect x="276" y="190" width="14" height="57" rx="2" fill="#0B5CFF" opacity="0.85" />
      <rect x="296" y="195" width="14" height="52" rx="2" fill="#0B5CFF" />
      {/* Donut hint */}
      <circle cx="306" cy="195" r="14" fill="#FFFFFF" stroke="#0B5CFF" strokeWidth="3" strokeDasharray="40 80" transform="rotate(-90 306 195)" />
    </svg>
  );
}

export default function Home() {
  const router = useRouter();
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="relative isolate flex flex-col items-center w-full">

      {/* ── Hero card ────────────────────────────────────────────────── */}
      <section className="w-full max-w-[1200px] mx-auto px-4 pt-6">
        <div className="rounded-[28px] border border-[#E3EAF4] bg-white p-6 sm:p-10 lg:p-12 overflow-hidden relative shadow-[0_8px_40px_rgba(15,23,42,0.04)]">

          {/* Subtle accent gradient — top-right corner wash */}
          <div
            aria-hidden
            className="pointer-events-none absolute -top-20 -right-20 w-[420px] h-[420px] rounded-full opacity-60"
            style={{ background: "radial-gradient(circle, rgba(238,243,255,0.9) 0%, rgba(248,250,253,0) 60%)" }}
          />

          <div className="grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-8 lg:gap-12 items-center relative">

            {/* Left: text + search */}
            <div className="text-left">
              {/* Eyebrow */}
              <div className="text-[11.5px] font-bold text-[#0B5CFF] uppercase tracking-[0.14em] mb-5">
                Belgian Company Intelligence
              </div>

              {/* Headline — serif-flavoured weight, bigger on desktop */}
              <h1 className="text-[34px] sm:text-[44px] lg:text-[52px] font-bold text-[#07142F] leading-[1.08] tracking-tight mb-5">
                Find, screen and<br />
                understand companies faster.
              </h1>

              {/* Subtitle */}
              <p className="text-[15px] sm:text-[16.5px] text-[#5F6B85] leading-relaxed mb-7 max-w-[520px]">
                A cleaner workspace for company discovery, financial benchmarking,
                publications and AI-assisted deal signals.
              </p>

              {/* Search bar */}
              <form onSubmit={handleSubmit} className="w-full max-w-[560px] mb-5">
                <div className="relative flex items-center rounded-2xl border border-[#E3EAF4] bg-white shadow-[0_2px_12px_rgba(15,23,42,0.04)] hover:shadow-[0_4px_20px_rgba(11,92,255,0.08)] focus-within:border-[#0B5CFF] focus-within:shadow-[0_4px_20px_rgba(11,92,255,0.12)] transition-all duration-200">
                  <Search className="absolute left-5 w-[18px] h-[18px] text-[#7B8498] pointer-events-none" aria-hidden />
                  <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search company, sector, VAT number or publication"
                    aria-label="Search companies"
                    className="w-full h-[52px] pl-[48px] pr-[100px] text-[14.5px] rounded-2xl bg-transparent focus:outline-none placeholder:text-[#7B8498] text-[#07142F]"
                    enterKeyHint="search"
                    autoCapitalize="off"
                    autoCorrect="off"
                  />
                  <button
                    type="submit"
                    className="absolute right-1.5 h-[42px] px-5 rounded-xl bg-[#0B5CFF] hover:bg-[#084ED8] text-white text-[13.5px] font-semibold transition-colors"
                  >
                    Search
                  </button>
                </div>
              </form>

              {/* Smart chips */}
              <div className="flex flex-wrap items-center gap-2">
                {SMART_CHIPS.map((chip) => (
                  <Link
                    key={chip.label}
                    href={chip.href}
                    className={`inline-flex items-center px-3.5 py-1.5 rounded-full border text-[12.5px] font-medium transition-all ${CHIP_TONES[chip.tone] ?? CHIP_TONES.neutral}`}
                  >
                    {chip.label}
                  </Link>
                ))}
              </div>

              {/* Secondary actions: guide + use cases (feedback icons live in the header) */}
              <div className="mt-6 flex flex-wrap items-center gap-y-1 text-[13px] text-[#5F6B85]">
                <Link
                  href="/guide"
                  className="px-3 py-2 min-h-[40px] inline-flex items-center gap-1.5 rounded-md hover:bg-[#F3F7FF] hover:text-[#0B5CFF] transition-colors"
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  User guide
                </Link>
                <span className="text-[#C3CEDF] mx-1" aria-hidden>·</span>
                <a
                  href="/use-cases.html"
                  className="px-3 py-2 min-h-[40px] inline-flex items-center gap-1.5 rounded-md hover:bg-[#F3F7FF] hover:text-[#0B5CFF] transition-colors"
                >
                  <Lightbulb className="w-3.5 h-3.5" />
                  Use cases
                </a>
              </div>
            </div>

            {/* Right: illustration — hidden on mobile to keep the hero compact */}
            <div className="hidden lg:flex items-center justify-center">
              <HeroIllustration />
            </div>
          </div>
        </div>
      </section>

      {/* ── Feature cards ────────────────────────────────────────────── */}
      <section className="w-full max-w-[1200px] mx-auto px-4 pt-6 pb-16">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {FEATURE_CARDS.map(({ icon: Icon, title, desc, href, cta }) => (
            <Link
              key={href}
              href={href}
              className="group flex flex-col gap-4 p-6 rounded-2xl border border-[#E3EAF4] bg-white hover:border-[#0B5CFF] hover:shadow-[0_8px_32px_rgba(11,92,255,0.08)] transition-all duration-200"
            >
              <div className="w-11 h-11 rounded-xl bg-[#EEF3FF] flex items-center justify-center group-hover:bg-[#0B5CFF] transition-colors">
                <Icon className="w-5 h-5 text-[#0B5CFF] group-hover:text-white transition-colors" />
              </div>
              <div>
                <div className="text-[15px] font-semibold text-[#07142F] mb-1">{title}</div>
                <p className="text-[13px] text-[#5F6B85] leading-relaxed">{desc}</p>
              </div>
              <div className="flex items-center gap-1 text-[13px] font-semibold text-[#0B5CFF] mt-auto">
                {cta} <ArrowRight className="w-3.5 h-3.5" />
              </div>
            </Link>
          ))}
        </div>
      </section>

    </div>
  );
}
