import type { Metadata } from "next";

const API_BASE = process.env.API_URL_INTERNAL || process.env.NEXT_PUBLIC_API_URL || "";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ cbe: string }>;
}): Promise<Metadata> {
  const { cbe } = await params;
  const cleanCbe = cbe.replace(/\./g, "").padStart(10, "0");
  const fmtCbe = `${cleanCbe.slice(0, 4)}.${cleanCbe.slice(4, 7)}.${cleanCbe.slice(7)}`;

  // Fetch company name server-side for SEO meta tags
  let name = `Company ${fmtCbe}`;
  let description = `Financial profile, structure, and filings for Belgian company ${fmtCbe}.`;
  try {
    const res = await fetch(`${API_BASE}/api/companies/${cleanCbe}`, {
      next: { revalidate: 86400 },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.name) {
        name = data.name;
        description = `${name} (${fmtCbe}) — revenue, EBITDA, margins, board members, shareholders, and NBB filings.`;
      }
    }
  } catch {
    // Fallback to CBE-only title
  }

  // Canonical URL uses the bare 10-digit CBE so Google doesn't treat the
  // dotted variant (0400.378.485) as a duplicate of the undotted one.
  return {
    title: `${name} (${fmtCbe})`,
    description,
    alternates: {
      canonical: `https://datasnoop.be/company/${cleanCbe}`,
    },
    openGraph: {
      title: `${name} — Company Profile | DataSnoop`,
      description,
      url: `https://datasnoop.be/company/${cleanCbe}`,
    },
  };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
