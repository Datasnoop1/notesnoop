"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

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
    <div className="min-h-[calc(100vh-14rem)] flex flex-col items-center justify-center px-4 bg-white">
      {/* Brand */}
      <div className="flex flex-col items-center mb-10 sm:mb-12">
        <img
          src={logoPath}
          alt=""
          width={64}
          height={64}
          className="rounded-lg bg-white mb-5 sm:mb-6 opacity-95 sm:w-[72px] sm:h-[72px]"
        />
        <div className="flex items-baseline gap-2 sm:gap-2.5">
          <h1 className="text-4xl sm:text-6xl font-light text-gray-900 tracking-tight">
            Datasnoop
          </h1>
          <span className="text-[10px] sm:text-[11px] font-medium text-gray-400 uppercase tracking-[0.2em]">
            Beta
          </span>
        </div>
      </div>

      {/* Search */}
      <form onSubmit={handleSubmit} className="w-full max-w-xl">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search companies or persons"
          aria-label="Search companies or persons"
          className="w-full h-12 sm:h-14 px-5 text-base rounded-full border border-gray-200 bg-white focus:border-gray-400 focus:outline-none transition-colors placeholder:text-gray-400 text-gray-900"
          enterKeyHint="search"
          autoCapitalize="off"
          autoCorrect="off"
        />
      </form>
    </div>
  );
}
