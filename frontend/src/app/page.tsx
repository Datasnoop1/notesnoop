"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Search } from "lucide-react";
import { useTranslation } from "@/components/language-provider";
import FeedbackButtons from "@/components/feedback-buttons";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export default function Home() {
  const router = useRouter();
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [logoPath, setLogoPath] = useState("/logos/dog-telescope-clean.jpeg");
  const inputRef = useRef<HTMLInputElement>(null);

  const whatsNewItems = [
    { titleKey: "home.whatsNewItems.unifiedSearch", descKey: "home.whatsNewItems.unifiedSearchDesc" },
    { titleKey: "home.whatsNewItems.sectorBenchmarking", descKey: "home.whatsNewItems.sectorBenchmarkingDesc" },
    { titleKey: "home.whatsNewItems.smartFilters", descKey: "home.whatsNewItems.smartFiltersDesc" },
    { titleKey: "home.whatsNewItems.dataAlerts", descKey: "home.whatsNewItems.dataAlertsDesc" },
    { titleKey: "home.whatsNewItems.customerSupplierLists", descKey: "home.whatsNewItems.customerSupplierListsDesc" },
    { titleKey: "home.whatsNewItems.fullExport", descKey: "home.whatsNewItems.fullExportDesc" },
  ];

  useEffect(() => {
    fetch(`${API_BASE}/api/site-config`)
      .then((r) => r.json())
      .then((data) => {
        if (data.site_logo) setLogoPath(data.site_logo);
      })
      .catch(() => {});
  }, []);

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
    <div className="relative isolate flex flex-col items-center px-4 pt-[10vh] pb-24">
      {/* Decorative teal radial — matches use-cases.html hero glow. Pointer-events-none so it never traps clicks. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px] -z-10"
        style={{
          background:
            "radial-gradient(ellipse at center top, rgba(13,115,119,0.08), transparent 60%)",
        }}
      />
      {/* Brand */}
      <div className="flex flex-col items-center mb-12 sm:mb-14">
        <img
          src={logoPath}
          alt=""
          width={72}
          height={72}
          className="rounded-xl bg-white mb-6 sm:mb-7 opacity-95 sm:w-[88px] sm:h-[88px]"
        />
        <div className="flex items-baseline gap-2 sm:gap-3">
          <h1 className="text-4xl sm:text-6xl font-light tracking-tight">
            <span className="text-gray-900">data</span><span className="text-brand">snoop</span>
          </h1>
          <span className="text-[11px] sm:text-[12px] font-medium text-gray-400 uppercase tracking-[0.2em]">
            Beta
          </span>
        </div>
      </div>

      {/* Search */}
      <form onSubmit={handleSubmit} className="w-full max-w-xl">
        <div className="group relative flex items-center rounded-full border border-gray-200 bg-white shadow-[0_1px_6px_rgba(32,33,36,0.06)] hover:shadow-[0_1px_10px_rgba(32,33,36,0.12)] focus-within:shadow-[0_1px_10px_rgba(32,33,36,0.16)] focus-within:border-gray-300 transition-shadow">
          <Search className="absolute left-5 w-4 h-4 text-gray-400 pointer-events-none" aria-hidden />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Start searching companies or persons here"
            aria-label="Start searching companies or persons here"
            className="w-full h-12 sm:h-14 pl-12 pr-5 text-base rounded-full bg-transparent focus:outline-none placeholder:text-gray-400 text-gray-900"
            enterKeyHint="search"
            autoCapitalize="off"
            autoCorrect="off"
          />
        </div>

        {/* Secondary actions — bug, feature, donate, guide.
            (Primary actions like Screener / Favourites / Compare / Aggregate
            and Sign-in live in the header on every page.) */}
        <div className="mt-8 flex flex-wrap items-center justify-center gap-y-1 text-[13px] text-gray-500">
          <FeedbackButtons />
          <span className="text-gray-300" aria-hidden>·</span>
          <Link href="/guide" className="px-3 sm:px-4 py-2.5 sm:py-2 min-h-[44px] inline-flex items-center rounded-md hover:bg-gray-50 transition-colors">
            User guide
          </Link>
          <span className="text-gray-300" aria-hidden>·</span>
          <a href="/use-cases.html" className="px-3 sm:px-4 py-2.5 sm:py-2 min-h-[44px] inline-flex items-center rounded-md hover:bg-gray-50 transition-colors">
            Use cases
          </a>
        </div>
      </form>

      {/* What's new */}
      <section className="mt-16 sm:mt-40 w-full max-w-2xl">
        <div className="rounded-2xl border border-gray-200 bg-white p-6 sm:p-8 shadow-[0_1px_3px_rgba(32,33,36,0.04)]">
          <div className="flex items-center gap-2 mb-6">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" aria-hidden />
            <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-[0.18em]">
              {t("home.whatsNew")}
            </span>
          </div>

          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-5">
            {whatsNewItems.map((item) => (
              <li key={item.titleKey} className="flex gap-3">
                <span className="text-gray-300 text-sm leading-6 select-none shrink-0">—</span>
                <div>
                  <div className="text-sm font-medium text-gray-900">
                    {t(item.titleKey)}
                  </div>
                  <p className="text-[13px] text-gray-500 mt-0.5">
                    {t(item.descKey)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
