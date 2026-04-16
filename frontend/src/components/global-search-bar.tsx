"use client";

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Search } from "lucide-react";

export default function GlobalSearchBar() {
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState("");

  if (pathname === "/") return null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="sticky top-16 z-40 bg-white border-b border-slate-200/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2.5">
        <form onSubmit={handleSubmit} className="w-full max-w-2xl mx-auto">
          <div className="group relative flex items-center rounded-full border border-gray-200 bg-white shadow-[0_1px_4px_rgba(32,33,36,0.04)] hover:shadow-[0_1px_8px_rgba(32,33,36,0.1)] focus-within:shadow-[0_1px_8px_rgba(32,33,36,0.14)] focus-within:border-gray-300 transition-shadow">
            <Search className="absolute left-4 w-4 h-4 text-gray-400 pointer-events-none" aria-hidden />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search companies or persons"
              aria-label="Search companies or persons"
              className="w-full h-10 pl-11 pr-4 text-sm rounded-full bg-transparent focus:outline-none placeholder:text-gray-400 text-gray-900"
              enterKeyHint="search"
              autoCapitalize="off"
              autoCorrect="off"
            />
          </div>
        </form>
      </div>
    </div>
  );
}
