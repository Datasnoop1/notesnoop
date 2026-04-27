import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sector Statistics",
  description: "Belgian company sector benchmarks: median revenue, EBITDA margins, FTE, leverage ratios, and distribution charts across 170K+ companies.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <section
        aria-label="About sector statistics"
        className="mt-12 border-t border-slate-200 bg-white"
      >
        <div className="mx-auto max-w-4xl px-4 py-8 text-sm text-slate-600 space-y-4">
          <h2 className="text-base font-semibold text-slate-900">
            Belgian sector benchmarks at a glance
          </h2>
          <p>
            DataSnoop&rsquo;s sector statistics page aggregates the financial
            filings of every Belgian company that deposits annual accounts at
            the National Bank (NBB), bucketed by NACE 2-digit sector and by
            province. Use it to size a market, compare sector medians, or
            spot which industries are growing.
          </p>
          <h3 className="text-sm font-semibold text-slate-900 mt-4">
            What the charts show
          </h3>
          <ul className="list-disc pl-5 space-y-1">
            <li>
              <strong>Sector breakdown</strong> &mdash; the top 20 NACE sectors
              by company count, coloured by median EBITDA margin so high- and
              low-profit industries pop visually.
            </li>
            <li>
              <strong>Company size distribution</strong> &mdash; how many
              companies fall in each revenue bracket (from sub-&euro;100K
              micro-enterprises up to billion-euro filers).
            </li>
            <li>
              <strong>EBITDA margin distribution</strong> &mdash; histogram of
              EBITDA margins across all filers with revenue above
              &euro;100,000, in 5% buckets.
            </li>
            <li>
              <strong>Multi-year evolution</strong> &mdash; aggregate revenue,
              EBITDA, and FTE trends over the last five fiscal years.
            </li>
          </ul>
          <h3 className="text-sm font-semibold text-slate-900 mt-4">
            Methodology
          </h3>
          <p>
            Aggregates use the latest NBB filing per company. Companies
            without filings (mostly newly incorporated entities and
            forms exempt from deposit) are excluded from the financial
            charts. Sector classification follows the official NACE 2008
            (NACE-Bel) taxonomy as published in the KBO open data set.
            For deeper sector analysis, jump to the{" "}
            <a href="/screener" className="text-brand hover:underline">screener</a>{" "}
            and filter by NACE code.
          </p>
        </div>
      </section>
    </>
  );
}
