import Link from "next/link";

export const metadata = {
  title: "About Datasnoop - Belgian Company Intelligence",
  description:
    "Datasnoop is an independent Belgian company intelligence platform that combines KBO registry data, NBB annual accounts, and Belgian Official Gazette publications into one searchable workspace.",
};

export default function AboutPage() {
  return (
    <div className="max-w-3xl mx-auto py-8">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">About Datasnoop</h1>
      <p className="text-sm text-slate-500 mb-8">
        An independent Belgian company intelligence platform.
      </p>

      <div className="prose prose-slate prose-sm max-w-none space-y-6">
        {/* --- 1 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">What Datasnoop is</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            Datasnoop is a searchable database of Belgian companies. It brings together three public
            data sources &mdash; the Belgian enterprise registry (KBO/BCE), the National Bank of
            Belgium&apos;s central balance sheet office (NBB/BNB), and the Belgian Official Gazette
            (Staatsblad/Moniteur belge) &mdash; and adds an AI-assisted layer that turns raw filings
            into plain-language summaries, comparable financial metrics, and discovery tools such as
            semantic search and find-similar-companies.
          </p>
          <p className="text-sm text-slate-600 leading-relaxed mt-2">
            The product is aimed at people who need to understand Belgian companies quickly:
            corporate development teams, M&amp;A advisors, investors screening for deal flow,
            credit analysts, journalists, recruiters, and anyone doing due diligence. It is not a
            marketing list and it is not a credit-scoring service.
          </p>
        </section>

        {/* --- 2 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">Why we built it</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            The information that Datasnoop surfaces is, by law, public. Anyone with patience can
            assemble a picture of a Belgian company by visiting <em>kbopub.economie.fgov.be</em> for
            the registry, the National Bank&apos;s consultation portal for annual accounts, and the
            Official Gazette for legal publications. In practice, very few people have that
            patience. The data is fragmented across portals with different identifiers, different
            languages, different file formats, and different reporting templates. Comparing two
            companies side by side, or screening a sector against revenue and profitability
            thresholds, is impractical without aggregating the data first.
          </p>
          <p className="text-sm text-slate-600 leading-relaxed mt-2">
            Existing commercial products in the Belgian market solve that aggregation problem but
            tend to price themselves at thousands of euros per seat per year, which puts them out
            of reach of independent advisors, smaller PE shops, journalists, and academic
            researchers. Datasnoop&apos;s goal is to make the same kind of consolidated view
            available with far less friction. The site is currently free.
          </p>
        </section>

        {/* --- 3 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">Where the data comes from</h2>
          <p className="text-sm text-slate-600 leading-relaxed mb-2">
            Every fact you see on a Datasnoop company profile can be traced to one of three
            authoritative public sources:
          </p>
          <ul className="list-disc pl-5 text-sm text-slate-600 space-y-2">
            <li>
              <strong>KBO/BCE registry</strong> &mdash; the legal identity of the company:
              enterprise number, name, registered address, NACE activity codes, juridical form,
              incorporation date, status, branches. We pull the official KBO data every night
              and patch in the daily updates, so what you see is almost never more than a day
              behind the registry.
            </li>
            <li>
              <strong>NBB/BNB annual accounts</strong> &mdash; the financial statements that
              Belgian companies are required to file with the National Bank above certain size
              thresholds. The trick: companies file in three different formats (micro,
              abbreviated, full). We translate all of them into the same plain numbers &mdash;
              revenue, EBITDA, EBIT, profit, total assets, equity, net debt, working capital,
              headcount &mdash; so a corner shop and a national chain compare cleanly on one
              screen, without you doing the math. Since April 2022 the National Bank publishes
              filings as structured machine-readable data; older paper filings are imported
              where available.
            </li>
            <li>
              <strong>Belgisch Staatsblad / Moniteur belge</strong> &mdash; the Belgian Official
              Gazette captures the drama of corporate life: appointments and dismissals, capital
              increases and decreases, statutory amendments, address moves, mergers, demergers,
              dissolutions, bankruptcies. Every notice gets linked to the right company and the
              right people, so a profile shows the full administrative timeline rather than
              today&apos;s snapshot. One profile, one timeline, no PDFs.
            </li>
          </ul>
          <p className="text-sm text-slate-600 leading-relaxed mt-2">
            Everything on Datasnoop comes from official, public sources &mdash; the government,
            the National Bank, the Official Gazette. We don&apos;t scrape, we don&apos;t buy
            lists, and we don&apos;t infer personal data from anywhere private. What you see is
            what the law already makes public.
          </p>
        </section>

        {/* --- 4 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">What we add on top</h2>
          <p className="text-sm text-slate-600 leading-relaxed mb-2">
            Aggregation alone is not enough. Datasnoop adds four layers that turn the underlying
            data into something useful:
          </p>
          <ul className="list-disc pl-5 text-sm text-slate-600 space-y-2">
            <li>
              <strong>A normalised financial model.</strong> Belgian companies file in three
              different formats &mdash; micro, abbreviated, full &mdash; depending on size. We
              translate all three into the same plain metrics so a corner shop and a listed
              holding can sit side-by-side on the same screen.
            </li>
            <li>
              <strong>AI-generated summaries.</strong> For every company we write a short,
              factual narrative that explains what the company does and how its financials have
              evolved. Grounded in the company&apos;s own filings and, where available, its
              public website. The AI only writes what it can prove &mdash; if a fact isn&apos;t
              in the filings, the website, or a public news source, it doesn&apos;t make it
              into the summary. No hallucinations.
            </li>
            <li>
              <strong>Semantic search.</strong> A keyword search for &ldquo;industrial bakery&rdquo;
              misses companies that describe themselves as &ldquo;artisanal patisserie supplier to
              the food service channel.&rdquo; Semantic search retrieves both, because it operates
              on meaning rather than literal token matches. This is particularly useful in deal
              sourcing where you are looking for a category, not a specific name.
            </li>
            <li>
              <strong>A screener and a comparison tool.</strong> Filter by revenue, growth, margin,
              headcount, region, sector, distress signals, or recent NBB filing date; rank the
              shortlist; export it. Compare up to several companies side by side on the same
              metrics.
            </li>
          </ul>
        </section>

        {/* --- 5 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">Limitations and honesty</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            We try to be straightforward about what the data does and does not tell you. Belgian
            financial filings are accurate but they are not real-time: a company that filed its
            most recent set of accounts in mid-2025 will not show 2026 figures until the next
            filing window. NBB JSON data is only structured for filings since April 2022; older
            statements may be missing some line items. Companies in liquidation or under
            insolvency proceedings appear with their pre-event filings until the registrar updates
            their status. Sector classification through NACE codes is only as fine-grained as the
            company&apos;s own declaration to the registry, which is occasionally generic. AI
            summaries are useful starting points but should not replace reading the underlying
            documents before making any decision of consequence.
          </p>
        </section>

        {/* --- 6 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">How we operate</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            Datasnoop is run by a small independent team based in Belgium. The platform runs on
            European infrastructure, all data is processed in the EU, and the product is built
            to comply with the Belgian KBO open data licence and the General Data Protection
            Regulation (EU 2016/679).
          </p>
          <p className="text-sm text-slate-600 leading-relaxed mt-2">
            We&apos;re here for research, not spam. The KBO rules forbid using this data for
            cold outreach, and we wouldn&apos;t want to anyway: no marketing-list exports, no
            email scraping, no ad targeting built from registry contents. If a feature would
            cross that line, we don&apos;t ship it.
          </p>
        </section>

        {/* --- 6b: FAQ block, schema-marked for rich results -------- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">Common questions</h2>
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">Is Datasnoop free?</h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                Yes. The whole site is free to use today, including search, the screener, the
                comparison tool, AI summaries, and exports. No credit card, no trial timer, no
                hidden seat licences.
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">
                Do I need an account?
              </h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                You can search and read every Belgian company profile without logging in. An
                account only becomes useful when you want to save favourites, sync shortlists
                across devices, or export.
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">
                How current is the data?
              </h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                The KBO registry view is almost never more than 24 hours behind the official
                source &mdash; we pull the daily updates every night. Annual accounts (NBB) and
                Official Gazette publications appear on Datasnoop within hours of being
                published. Financials themselves are inherently lagged by the company&apos;s own
                filing schedule: a company that filed its 2025 accounts in mid-2026 won&apos;t
                show 2026 numbers until the next filing window.
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">
                Where exactly does the data come from?
              </h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                Three official Belgian public sources: the KBO/BCE enterprise registry, the
                National Bank of Belgium&apos;s Central Balance Sheet Office (NBB/BNB), and the
                Belgian Official Gazette (Belgisch Staatsblad / Moniteur belge). No third-party
                data brokers, no scraped websites, no purchased lists.
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">
                Can I use Datasnoop for due diligence or credit decisions?
              </h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                For triage, sourcing, qualification and preliminary analysis, yes &mdash; that
                is what most users do here. For binding commercial decisions (signing an LOI,
                granting credit, executing a transaction) you should still cross-check against
                the company&apos;s own filings, share register, and UBO extract. Datasnoop gets
                you to the conversation; it doesn&apos;t replace it.
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">
                What if I find an error in a company&apos;s data?
              </h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                Email us at{" "}
                <a href="mailto:info@datasnoop.be" className="text-brand hover:underline">
                  info@datasnoop.be
                </a>{" "}
                with the company&apos;s enterprise number and the issue. Presentation errors
                we can usually correct quickly; underlying registry errors we systematically
                forward to the relevant Belgian authority.
              </p>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-800 mb-1">
                Can I export data for my CRM or marketing list?
              </h3>
              <p className="text-sm text-slate-600 leading-relaxed">
                Exports for analysis and decision-making are fine &mdash; export a screener
                shortlist to CSV, a profile to Excel, a comparison to PDF. Bulk exports for
                cold-call lists or marketing campaigns are not allowed under the KBO open
                data licence and we don&apos;t support them by design.
              </p>
            </div>
          </div>
        </section>

        {/* JSON-LD FAQ schema for the 7 questions above —
            this gives Google's "People Also Ask" eligibility. */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "FAQPage",
              mainEntity: [
                {
                  "@type": "Question",
                  name: "Is Datasnoop free?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text:
                      "Yes. The whole site is free to use today, including search, the screener, the comparison tool, AI summaries, and exports. No credit card, no trial timer, no hidden seat licences.",
                  },
                },
                {
                  "@type": "Question",
                  name: "Do I need an account?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text:
                      "You can search and read every Belgian company profile without logging in. An account only becomes useful when you want to save favourites, sync shortlists across devices, or export.",
                  },
                },
                {
                  "@type": "Question",
                  name: "How current is the data?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text:
                      "The KBO registry view is almost never more than 24 hours behind the official source. Annual accounts (NBB) and Official Gazette publications appear on Datasnoop within hours of being published.",
                  },
                },
                {
                  "@type": "Question",
                  name: "Where exactly does the data come from?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text:
                      "Three official Belgian public sources: the KBO/BCE enterprise registry, the National Bank of Belgium's Central Balance Sheet Office (NBB/BNB), and the Belgian Official Gazette (Belgisch Staatsblad / Moniteur belge).",
                  },
                },
                {
                  "@type": "Question",
                  name: "Can I use Datasnoop for due diligence or credit decisions?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text:
                      "For triage, sourcing, qualification and preliminary analysis, yes. For binding commercial decisions you should still cross-check against the company's own filings, share register, and UBO extract.",
                  },
                },
                {
                  "@type": "Question",
                  name: "What if I find an error in a company's data?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text:
                      "Email info@datasnoop.be with the company's enterprise number and the issue. Presentation errors we can usually correct quickly; underlying registry errors we forward to the relevant Belgian authority.",
                  },
                },
                {
                  "@type": "Question",
                  name: "Can I export data for my CRM or marketing list?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text:
                      "Exports for analysis and decision-making are fine. Bulk exports for cold-call lists or marketing campaigns are not allowed under the KBO open data licence and we don't support them by design.",
                  },
                },
              ],
            }),
          }}
        />

        {/* --- 7 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">Contact and corrections</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            If you spot something that looks wrong &mdash; a misclassified sector, a mismatched
            address, a duplicated entity, a stale executive listing &mdash; please tell us. We can
            often correct presentation issues quickly and we systematically forward upstream
            registry errors to the relevant authority. Reach us at{" "}
            <a href="mailto:info@datasnoop.be" className="text-brand hover:underline">
              info@datasnoop.be
            </a>{" "}
            for editorial questions, data corrections, partnership enquiries, or press requests.
          </p>
          <p className="text-sm text-slate-600 leading-relaxed mt-2">
            For the legal small print, see our{" "}
            <Link href="/privacy" className="text-brand hover:underline">
              privacy policy
            </Link>{" "}
            and{" "}
            <Link href="/terms" className="text-brand hover:underline">
              terms of use
            </Link>
            . For a tour of the product itself, the{" "}
            <Link href="/guide" className="text-brand hover:underline">
              user guide
            </Link>{" "}
            walks through every feature.
          </p>
        </section>

        {/* Back link */}
        <div className="pt-4 border-t border-slate-200">
          <Link href="/" className="text-sm text-brand hover:underline">
            &larr; Back to Datasnoop
          </Link>
        </div>
      </div>
    </div>
  );
}
