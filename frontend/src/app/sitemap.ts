import type { MetadataRoute } from "next";

const BASE = "https://datasnoop.be";
// Sitemap runs server-side during SSR, so prefer the in-cluster API URL
// (API_URL_INTERNAL=http://backend:8000 inside Docker) and only fall back to
// the public one when not set. Using NEXT_PUBLIC_API_URL alone left this
// silently failing in prod, leaving Google with a static-only sitemap and
// 170k+ company profiles never indexed.
const API_BASE =
  process.env.API_URL_INTERNAL || process.env.NEXT_PUBLIC_API_URL || "";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  // Static pages
  const staticPages: MetadataRoute.Sitemap = [
    { url: BASE, lastModified: new Date(), changeFrequency: "daily", priority: 1.0 },
    { url: `${BASE}/search`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE}/screener`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE}/stats`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.8 },
    { url: `${BASE}/people`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.7 },
    { url: `${BASE}/compare`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.5 },
    { url: `${BASE}/guide`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.6 },
    { url: `${BASE}/privacy`, lastModified: new Date(), changeFrequency: "yearly", priority: 0.2 },
    { url: `${BASE}/terms`, lastModified: new Date(), changeFrequency: "yearly", priority: 0.2 },
  ];

  // Dynamic company pages — fetch all CBE numbers with financials
  let companyPages: MetadataRoute.Sitemap = [];
  if (!API_BASE) {
    console.error("[sitemap] API base URL not set (API_URL_INTERNAL / NEXT_PUBLIC_API_URL) — skipping dynamic company entries");
  } else {
    try {
      const res = await fetch(`${API_BASE}/api/sitemap/companies`, {
        next: { revalidate: 86400 },
      });
      if (!res.ok) {
        console.error(`[sitemap] ${API_BASE}/api/sitemap/companies returned ${res.status}`);
      } else {
        const cbes: string[] = await res.json();
        companyPages = cbes.map((cbe) => ({
          url: `${BASE}/company/${cbe}`,
          lastModified: new Date(),
          changeFrequency: "monthly" as const,
          priority: 0.6,
        }));
      }
    } catch (err) {
      console.error(`[sitemap] ${API_BASE}/api/sitemap/companies threw`, err);
    }
  }

  return [...staticPages, ...companyPages];
}
