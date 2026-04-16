"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

const AD_CLIENT = "ca-pub-1315269218347333";
const HIDDEN_PREFIXES = ["/admin", "/login", "/auth", "/account"];

type AdFormat = "auto" | "horizontal" | "rectangle" | "fluid";

interface AdUnitProps {
  slot: string;
  format?: AdFormat;
  className?: string;
  responsive?: boolean;
}

/**
 * Reusable AdSense ad unit.
 *
 * Usage:
 *   <AdUnit slot="3722838377" />                          // auto responsive
 *   <AdUnit slot="3722838377" format="horizontal" />      // leaderboard
 *   <AdUnit slot="3722838377" format="rectangle" />       // sidebar rectangle
 *   <AdUnit slot="3722838377" format="fluid" />           // in-feed native
 */
export default function AdUnit({
  slot,
  format = "auto",
  className = "",
  responsive = true,
}: AdUnitProps) {
  const pathname = usePathname();
  const adRef = useRef<HTMLModElement>(null);
  const pushed = useRef(false);

  const hidden = HIDDEN_PREFIXES.some((p) => pathname.startsWith(p));

  useEffect(() => {
    if (hidden || pushed.current) return;
    try {
      // @ts-expect-error — adsbygoogle injected by script
      (window.adsbygoogle = window.adsbygoogle || []).push({});
      pushed.current = true;
    } catch {
      // Ad blocker or script not loaded
    }
  }, [hidden]);

  if (hidden) return null;

  return (
    <div className={`overflow-hidden min-h-[50px] ${className}`}>
      <ins
        ref={adRef}
        className="adsbygoogle"
        style={{ display: "block" }}
        data-ad-client={AD_CLIENT}
        data-ad-slot={slot}
        data-ad-format={format}
        data-full-width-responsive={responsive ? "true" : "false"}
      />
      {/* Placeholder until Google approves & fills the ad */}
      {!pushed.current && (
        <div className="bg-slate-50 border border-dashed border-slate-200 rounded-lg p-2 text-center text-[10px] text-slate-300">
          Ad space
        </div>
      )}
    </div>
  );
}
