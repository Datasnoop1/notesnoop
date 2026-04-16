import { CompanyPageClient } from "./company-page-client";
import type { CompanyDetail, FinancialsData, StructureData } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

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

  // Server-side parallel fetch — data available in initial HTML for SEO
  const [detail, financials, structure] = await Promise.all([
    fetchJson<CompanyDetail>(`${API_BASE}/api/companies/${cleanCbe}`),
    fetchJson<FinancialsData>(`${API_BASE}/api/companies/${cleanCbe}/financials`),
    fetchJson<StructureData>(`${API_BASE}/api/companies/${cleanCbe}/structure`),
  ]);

  return (
    <CompanyPageClient
      key={cleanCbe}
      cbe={cleanCbe}
      initialDetail={detail}
      initialFinancials={financials}
      initialStructure={structure}
    />
  );
}
