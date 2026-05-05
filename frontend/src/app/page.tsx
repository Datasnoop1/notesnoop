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
  blue: "border-[#1687E8]/30 bg-[#EAF5FF] text-[#1687E8] hover:bg-[#1687E8] hover:text-white hover:border-[#1687E8]",
  green: "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-600 hover:text-white hover:border-emerald-600",
  amber: "border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-500 hover:text-white hover:border-amber-500",
  neutral: "border-[#E2E8F2] bg-white text-[#5F6B85] hover:border-[#1687E8] hover:text-[#1687E8] hover:bg-[#EAF5FF]",
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
   Mirrors the "search + analytics" feel without needing an external
   asset. Pure inline SVG, scales with container. */
function HeroIllustration() {
  return (
    <svg viewBox="0 0 360 280" className="w-full h-auto" aria-hidden>
      <rect x="40" y="30" width="170" height="115" rx="14" fill="#FFFFFF" stroke="#E2E8F2" strokeWidth="1.5" />
      <rect x="56" y="48" width="88" height="6" rx="3" fill="#E2E8F2" />
      <rect x="56" y="62" width="60" height="6" rx="3" fill="#E2E8F2" />
      <rect x="56" y="80" width="138" height="3" rx="1.5" fill="#F3F6FB" />
      <rect x="56" y="90" width="138" height="3" rx="1.5" fill="#F3F6FB" />
      <rect x="56" y="100" width="100" height="3" rx="1.5" fill="#F3F6FB" />
      <rect x="56" y="110" width="138" height="3" rx="1.5" fill="#F3F6FB" />
      <circle cx="170" cy="140" r="46" fill="#FFFFFF" stroke="#1687E8" strokeWidth="2.5" />
      <circle cx="170" cy="140" r="46" fill="#EAF5FF" opacity="0.4" />
      <line x1="205" y1="174" x2="232" y2="201" stroke="#1687E8" strokeWidth="6" strokeLinecap="round" />
      <rect x="180" y="155" width="150" height="110" rx="14" fill="#FFFFFF" stroke="#E2E8F2" strokeWidth="1.5" />
      <rect x="196" y="173" width="60" height="5" rx="2.5" fill="#E2E8F2" />
      <rect x="196" y="225" width="14" height="22" rx="2" fill="#1687E8" opacity="0.25" />
      <rect x="216" y="215" width="14" height="32" rx="2" fill="#1687E8" opacity="0.4" />
      <rect x="236" y="200" width="14" height="47" rx="2" fill="#1687E8" opacity="0.6" />
      <rect x="256" y="210" width="14" height="37" rx="2" fill="#1687E8" opacity="0.5" />
      <rect x="276" y="190" width="14" height="57" rx="2" fill="#1687E8" opacity="0.85" />
      <rect x="296" y="195" width="14" height="52" rx="2" fill="#1687E8" />
      <circle cx="306" cy="195" r="14" fill="#FFFFFF" stroke="#1687E8" strokeWidth="3" strokeDasharray="40 80" transform="rotate(-90 306 195)" />
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
      <section className="relative w-full max-w-[1200px] mx-auto px-3 sm:px-4 pt-4 sm:pt-6">
        {/* Decorative colour blobs sitting BEHIND the glass hero, so the
            frosted card has rich tones to blur. Hidden on small screens
            (the body aura already provides enough colour at mobile sizes). */}
        <div
          aria-hidden
          className="pointer-events-none absolute hidden md:block -top-10 -left-10 w-[420px] h-[420px] rounded-full blur-[80px] opacity-55"
          style={{ background: "radial-gradient(circle, rgba(22,135,232,0.45) 0%, rgba(22,135,232,0) 70%)" }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute hidden md:block top-20 -right-20 w-[460px] h-[460px] rounded-full blur-[80px] opacity-50"
          style={{ background: "radial-gradient(circle, rgba(31,155,143,0.40) 0%, rgba(31,155,143,0) 70%)" }}
        />
        <div className="glass-card rounded-2xl sm:rounded-[28px] p-5 sm:p-10 lg:p-12 overflow-hidden relative">

          {/* Subtle accent gradient — top-right corner wash. Sits inside
              the frosted hero so the corner picks up a touch of sky-blue
              tint behind the glass. */}
          <div
            aria-hidden
            className="pointer-events-none absolute -top-20 -right-20 w-[420px] h-[420px] rounded-full opacity-70"
            style={{ background: "radial-gradient(circle, rgba(234,245,255,0.95) 0%, rgba(247,249,252,0) 60%)" }}
          />

          <div className="grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-8 lg:gap-12 items-center relative">

            {/* Left: text + search */}
            <div className="text-left">
              {/* Eyebrow */}
              <div className="text-[11px] sm:text-[11.5px] font-bold text-[#1687E8] uppercase tracking-[0.14em] mb-3 sm:mb-5">
                Company Intelligence
              </div>

              {/* Headline — kept deliberately subtle. Wink first, shout never. */}
              <h1 className="text-[24px] sm:text-[30px] lg:text-[34px] font-semibold text-[#08132B] leading-[1.15] tracking-tight mb-2 sm:mb-3">
                Just snoop it.
              </h1>

              {/* Subtitle — carries the actual value-prop so the headline can stay light. */}
              <p className="text-[14px] sm:text-[15.5px] text-[#5F6B85] leading-relaxed mb-5 sm:mb-6 max-w-[480px]">
                Every Belgian company, every filing, every director and owner —
                in one fast workspace. Built by the people who actually use it.
              </p>

              {/* Search bar */}
              <form onSubmit={handleSubmit} className="w-full max-w-[460px] mb-4 sm:mb-5">
                <div className="relative flex items-center rounded-xl border border-[#E2E8F2] bg-white shadow-[0_1px_8px_rgba(15,23,42,0.03)] hover:shadow-[0_3px_14px_rgba(22,135,232,0.06)] focus-within:border-[#1687E8] focus-within:shadow-[0_3px_14px_rgba(22,135,232,0.1)] transition-all duration-200">
                  <Search className="absolute left-3.5 sm:left-4 w-[18px] h-[18px] sm:w-[16px] sm:h-[16px] text-[#8791A6] pointer-events-none" aria-hidden />
                  <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search company, sector, VAT or publication"
                    aria-label="Search companies"
                    /* h-[52px] mobile / h-[48px] desktop — the input
                       previously sat at 44px which is the WCAG floor;
                       phones with a thumb covering half the row need a
                       larger landing zone. Right padding (104px) leaves
                       space for the floating Search pill. */
                    className="w-full h-[52px] sm:h-[48px] pl-[42px] sm:pl-[40px] pr-[104px] text-[16px] sm:text-[14px] rounded-xl bg-transparent focus:outline-none placeholder:text-[#8791A6] text-[#08132B]"
                    enterKeyHint="search"
                    autoCapitalize="off"
                    autoCorrect="off"
                  />
                  <button
                    type="submit"
                    aria-label="Search"
                    className="absolute right-1.5 h-[44px] sm:h-[40px] px-4 rounded-lg bg-[#1687E8] hover:bg-[#0F72C8] active:bg-[#0A5BA0] text-white text-[14px] sm:text-[13px] font-semibold transition-colors"
                  >
                    Search
                  </button>
                </div>
              </form>

              {/* Smart chips — horizontal-scroll row on mobile so we
                  don't reflow into 3+ rows on narrow phones. Snap-aligns
                  individual chips so a quick swipe parks the next one
                  near the leading edge instead of mid-chip. */}
              <div className="flex sm:flex-wrap items-center gap-2 overflow-x-auto sm:overflow-visible -mx-3 sm:mx-0 px-3 sm:px-0 snap-x snap-mandatory sm:snap-none pb-1 sm:pb-0">
                {SMART_CHIPS.map((chip) => (
                  <Link
                    key={chip.label}
                    href={chip.href}
                    className={`inline-flex items-center px-3.5 py-2 sm:py-1.5 rounded-full border text-[13px] sm:text-[12.5px] font-medium transition-all shrink-0 snap-start min-h-[40px] sm:min-h-[36px] ${CHIP_TONES[chip.tone] ?? CHIP_TONES.neutral}`}
                  >
                    {chip.label}
                  </Link>
                ))}
              </div>

              {/* Secondary actions: guide + knowledge base + use cases (feedback icons live in the header) */}
              <div className="mt-6 flex flex-wrap items-center gap-y-1 text-[13px] text-[#5F6B85]">
                <Link
                  href="/guide"
                  className="px-3 py-2 min-h-[40px] inline-flex items-center gap-1.5 rounded-md hover:bg-[#F3F6FB] hover:text-[#1687E8] transition-colors"
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  User guide
                </Link>
                <span className="text-[#C3CEDF] mx-1" aria-hidden>·</span>
                <Link
                  href="/learn"
                  className="px-3 py-2 min-h-[40px] inline-flex items-center gap-1.5 rounded-md hover:bg-[#F3F6FB] hover:text-[#1687E8] transition-colors"
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  Knowledge base
                </Link>
                <span className="text-[#C3CEDF] mx-1" aria-hidden>·</span>
                <a
                  href="/use-cases.html"
                  className="px-3 py-2 min-h-[40px] inline-flex items-center gap-1.5 rounded-md hover:bg-[#F3F6FB] hover:text-[#1687E8] transition-colors"
                >
                  <Lightbulb className="w-3.5 h-3.5" />
                  Use cases
                </a>
              </div>
            </div>

            {/* Right: hero illustration — hidden on mobile to keep the hero compact */}
            <div className="hidden lg:flex items-center justify-center">
              <HeroIllustration />
            </div>
          </div>
        </div>
      </section>

      {/* ── Feature cards ────────────────────────────────────────────── */}
      <section className="w-full max-w-[1200px] mx-auto px-3 sm:px-4 pt-4 sm:pt-6">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
          {FEATURE_CARDS.map(({ icon: Icon, title, desc, href, cta }) => (
            <Link
              key={href}
              href={href}
              className="group flex flex-col gap-3 sm:gap-4 p-5 sm:p-6 rounded-2xl border border-[#E2E8F2] bg-white hover:border-[#1687E8] hover:shadow-[0_8px_32px_rgba(22,135,232,0.08)] active:bg-[#F7F9FC] transition-all duration-200"
            >
              <div className="w-11 h-11 rounded-xl bg-[#EAF5FF] flex items-center justify-center group-hover:bg-[#1687E8] transition-colors">
                <Icon className="w-5 h-5 text-[#1687E8] group-hover:text-white transition-colors" />
              </div>
              <div>
                <div className="text-[15px] font-semibold text-[#08132B] mb-1">{title}</div>
                <p className="text-[13px] text-[#5F6B85] leading-relaxed">{desc}</p>
              </div>
              <div className="flex items-center gap-1 text-[13px] font-semibold text-[#1687E8] mt-auto">
                {cta} <ArrowRight className="w-3.5 h-3.5" />
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── How Datasnoop works (prose) ──────────────────────────────── */}
      <section className="w-full max-w-[1200px] mx-auto px-3 sm:px-4 pt-12 sm:pt-16 pb-12 sm:pb-16">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_2fr] gap-8 lg:gap-12">
          <div>
            <div className="text-[11px] sm:text-[11.5px] font-bold text-[#1687E8] uppercase tracking-[0.14em] mb-3">
              How Datasnoop works
            </div>
            <h2 className="text-[22px] sm:text-[28px] font-bold text-[#08132B] leading-[1.2] tracking-tight mb-3">
              Three public registries, one searchable workspace.
            </h2>
            <p className="text-[14px] text-[#5F6B85] leading-relaxed">
              Every fact on Datasnoop is traceable to the Belgian enterprise registry, the National
              Bank annual accounts, or the Belgian Official Gazette. We aggregate, normalise, and
              enrich &mdash; we do not invent.
            </p>
            <Link
              href="/about"
              className="inline-flex items-center gap-1.5 mt-4 text-[13px] font-semibold text-[#1687E8] hover:text-[#0F72C8]"
            >
              How we source and verify Belgian company data
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="space-y-6 text-[14px] text-[#3D4763] leading-relaxed">
            <div>
              <h3 className="text-[15px] font-semibold text-[#08132B] mb-1.5">
                The Belgian enterprise registry (KBO/BCE)
              </h3>
              <p>
                Every Belgian legal entity has a 10-digit enterprise number from the Crossroads
                Bank. We pull the official KBO data every night and patch in the daily updates,
                so what you see is almost never more than a day old &mdash; the company name, the
                registered address, the NACE activity codes, the juridical form, the
                incorporation date, the status, the branches.
              </p>
            </div>

            <div>
              <h3 className="text-[15px] font-semibold text-[#08132B] mb-1.5">
                Annual accounts at the National Bank (NBB/BNB)
              </h3>
              <p>
                Belgian companies file their accounts in three different formats &mdash; micro,
                abbreviated, full &mdash; depending on their size. We translate all of them into
                the same plain numbers: revenue, EBITDA, profit, debt, equity, headcount. So a
                corner shop and a national chain compare cleanly on one screen, without you
                doing the math.
              </p>
            </div>

            <div>
              <h3 className="text-[15px] font-semibold text-[#08132B] mb-1.5">
                Legal acts in the Belgian Official Gazette
              </h3>
              <p>
                The Belgisch Staatsblad / Moniteur belge captures the drama of corporate life
                &mdash; the boardroom shifts, the sudden mergers, the capital injections, the
                dissolutions. Every notice gets linked to the right company and the right people,
                so a profile shows the full timeline instead of today&apos;s snapshot. One
                profile, one timeline, no PDFs.
              </p>
            </div>

            <div>
              <h3 className="text-[15px] font-semibold text-[#08132B] mb-1.5">
                An AI layer that summarises, not invents
              </h3>
              <p>
                On top of the registries we write plain-language narratives, run semantic search,
                and surface companies that <em>do</em> the same thing rather than just share a
                keyword. The AI only writes what it can prove. If a fact isn&apos;t in the
                filings, the company website, or a public news source, it doesn&apos;t make it
                into the summary &mdash; no hallucinations, no guesswork.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Who uses it ──────────────────────────────────────────────── */}
      <section className="w-full max-w-[1200px] mx-auto px-3 sm:px-4 pb-12 sm:pb-16">
        <div className="rounded-2xl border border-[#E2E8F2] bg-[#F7F9FC] p-6 sm:p-10">
          <div className="text-[11px] sm:text-[11.5px] font-bold text-[#1687E8] uppercase tracking-[0.14em] mb-3">
            Who uses Datasnoop
          </div>
          <h2 className="text-[20px] sm:text-[24px] font-bold text-[#08132B] leading-[1.25] tracking-tight mb-4">
            Built for the people who need to understand a Belgian company in fifteen minutes, not
            in three days.
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-10 gap-y-3 text-[14px] text-[#3D4763] leading-relaxed">
            <p>
              <strong>Corporate development and M&amp;A advisors</strong> use Datasnoop to build
              shortlists for buy-side searches, qualify inbound deal flow, and benchmark a target
              against its sector before going into a first call.
            </p>
            <p>
              <strong>Investors and lenders</strong> use it to triage opportunities at scale,
              cross-check management teams across portfolios, and spot distress signals or growth
              outliers without leaving the screener.
            </p>
            <p>
              <strong>Journalists and researchers</strong> use it to follow the paper trail behind
              a story &mdash; ownership changes, director appointments, address moves, capital
              increases &mdash; without juggling four government portals at once.
            </p>
            <p>
              <strong>Recruiters, sales teams, and credit analysts</strong> use it to verify that a
              counterparty is who they say they are, that the financials line up with the pitch,
              and that the executives in the meeting actually hold the mandates they claim.
            </p>
          </div>
          <div className="mt-6 pt-5 border-t border-[#E2E8F2]">
            <a
              href="/use-cases.html"
              className="inline-flex items-center gap-1.5 text-[13.5px] font-semibold text-[#1687E8] hover:text-[#0F72C8]"
            >
              See a typical day in your profession
              <ArrowRight className="w-3.5 h-3.5" />
            </a>
            <p className="text-[12.5px] text-[#5F6B85] mt-1.5">
              Eleven personas &mdash; accountants, lawyers, M&amp;A advisors, journalists, sales
              teams, real estate, credit analysts and more &mdash; with the exact workflow each
              uses on Datasnoop.
            </p>
          </div>
        </div>
      </section>

    </div>
  );
}
