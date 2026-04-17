import type { Metadata } from "next";
import Link from "next/link";
import { ValuationTab } from "@/app/company/[cbe]/_tabs/valuation-tab";
import type { CompanyDetail } from "@/app/company/[cbe]/types";
import { fmtCbe } from "@/lib/format";

const API_BASE = process.env.API_URL_INTERNAL || process.env.NEXT_PUBLIC_API_URL || "";

async function fetchDetail(cbe: string): Promise<CompanyDetail | null> {
  try {
    const res = await fetch(`${API_BASE}/api/companies/${cbe}`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ cbe: string }>;
}): Promise<Metadata> {
  const { cbe } = await params;
  const cleanCbe = cbe.replace(/\./g, "").padStart(10, "0");
  const detail = await fetchDetail(cleanCbe);
  const name = detail?.name || `Company ${fmtCbe(cleanCbe)}`;

  return {
    title: `${name} — Valuation (demo)`,
    description: `Indicative EV/EBITDA-based valuation for ${name}, using Vlerick M&A Monitor multiples.`,
    robots: { index: false, follow: false },
    openGraph: {
      title: `${name} — Valuation (demo) | DataSnoop`,
      description: `Indicative EV/EBITDA-based valuation using Vlerick M&A Monitor multiples.`,
    },
  };
}

export default async function ValuationDemoPage({
  params,
}: {
  params: Promise<{ cbe: string }>;
}) {
  const { cbe } = await params;
  const cleanCbe = cbe.replace(/\./g, "").padStart(10, "0");
  const detail = await fetchDetail(cleanCbe);

  const addressParts = [
    detail?.street,
    detail?.house_number,
    [detail?.zipcode, detail?.city].filter(Boolean).join(" "),
  ].filter(Boolean);
  const address = addressParts.length > 0 ? addressParts.join(", ") : null;

  return (
    <div className="mx-auto w-full max-w-[1000px] px-2 py-4 md:py-8">
      {/* Demo-mode label — hidden in print since the valuation tab has its
          own DataSnoop logo header for the PDF. */}
      <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-indigo-700 no-print">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-indigo-500" />
        Indicative valuation · Demo
      </div>

      {/* Company header — minimal, focused */}
      <div className="mb-6 border-b border-slate-200 pb-4">
        <h1 className="text-2xl font-semibold text-slate-900">
          {detail?.name || `Company ${fmtCbe(cleanCbe)}`}
        </h1>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
          <span className="font-mono">CBE {fmtCbe(cleanCbe)}</span>
          {address && <span>{address}</span>}
          {detail?.nace_code && (
            <span>
              NACE {detail.nace_code}
              {detail.nace_label && detail.nace_label !== detail.nace_code ? ` — ${detail.nace_label}` : ""}
            </span>
          )}
        </div>
      </div>

      {/* Valuation tab content */}
      <ValuationTab cbe={cleanCbe} companyName={detail?.name ?? null} />

      {/* Demo footer note */}
      <div className="mt-8 border-t border-slate-100 pt-4 text-center text-[11px] text-slate-400">
        This is a demo page. For the full company profile, structure, and filings, see{" "}
        <Link
          href={`/company/${cleanCbe}`}
          className="font-semibold text-indigo-500 hover:text-indigo-600"
        >
          the full company page on DataSnoop
        </Link>
        .
      </div>
    </div>
  );
}
