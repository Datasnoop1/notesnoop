import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Compare Belgian Companies Side-by-Side",
  description: "Side-by-side comparison of P&L, balance sheet, and ratios for up to 5 Belgian companies. Powered by KBO + NBB filings.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <section
        aria-label="About company comparison"
        className="mt-12 border-t border-slate-200 bg-white"
      >
        <div className="mx-auto max-w-4xl px-4 py-8 text-sm text-slate-600 space-y-4">
          <h2 className="text-base font-semibold text-slate-900">
            Compare Belgian companies side-by-side
          </h2>
          <p>
            DataSnoop&rsquo;s comparison view puts up to five Belgian companies
            next to each other, line-by-line, across the income statement,
            balance sheet, and headline ratios. The data comes from the
            National Bank&rsquo;s annual XBRL filings, so every line item maps
            to its official Belgian-GAAP rubric (e.g. revenue = rubric 70,
            EBITDA = 9901 + 630).
          </p>
          <h3 className="text-sm font-semibold text-slate-900 mt-4">
            Typical use cases
          </h3>
          <ul className="list-disc pl-5 space-y-1">
            <li>
              <strong>Peer benchmarking</strong> &mdash; pick three competitors
              in the same sector and see which one converts revenue to EBITDA
              most efficiently.
            </li>
            <li>
              <strong>Acquisition shortlisting</strong> &mdash; line up a
              handful of M&amp;A targets on revenue growth, margin expansion,
              and leverage in one screen.
            </li>
            <li>
              <strong>Customer / supplier diligence</strong> &mdash; compare a
              prospective counterparty against its closest peers to gauge
              financial health.
            </li>
          </ul>
          <h3 className="text-sm font-semibold text-slate-900 mt-4">
            How to start
          </h3>
          <p>
            Search for a company in the box above, or load a saved{" "}
            <a href="/favourites" className="text-brand hover:underline">Project</a>{" "}
            to populate the comparison with one click. To browse a sector
            first and then compare the top performers, head to the{" "}
            <a href="/screener" className="text-brand hover:underline">screener</a>{" "}
            and pick &ldquo;Compare selected&rdquo; once you&rsquo;ve filtered
            the universe.
          </p>
        </div>
      </section>
    </>
  );
}
