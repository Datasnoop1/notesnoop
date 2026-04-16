"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Search } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [logoPath, setLogoPath] = useState("/logos/dog-telescope-clean.jpeg");
  const inputRef = useRef<HTMLInputElement>(null);

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
    <div className="flex flex-col items-center px-4 pt-[10vh] pb-24 bg-white">
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
          <h1 className="text-5xl sm:text-7xl font-light text-gray-900 tracking-tight">
            Datasnoop
          </h1>
          <span className="text-[10px] sm:text-[11px] font-medium text-gray-400 uppercase tracking-[0.2em]">
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

        {/* Secondary actions */}
        <div className="mt-8 flex items-center justify-center gap-3 text-[13px] text-gray-600">
          <Link href="/screener" className="px-4 py-2 rounded-md hover:bg-gray-50 transition-colors">
            Browse the screener
          </Link>
          <span className="text-gray-300">·</span>
          <Link href="/guide" className="px-4 py-2 rounded-md hover:bg-gray-50 transition-colors">
            User guide
          </Link>
        </div>
      </form>

      {/* What's new */}
      <section className="mt-32 sm:mt-40 w-full max-w-xl">
        <div className="rounded-2xl border border-gray-200 bg-white p-6 sm:p-8 shadow-[0_1px_3px_rgba(32,33,36,0.04)]">
          <div className="flex items-center gap-2 mb-5">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500" aria-hidden />
            <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-[0.18em]">
              What&rsquo;s new
            </span>
          </div>

          <ul className="space-y-4">
            <li className="flex gap-3">
              <span className="text-gray-300 text-sm leading-6 select-none">—</span>
              <div>
                <div className="text-sm font-medium text-gray-900">
                  Refreshed, distraction-free landing
                </div>
                <p className="text-[13px] text-gray-500 mt-0.5">
                  White background, bigger brand, search front and centre.
                </p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="text-gray-300 text-sm leading-6 select-none">—</span>
              <div>
                <div className="text-sm font-medium text-gray-900">
                  Persistent search bar on every page
                </div>
                <p className="text-[13px] text-gray-500 mt-0.5">
                  Jump to a company or person from anywhere in the app.
                </p>
              </div>
            </li>
            <li className="flex gap-3">
              <span className="text-gray-300 text-sm leading-6 select-none">—</span>
              <div>
                <div className="text-sm font-medium text-gray-900">
                  Mobile experience in progress
                </div>
                <p className="text-[13px] text-gray-500 mt-0.5">
                  Full power-user functionality on phone is the next focus.
                </p>
              </div>
            </li>
          </ul>
        </div>
      </section>
    </div>
  );
}
