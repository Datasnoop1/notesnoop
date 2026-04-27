import { CompanyPageClient } from "./company-page-client";
import type { CompanyDetail, StructureData } from "./types";

// Server components need an absolute URL for fetch — use internal Docker URL if available
const API_BASE = process.env.API_URL_INTERNAL || process.env.NEXT_PUBLIC_API_URL || "";

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function CompanyDetailPage({
  params,
}: {
  params: Promise<{ cbe: string }>;
}) {
  const { cbe } = await params;
  const cleanCbe = cbe.replace(/\./g, "").padStart(10, "0");

  // Server-side parallel fetch — detail + structure in initial HTML for SEO.
  // Financials are intentionally excluded here: they can be slow (5-15 s for
  // large companies) and blocking them would delay above-the-fold render for
  // every visitor. FinancialsSection (a client component) fetches them after
  // mount with a 15 s deadline and a retry fallback.
  const [detail, structure] = await Promise.all([
    fetchJson<CompanyDetail>(`${API_BASE}/api/companies/${cleanCbe}`),
    fetchJson<StructureData>(`${API_BASE}/api/companies/${cleanCbe}/structure`),
  ]);

  return (
    <CompanyPageClient
      key={cleanCbe}
      cbe={cleanCbe}
      initialDetail={detail}
      initialFinancials={null}
      initialStructure={structure}
    />
  );
}
