"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import Script from "next/script";

const HIDDEN_PREFIXES = ["/admin", "/login", "/auth"];

export default function AdBanner() {
  const pathname = usePathname();
  const [adLoaded, setAdLoaded] = useState(false);

  const hidden = HIDDEN_PREFIXES.some((p) => pathname.startsWith(p));

  useEffect(() => {
    if (hidden) return;
    try {
      // @ts-expect-error — adsbygoogle is injected by the script
      (window.adsbygoogle = window.adsbygoogle || []).push({});
      // Check if ad rendered after a delay
      setTimeout(() => {
        const ins = document.querySelector(".adsbygoogle");
        if (ins && ins.getAttribute("data-ad-status") === "filled") {
          setAdLoaded(true);
        }
      }, 3000);
    } catch {
      // Ad blocker or script not loaded
    }
  }, [pathname, hidden]);

  if (hidden) return null;

  return (
    <>
      <Script
        async
        src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1315269218347333"
        crossOrigin="anonymous"
        strategy="lazyOnload"
      />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
        <div className="rounded-lg overflow-hidden min-h-[50px]">
          <ins
            className="adsbygoogle"
            style={{ display: "block" }}
            data-ad-client="ca-pub-1315269218347333"
            data-ad-slot="3722838377"
            data-ad-format="auto"
            data-full-width-responsive="true"
          />
          {/* Fallback until Google approves the site */}
          {!adLoaded && (
            <div className="bg-slate-50 border border-dashed border-slate-200 rounded-lg p-2 text-center text-[10px] text-slate-300">
              Ad space — pending Google AdSense approval
            </div>
          )}
        </div>
      </div>
    </>
  );
}
