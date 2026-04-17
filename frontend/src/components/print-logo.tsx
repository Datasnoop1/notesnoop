"use client";

/**
 * PrintLogo — a client-only component that fetches the current site logo
 * (from /api/site-config) and renders it as an <img> that is hidden on
 * screen and only visible in print. Used in company headers so the PDF
 * export carries a branded letterhead aligned with the company name.
 *
 * Matches the same lookup Nav uses, so the print logo always tracks
 * whatever the admin has currently configured.
 */

import { useEffect, useState } from "react";

interface PrintLogoProps {
  heightPx?: number;
  className?: string;
}

export default function PrintLogo({ heightPx = 32, className = "" }: PrintLogoProps) {
  const [logoPath, setLogoPath] = useState<string>("/logos/dog-telescope.jpg");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/site-config")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.site_logo) setLogoPath(data.site_logo);
      })
      .catch(() => {
        // Fall back to default — the only cost is the wrong logo in print.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className={`hidden print:block shrink-0 ${className}`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={logoPath} alt="DataSnoop" style={{ height: `${heightPx}px` }} />
    </div>
  );
}
