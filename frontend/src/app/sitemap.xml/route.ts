import { NextResponse } from "next/server";

// Next.js 16 metadata routes (sitemap.ts) aggressively pre-render at build
// time and their ISR cache hides my force-dynamic export. At build time
// the backend container isn't reachable, so the cached output is only
// static pages and Google never sees the 170k company profiles.
//
// This Route Handler replaces the metadata route: explicit runtime
// rendering, explicit no-store fetch, explicit XML serialisation. The
// URL stays at /sitemap.xml.
export const dynamic = "force-dynamic";
export const revalidate = 0;

const BASE = "https://datasnoop.be";
const API_BASE =
  process.env.API_URL_INTERNAL || process.env.NEXT_PUBLIC_API_URL || "";

interface UrlEntry {
  loc: string;
  lastmod: string;
  changefreq: "daily" | "weekly" | "monthly" | "yearly";
  priority: number;
}

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/'/g, "&apos;")
    .replace(/"/g, "&quot;");
}

function toXml(entries: UrlEntry[]): string {
  const rows = entries
    .map(
      (e) =>
        `  <url>\n    <loc>${esc(e.loc)}</loc>\n    <lastmod>${e.lastmod}</lastmod>\n    <changefreq>${e.changefreq}</changefreq>\n    <priority>${e.priority.toFixed(1)}</priority>\n  </url>`,
    )
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${rows}\n</urlset>\n`;
}

export async function GET() {
  const now = new Date().toISOString();
  const staticPages: UrlEntry[] = [
    { loc: BASE, lastmod: now, changefreq: "daily", priority: 1.0 },
    { loc: `${BASE}/search`, lastmod: now, changefreq: "weekly", priority: 0.9 },
    { loc: `${BASE}/screener`, lastmod: now, changefreq: "weekly", priority: 0.9 },
    { loc: `${BASE}/stats`, lastmod: now, changefreq: "weekly", priority: 0.8 },
    { loc: `${BASE}/people`, lastmod: now, changefreq: "weekly", priority: 0.7 },
    { loc: `${BASE}/compare`, lastmod: now, changefreq: "monthly", priority: 0.5 },
    { loc: `${BASE}/guide`, lastmod: now, changefreq: "monthly", priority: 0.6 },
    { loc: `${BASE}/privacy`, lastmod: now, changefreq: "yearly", priority: 0.2 },
    { loc: `${BASE}/terms`, lastmod: now, changefreq: "yearly", priority: 0.2 },
  ];

  let companyPages: UrlEntry[] = [];
  if (!API_BASE) {
    console.error(
      "[sitemap] API base URL not set (API_URL_INTERNAL / NEXT_PUBLIC_API_URL) \u2014 skipping dynamic company entries",
    );
  } else {
    try {
      const res = await fetch(`${API_BASE}/api/sitemap/companies`, {
        cache: "no-store",
      });
      if (!res.ok) {
        console.error(
          `[sitemap] ${API_BASE}/api/sitemap/companies returned ${res.status}`,
        );
      } else {
        const cbes = (await res.json()) as string[];
        companyPages = cbes.map((cbe) => ({
          loc: `${BASE}/company/${cbe}`,
          lastmod: now,
          changefreq: "monthly",
          priority: 0.6,
        }));
      }
    } catch (err) {
      console.error(
        `[sitemap] ${API_BASE}/api/sitemap/companies threw`,
        err,
      );
    }
  }

  const xml = toXml([...staticPages, ...companyPages]);
  return new NextResponse(xml, {
    status: 200,
    headers: {
      "content-type": "application/xml; charset=utf-8",
      "cache-control": "public, max-age=3600, stale-while-revalidate=86400",
    },
  });
}
