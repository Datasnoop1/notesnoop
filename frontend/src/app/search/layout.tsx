import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Search Companies & People",
  description: "Search Belgian companies by name, CBE number, or keyword. Find administrators and shareholders across 170K+ registered enterprises.",
};

// Server-rendered helper content sits below the interactive client UI so
// Googlebot's first-paint scan sees substantive text (the client surface
// is "use client" and renders a thin shell until JS hydrates — Search
// Console flagged it as discovered-but-not-indexed in 2026-04 because of
// this).
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <section
        aria-label="About DataSnoop search"
        className="mt-12 border-t border-slate-200 bg-white"
      >
        <div className="mx-auto max-w-4xl px-4 py-8 text-sm text-slate-600 space-y-4">
          <h2 className="text-base font-semibold text-slate-900">
            Search across 170,000+ Belgian companies
          </h2>
          <p>
            DataSnoop combines the public KBO (Kruispuntbank van Ondernemingen)
            registry with the National Bank of Belgium&rsquo;s annual filings,
            giving a single search surface across every officially registered
            enterprise in Belgium and the people behind them.
          </p>
          <h3 className="text-sm font-semibold text-slate-900 mt-4">
            What you can search for
          </h3>
          <ul className="list-disc pl-5 space-y-1">
            <li>
              <strong>Companies</strong> &mdash; by registered name, trade name,
              CBE number (e.g. <code>0473.416.418</code>), or VAT number
              (e.g. <code>BE0473416418</code>). Legal-form suffixes such as
              BV, NV, SA, SRL, ASBL, VZW are ignored automatically.
            </li>
            <li>
              <strong>Directors and shareholders</strong> &mdash; by full or
              partial name. Results merge KBO data, NBB filings, and
              Belgian Gazette appointments.
            </li>
            <li>
              <strong>Belgian Gazette events</strong> &mdash; recent
              appointments, resignations, dissolutions, and capital changes.
            </li>
          </ul>
          <h3 className="text-sm font-semibold text-slate-900 mt-4">
            Refining results
          </h3>
          <p>
            Narrow company results by <strong>postcode</strong>,
            <strong> municipality</strong>, or <strong>street</strong> with the
            location filters above. Click any company to open its full
            financial profile (P&amp;L, balance sheet, ratios, board, and
            ownership). For sector-level browsing, use the{" "}
            <a href="/screener" className="text-brand hover:underline">screener</a>{" "}
            instead.
          </p>
        </div>
      </section>
    </>
  );
}
