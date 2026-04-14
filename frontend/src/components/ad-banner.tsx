"use client";

import { usePathname } from "next/navigation";

const HIDDEN_PREFIXES = ["/admin", "/login", "/auth"];

export default function AdBanner() {
  const pathname = usePathname();

  const hidden = HIDDEN_PREFIXES.some((p) => pathname.startsWith(p));
  if (hidden) return null;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2">
      {/* Ad banner — replace with Google AdSense when ready */}
      <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-center text-xs text-slate-400">
        <span>Advertisement</span>
        {/* Replace with: <ins className="adsbygoogle" ... /> */}
      </div>
    </div>
  );
}
