"use client";

import { usePathname } from "next/navigation";
import Script from "next/script";
import AdUnit from "./ad-unit";

const HIDDEN_PREFIXES = ["/admin", "/login", "/auth"];

/**
 * Footer ad banner — loads the AdSense script once (globally)
 * and renders a responsive banner before the footer.
 */
export default function AdBanner() {
  const pathname = usePathname();
  const hidden = HIDDEN_PREFIXES.some((p) => pathname.startsWith(p));

  if (hidden) return null;

  return (
    <>
      {/* Global AdSense script — loaded once, powers all AdUnit components */}
      <Script
        async
        src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1315269218347333"
        crossOrigin="anonymous"
        strategy="lazyOnload"
      />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
        <AdUnit slot="3722838377" format="horizontal" />
      </div>
    </>
  );
}
