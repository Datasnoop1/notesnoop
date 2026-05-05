import type { ReactNode } from "react";
import Link from "next/link";

export interface LearnArticle {
  slug: string;
  title: string;
  summary: string;
  description: string;
  publishedAt: string;
  readingMinutes: number;
  body: ReactNode;
}

const P = ({ children }: { children: ReactNode }) => (
  <p className="text-sm text-slate-600 leading-relaxed">{children}</p>
);

const H2 = ({ children }: { children: ReactNode }) => (
  <h2 className="text-lg font-semibold text-slate-800 mt-8 mb-2">{children}</h2>
);

const UL = ({ children }: { children: ReactNode }) => (
  <ul className="list-disc pl-5 text-sm text-slate-600 space-y-1.5">{children}</ul>
);

export const LEARN_ARTICLES: LearnArticle[] = [
  {
    slug: "belgian-enterprise-number",
    title: "Understanding the Belgian Enterprise Number (CBE / KBO)",
    summary:
      "The 10-digit identifier behind every Belgian company, where it comes from, and how to read it correctly.",
    description:
      "A practical guide to the Belgian Crossroads Bank for Enterprises identifier (CBE / KBO number): structure, formats, and how it links the public registry to the National Bank's annual accounts.",
    publishedAt: "2026-05-05",
    readingMinutes: 5,
    body: (
      <>
        <P>
          Every legal entity registered in Belgium &mdash; companies, non-profits, sole
          proprietorships, foreign branches, and self-employed professionals &mdash; carries a
          ten-digit identifier issued by the Crossroads Bank for Enterprises. The Dutch acronym is
          KBO (Kruispuntbank van Ondernemingen), the French is BCE (Banque-Carrefour des
          Entreprises), and the English form most often seen in international filings is CBE. All
          three refer to the same registry and the same number.
        </P>
        <H2>Why the number exists</H2>
        <P>
          Before 2003, Belgian companies were identified by separate VAT numbers, social-security
          numbers, RSZ numbers, and registry numbers depending on which administration was asking.
          The Crossroads Bank consolidated those identifiers into a single ten-digit code that
          every Belgian government body, the National Bank, the Official Gazette, and any party
          dealing with the company is expected to use. If you see a Belgian company today, it has
          a CBE number. The number is the canonical key that links a registry record, an annual
          account filing, and a Staatsblad publication to the same legal entity.
        </P>
        <H2>How the number is structured</H2>
        <P>
          The full identifier is ten digits, traditionally rendered with dots in the format{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">0XXX.XXX.XXX</code>. The
          leading zero is significant &mdash; older numbering schemes used a leading 0 for
          companies and a leading 1 for sole proprietors, although both ranges are now in active
          use. The last two digits form a modulo-97 check digit: take the first eight digits as a
          number, divide by 97, take the remainder, and the result is what the last two digits
          should equal. This makes typos easy to detect programmatically.
        </P>
        <H2>The formats you will encounter</H2>
        <UL>
          <li>
            <strong>With dots</strong> &mdash; <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">0123.456.789</code>{" "}
            is the human-readable form used in invoices, contracts, and the public KBO web
            interface.
          </li>
          <li>
            <strong>Bare digits</strong> &mdash; <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">0123456789</code>{" "}
            is the form required by the National Bank's CBSO API and most internal systems.
          </li>
          <li>
            <strong>VAT prefix</strong> &mdash; <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">BE0123456789</code>{" "}
            is the same number prefixed with the country code, used in cross-border invoicing.
          </li>
        </UL>
        <P>
          Datasnoop normalises all three forms. You can paste any of them into the search bar and
          the system will resolve to the same company.
        </P>
        <H2>What the number does and does not tell you</H2>
        <P>
          The CBE number identifies a legal entity, not a brand or trade name. A holding structure
          can have a single trading brand spread across half a dozen subsidiaries, each with its
          own number. Conversely, a single legal entity can operate under multiple trade names,
          each registered as a <em>vestigingseenheid</em> or <em>unit&eacute; d&apos;&eacute;tablissement</em>{" "}
          with its own auxiliary identifier. When you screen a market, build the shortlist on legal
          entities; when you map a brand, expect to traverse the tree.
        </P>
        <H2>Practical implications for research</H2>
        <P>
          Because every CBE number is unique, it is the only foolproof way to tell two Belgian
          companies apart &mdash; even when they share the same name. Two entirely separate
          businesses can share a name fragment, particularly in services where generic
          descriptors are common. When citing a company in a memo, always include the CBE number
          alongside the name. It removes any doubt about which legal entity you mean. Datasnoop
          shows the number on every search result, profile, and exported row precisely for this
          reason.
        </P>

        <H2>Common questions about the CBE number</H2>
        <P>
          <strong>Is the CBE number the same as the VAT number?</strong> Almost. The Belgian
          VAT identifier is the same ten-digit CBE number prefixed with{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">BE</code>. So{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">0123.456.789</code> on
          a Belgian invoice and{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">BE0123456789</code> on
          a cross-border invoice point at the same legal entity. Not every CBE-registered entity
          is VAT-liable (some non-profits, dormant entities), but every Belgian VAT number is
          built around a CBE number.
        </P>
        <P>
          <strong>Why do some numbers start with 0 and others with 1?</strong> The leading digit
          historically distinguished classic companies (0) from sole proprietors and other
          natural-person registrations (1). Both ranges are now in active use, and the difference
          is purely numerical &mdash; it does not signal anything about the entity&apos;s
          quality, status, or size.
        </P>
        <P>
          <strong>Do I need to type the dots when I search?</strong> No. Datasnoop accepts the
          number with dots (
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">0123.456.789</code>),
          without dots (
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">0123456789</code>),
          or with the VAT prefix (
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[12px]">BE0123456789</code>).
          Paste any of those forms into the search bar and the same company comes up.
        </P>
        <P>
          <strong>What happens to a CBE number when a company is dissolved?</strong> The number
          stays attached to the legal entity for as long as the registry keeps the record,
          which is decades after dissolution. You can still look up a long-defunct company on
          Datasnoop and see its final filings, its directors at the time of liquidation, and
          the Official Gazette notices that closed it. The number is never reassigned.
        </P>
        <P>
          <strong>Can I look up a CBE number for free?</strong> Yes. The Belgian government
          publishes the registry as open data, and Datasnoop&apos;s{" "}
          <Link href="/" className="text-brand hover:underline">
            free company search
          </Link>{" "}
          lets you query it directly. For deeper financial detail, the same CBE number unlocks
          the company&apos;s annual accounts; see{" "}
          <Link href="/learn/reading-belgian-annual-accounts" className="text-brand hover:underline">
            how to read a Belgian annual account
          </Link>{" "}
          for the next step.
        </P>
      </>
    ),
  },
  {
    slug: "reading-belgian-annual-accounts",
    title: "How to read a Belgian annual account",
    summary:
      "The three filing formats, what gets disclosed at each level, and how to compare a micro-format filer with a full-format filer.",
    description:
      "A working guide to Belgian GAAP annual accounts: micro, abbreviated, and full templates; what is disclosed at each tier; and the rubric codes that matter when comparing filings across companies of different sizes.",
    publishedAt: "2026-05-05",
    readingMinutes: 8,
    body: (
      <>
        <P>
          Companies above certain thresholds are required to deposit their annual accounts with the
          Central Balance Sheet Office of the National Bank of Belgium. Which template they file
          depends on their size, and the template determines how much detail you get. Reading a
          Belgian annual account properly means knowing which rubrics exist in your template,
          which exist only in larger ones, and which can be derived rather than read directly.
        </P>
        <H2>The three filing templates</H2>
        <UL>
          <li>
            <strong>Micro-format (modèle micro / micromodel)</strong> &mdash; available to very
            small companies under tight thresholds (max balance sheet around &euro;700k, max
            revenue around &euro;1.4m, max headcount 10 FTE on average). Discloses only headline
            balance-sheet and income-statement totals; no breakdown of revenue, cost of sales, or
            operating expenses.
          </li>
          <li>
            <strong>Abbreviated format (modèle abrégé / verkort schema)</strong> &mdash; for small
            companies that exceed the micro thresholds but stay below the full-format thresholds.
            Discloses an aggregated income statement (operating income vs. operating costs, with
            limited break-down) and a more detailed balance sheet.
          </li>
          <li>
            <strong>Full format (modèle complet / volledig schema)</strong> &mdash; mandatory for
            companies above the size thresholds and for all companies that have securities on a
            regulated market. Discloses revenue separately from other operating income, breaks
            down cost of sales, payroll, depreciation, and all balance-sheet line items in detail.
          </li>
        </UL>
        <H2>The rubric codes</H2>
        <P>
          Belgian GAAP uses numeric rubric codes to identify each line in the standardised
          template. The codes are stable across companies and across the three formats, although
          smaller templates only use a subset. A few that matter for almost every analysis:
        </P>
        <UL>
          <li>
            <strong>70</strong> &mdash; revenue (turnover from sales of goods and services).
            Disclosed in full and abbreviated; aggregated into <strong>70/74</strong> in the
            abbreviated format and absent from micro filings.
          </li>
          <li>
            <strong>9900</strong> &mdash; result of operations before non-operating items.
          </li>
          <li>
            <strong>9901</strong> &mdash; operating profit (also referred to as result of
            operations, equivalent to EBIT in international comparison).
          </li>
          <li>
            <strong>630</strong> &mdash; depreciation, amortisation, and write-downs. Adding this
            back to <strong>9901</strong> gives EBITDA. See{" "}
            <Link href="/learn/ebitda-belgian-gaap" className="text-brand hover:underline">
              EBITDA in Belgian GAAP
            </Link>{" "}
            for a worked example.
          </li>
          <li>
            <strong>10/15</strong> &mdash; total equity.
          </li>
          <li>
            <strong>10</strong> &mdash; capital subscribed.
          </li>
          <li>
            <strong>20/58</strong> &mdash; total assets.
          </li>
          <li>
            <strong>9087</strong> &mdash; average headcount in full-time equivalents.
          </li>
        </UL>
        <H2>Comparing filers across templates</H2>
        <P>
          The biggest practical issue when screening Belgian companies is that a micro-format
          filer simply does not disclose its revenue. You can see that a company exists, you can
          see its total balance sheet, you can see its operating profit, but you cannot see the
          top line. This is by design &mdash; the regulator deliberately reduced the disclosure
          burden for the smallest companies. When benchmarking, this means you have to choose
          between (a) restricting your screen to abbreviated and full filers (which excludes the
          long tail of small companies) or (b) treating revenue as missing for micro filers and
          benchmarking on metrics that are universally disclosed (operating profit, total
          assets, equity, headcount).
        </P>
        <H2>The April-2022 break</H2>
        <P>
          Since April 2022, the National Bank requires accounts to be deposited in XBRL, an
          XML-based machine-readable format. Anything filed before that date is available only as
          a PDF (or, for very old filings, as a scan) and must be re-keyed if you want structured
          data. In practice this means a company's most recent filings are perfectly comparable
          across the database, but historical comparisons before 2022 depend on whether the line
          you care about was extracted into the PDF tables. Datasnoop normalises both, but flags
          which figures come from XBRL and which are derived from PDF extraction.
        </P>
        <H2>What the accounts do not tell you</H2>
        <P>
          Belgian statutory accounts are filed at the legal-entity level, which means a holding
          structure with a Belgian topco, several Belgian opcos, and foreign subsidiaries will
          present a different picture depending on which entity you look at. The consolidated
          accounts are filed only by groups above the consolidation threshold, and even then the
          group perimeter follows Belgian law rather than IFRS. For an operational view of a
          group, the consolidated filing of the topco is the right starting point. For a credit
          view of a specific guarantor, the standalone filing of that entity is what matters.
        </P>
      </>
    ),
  },
  {
    slug: "ebitda-belgian-gaap",
    title: "EBITDA in Belgian GAAP: rubrics 9901 and 630",
    summary:
      "Why EBITDA is not a line item in a Belgian annual account, and the exact formula that produces a comparable EBITDA from the rubrics that are reported.",
    description:
      "EBITDA does not exist as a standalone line in Belgian GAAP, but it can be derived consistently from the operating profit (rubric 9901) and the depreciation and amortisation charge (rubric 630). This article explains the calculation, common mistakes, and how to handle the abbreviated and micro templates.",
    publishedAt: "2026-05-05",
    readingMinutes: 6,
    body: (
      <>
        <P>
          EBITDA &mdash; earnings before interest, tax, depreciation, and amortisation &mdash; is
          the most common operating-performance metric used in M&amp;A, leveraged finance, and
          benchmarking. It is also the most common source of confusion when reading a Belgian
          annual account, because EBITDA is not reported as a standalone line. You have to derive
          it.
        </P>
        <H2>The formula that works in Belgian GAAP</H2>
        <P>
          The reliable approach is to start from operating profit (rubric{" "}
          <strong>9901</strong>) and add back depreciation, amortisation, and write-downs (rubric{" "}
          <strong>630</strong>). That gives you EBITDA in the sense most analysts understand it:
          operating performance before non-cash charges, before financing costs, and before tax.
        </P>
        <P>
          <strong>EBITDA = Rubric 9901 + Rubric 630</strong>
        </P>
        <H2>Why this works</H2>
        <P>
          Rubric 9901 in the standardised Belgian template is defined as the result of the
          operating cycle: operating revenue minus operating costs, where operating costs already
          include depreciation, amortisation, and write-downs as a charge. Adding rubric 630 back
          neutralises that non-cash charge and brings you to the pre-D&amp;A operating result.
          Interest is recorded below the operating line in Belgian GAAP, so it is already
          excluded; the same is true for tax.
        </P>
        <H2>Common mistakes</H2>
        <UL>
          <li>
            <strong>Using rubric 9900 instead of 9901.</strong> Rubric 9900 is defined slightly
            differently in some templates and is an intermediate result, not the operating result
            proper. Always use 9901.
          </li>
          <li>
            <strong>Forgetting that 630 includes write-downs.</strong> Belgian rubric 630 covers
            depreciation on tangible fixed assets, amortisation on intangibles, <em>and</em>{" "}
            write-downs on tangible and intangible assets. If you back out only depreciation, you
            understate EBITDA in any year with a meaningful write-down.
          </li>
          <li>
            <strong>Mixing in financial provisions.</strong> Provisions for liabilities and
            charges (rubric 635/637) are also non-cash but they are not part of the standard
            EBITDA add-back. Including them produces a non-standard adjusted EBITDA that you
            should label as such.
          </li>
          <li>
            <strong>Reading EBITDA in the management commentary.</strong> Some companies disclose
            an EBITDA figure in their narrative or in a supplementary schedule; this is voluntary
            and may be calculated on a different basis (for instance, after backing out
            non-recurring charges). Stick to the rubric formula for cross-company comparability.
          </li>
        </UL>
        <H2>Handling smaller filers</H2>
        <P>
          Rubric 9901 and rubric 630 are both disclosed in the full and abbreviated templates, so
          EBITDA can be derived for the vast majority of Belgian filers. The micro template does
          report 9901 but not always 630 at the same level of granularity, which means EBITDA is
          available for some micro filers and not others. When the figure cannot be derived,
          Datasnoop flags it as missing rather than guessing.
        </P>
        <H2>From EBITDA to a multiple</H2>
        <P>
          Once you have a clean EBITDA, the natural next step is a valuation cross-check using a
          sector multiple. The{" "}
          <Link href="/screener" className="text-brand hover:underline">
            screener
          </Link>{" "}
          and{" "}
          <Link href="/stats" className="text-brand hover:underline">
            sector-statistics
          </Link>{" "}
          views in Datasnoop give you the inputs for this directly: median EBITDA in the relevant
          NACE sector, the implied multiple range from comparable transactions where available,
          and the company's own margin trajectory. None of this replaces a proper valuation
          exercise, but it usually tells you within five minutes whether the deal is in the realm
          of plausibility or whether somebody is asking far above the sector range.
        </P>

        <H2>A worked example: BV Patisserie Vandenberghe</H2>
        <P>
          To make the formula concrete, here is how it actually plays out on a typical Belgian
          filing. The figures below are from a hypothetical mid-sized filer but the structure
          mirrors the real abbreviated-format template. Every line maps to a rubric you can
          locate in the deposited annual account.
        </P>
        <table className="w-full text-[12px] sm:text-[13px] border border-slate-200 rounded-md overflow-hidden my-4">
          <thead className="bg-slate-50">
            <tr>
              <th className="text-left p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                Rubric
              </th>
              <th className="text-left p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                Line
              </th>
              <th className="text-right p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                Amount (EUR)
              </th>
            </tr>
          </thead>
          <tbody className="text-slate-600">
            <tr>
              <td className="p-2.5 border-b border-slate-100 font-mono">70/74</td>
              <td className="p-2.5 border-b border-slate-100">Operating income (incl. revenue)</td>
              <td className="p-2.5 border-b border-slate-100 text-right">8 420 000</td>
            </tr>
            <tr>
              <td className="p-2.5 border-b border-slate-100 font-mono">60/64</td>
              <td className="p-2.5 border-b border-slate-100">Operating costs</td>
              <td className="p-2.5 border-b border-slate-100 text-right">(7 940 000)</td>
            </tr>
            <tr className="bg-slate-50">
              <td className="p-2.5 border-b border-slate-100 font-mono">9901</td>
              <td className="p-2.5 border-b border-slate-100 font-semibold">
                Operating profit (= EBIT)
              </td>
              <td className="p-2.5 border-b border-slate-100 text-right font-semibold">
                480 000
              </td>
            </tr>
            <tr>
              <td className="p-2.5 border-b border-slate-100 font-mono">630</td>
              <td className="p-2.5 border-b border-slate-100">
                Depreciation, amortisation, write-downs (add back)
              </td>
              <td className="p-2.5 border-b border-slate-100 text-right">+ 320 000</td>
            </tr>
            <tr className="bg-emerald-50">
              <td className="p-2.5 font-mono font-semibold">EBITDA</td>
              <td className="p-2.5 font-bold">9901 + 630</td>
              <td className="p-2.5 text-right font-bold">800 000</td>
            </tr>
          </tbody>
        </table>
        <P>
          Translated: the bakery turned over &euro;8.4m, ran &euro;7.94m of operating costs and
          posted &euro;0.48m of operating profit (EBIT). Of those costs, &euro;0.32m was non-cash
          depreciation and amortisation. Adding that back gives an EBITDA of &euro;0.8m, which
          equals a 9.5% EBITDA margin. From there a sector cross-check is one click in the{" "}
          <Link href="/stats" className="text-brand hover:underline">
            sector-statistics view
          </Link>
          : if median EBITDA margin in NACE 10.71 (industrial bakery) sits at 7&ndash;9%, this
          filer is at the top of the band; if it sits at 12&ndash;15%, the company is
          underperforming relative to peers and probably has a structural cost issue worth
          investigating.
        </P>

        <H2>The three filing templates side-by-side</H2>
        <P>
          Whether you can derive EBITDA at all depends on which template the company filed.
          Belgian companies file in one of three formats based on their size; each discloses
          different levels of detail. This is why some Datasnoop profiles show a clean EBITDA
          line and others show a dash.
        </P>
        <table className="w-full text-[12px] sm:text-[13px] border border-slate-200 rounded-md overflow-hidden my-4">
          <thead className="bg-slate-50">
            <tr>
              <th className="text-left p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                Format
              </th>
              <th className="text-left p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                Who files it
              </th>
              <th className="text-left p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                Revenue disclosed?
              </th>
              <th className="text-left p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                Operating profit (9901)
              </th>
              <th className="text-left p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                D&amp;A (630)
              </th>
              <th className="text-left p-2.5 font-semibold text-slate-700 border-b border-slate-200">
                EBITDA derivable?
              </th>
            </tr>
          </thead>
          <tbody className="text-slate-600">
            <tr>
              <td className="p-2.5 border-b border-slate-100 font-semibold">Micro</td>
              <td className="p-2.5 border-b border-slate-100">
                Smallest companies (assets &lt; ~&euro;700k, revenue &lt; ~&euro;1.4m, &lt; 10 FTE)
              </td>
              <td className="p-2.5 border-b border-slate-100">No</td>
              <td className="p-2.5 border-b border-slate-100">Yes</td>
              <td className="p-2.5 border-b border-slate-100">Sometimes</td>
              <td className="p-2.5 border-b border-slate-100">Often missing</td>
            </tr>
            <tr>
              <td className="p-2.5 border-b border-slate-100 font-semibold">Abbreviated</td>
              <td className="p-2.5 border-b border-slate-100">
                Small companies above the micro thresholds
              </td>
              <td className="p-2.5 border-b border-slate-100">Aggregated (70/74)</td>
              <td className="p-2.5 border-b border-slate-100">Yes</td>
              <td className="p-2.5 border-b border-slate-100">Yes</td>
              <td className="p-2.5 border-b border-slate-100 font-semibold text-emerald-700">
                Yes
              </td>
            </tr>
            <tr>
              <td className="p-2.5 font-semibold">Full</td>
              <td className="p-2.5">Large companies and listed entities</td>
              <td className="p-2.5">Yes (separate revenue line, rubric 70)</td>
              <td className="p-2.5">Yes</td>
              <td className="p-2.5">Yes (broken down)</td>
              <td className="p-2.5 font-semibold text-emerald-700">Yes</td>
            </tr>
          </tbody>
        </table>
        <P>
          The takeaway: when you screen the Belgian market, expect to lose some micro-filers from
          a revenue-based sort. They&apos;re not hidden &mdash; they just don&apos;t disclose
          that line. For most operational analysis, restricting to abbreviated and full filers
          gives a clean comparable population. For a complete demographic view of a sector,
          include the micros and accept that revenue is incomplete.
        </P>
      </>
    ),
  },
  {
    slug: "belgian-official-gazette",
    title: "What the Belgian Official Gazette publishes",
    summary:
      "The Staatsblad / Moniteur belge is the legal record of corporate life in Belgium &mdash; appointments, mergers, dissolutions. Here is what each notice type means.",
    description:
      "A guide to the Belgian Official Gazette (Belgisch Staatsblad / Moniteur belge): what gets published, why, the timing of corporate notices, and how to read a typical filing.",
    publishedAt: "2026-05-05",
    readingMinutes: 6,
    body: (
      <>
        <P>
          The Belgisch Staatsblad &mdash; in French the Moniteur belge &mdash; is the official
          gazette of the Belgian state. It is where the federal government publishes new
          legislation, but for company researchers the more useful half is the section that
          publishes the legal acts of private companies and associations. Every appointment,
          dismissal, statutory amendment, capital change, merger, demerger, and dissolution that
          a Belgian company carries out has to be announced there.
        </P>
        <H2>Why publication is required</H2>
        <P>
          Belgian company law is built around the principle that third parties dealing with a
          company should be able to verify, from a public source, that the people signing on its
          behalf are actually authorised to do so, and that the legal structure they are
          describing actually exists. Publication in the Staatsblad is the mechanism. A board
          appointment that has not been published is, in many cases, not enforceable against
          third parties.
        </P>
        <H2>The most common notice types</H2>
        <UL>
          <li>
            <strong>Appointments and dismissals</strong> &mdash; new directors, departing
            directors, changes in mandate (managing director, chair, statutory auditor). Each
            entry typically names the individual, gives a date of effect, and references the
            general meeting or board decision behind the change.
          </li>
          <li>
            <strong>Statutory amendments</strong> &mdash; changes to the articles of association
            adopted by the general meeting. These can be technical (renaming, adapting to new
            company-law provisions) or substantive (capital increase, change of corporate object,
            transfer of registered office).
          </li>
          <li>
            <strong>Capital actions</strong> &mdash; capital increases against cash or
            contribution in kind, capital reductions, share buy-backs, share splits, and the
            issuance of new categories of shares.
          </li>
          <li>
            <strong>Mergers and demergers</strong> &mdash; legal merger of two or more entities,
            partial demerger, transfer of branch of activity. The notice typically references the
            merger plan, the date the operation takes legal effect, and the entities involved.
          </li>
          <li>
            <strong>Dissolutions and liquidations</strong> &mdash; voluntary dissolution decided
            by the shareholders, appointment of a liquidator, intermediate accounts during the
            liquidation, and the closing report.
          </li>
          <li>
            <strong>Insolvency events</strong> &mdash; bankruptcy declaration, court-appointed
            receiver, judicial reorganisation, and the closure of these proceedings.
          </li>
        </UL>
        <H2>Timing and what to expect</H2>
        <P>
          Publication is not instantaneous. A general-meeting decision typically reaches the
          Staatsblad two to six weeks later, sometimes longer for complex statutory amendments.
          This means that the Staatsblad is the authoritative record of what happened, but for
          very recent decisions the registry may already show a new director that has not yet been
          formally published, or vice versa. Cross-referencing the registry view and the
          publications timeline in Datasnoop usually resolves any apparent inconsistency.
        </P>
        <H2>Reading a notice</H2>
        <P>
          A typical Staatsblad notice is short &mdash; one or two paragraphs of legal language
          identifying the company by CBE number and registered office, naming the parties
          involved, and citing the underlying decision. The full PDF is available from the
          Staatsblad's own portal; Datasnoop links to the original for every notice in a profile's
          publications timeline. The AI summarisation feature on that timeline produces a
          chronological digest of the substantive events, which is useful when a company has
          accumulated fifteen or twenty years of routine notices and you want to find the points
          where ownership or control actually changed.
        </P>
      </>
    ),
  },
  {
    slug: "nace-codes-belgium",
    title: "NACE codes explained for Belgian deal sourcing",
    summary:
      "How the European NACE classification works, the Belgian extensions, and why a single sector usually requires a cluster of codes rather than just one.",
    description:
      "A practical guide to NACE-Bel sector codes for Belgian deal sourcing: structure, common pitfalls, primary versus secondary classification, and how to build an effective sector cluster.",
    publishedAt: "2026-05-05",
    readingMinutes: 6,
    body: (
      <>
        <P>
          NACE is the European statistical classification of economic activities. Every member
          state implements its own variant; Belgium uses NACE-Bel, which adds national-level
          subdivisions on top of the European base. Every Belgian company declares one or more
          NACE-Bel codes when it registers with the Crossroads Bank, and those codes are what you
          filter on when you build a sector screen.
        </P>
        <H2>The structure of a NACE-Bel code</H2>
        <P>
          A NACE-Bel code is up to five digits long. The first two digits identify the section
          (manufacturing, wholesale trade, transport, etc.); each additional digit narrows the
          activity. Code <strong>10</strong> is the manufacture of food products; code{" "}
          <strong>10.71</strong> is the manufacture of bread, fresh pastry goods, and cakes; and
          the Belgian extension carries it further, distinguishing industrial bakeries from
          artisanal producers under <strong>10.71.1</strong> and <strong>10.71.2</strong>{" "}
          respectively.
        </P>
        <H2>Primary versus secondary activities</H2>
        <P>
          A company can declare any number of NACE codes, but exactly one of them is its primary
          activity for statistical purposes. This is supposed to be the activity that generates
          the most revenue. In practice, declarations are not always kept up to date: a company
          that started as a courier service and now derives most of its revenue from warehousing
          may still appear under the courier code. When you build a sector screen, expect to find
          some companies that should not be there and to miss some companies that should.
        </P>
        <H2>Why one code is rarely enough</H2>
        <P>
          Most useful sector definitions span multiple NACE codes. Construction, for instance,
          fragments across general construction, finishing trades, civil engineering, and
          specialised activities like roofing and insulation. Logistics splits between freight
          forwarding, storage and warehousing, support activities for transport, and the various
          modes of transport themselves. A coherent sector view typically requires you to assemble
          a cluster of codes rather than relying on a single one. The Datasnoop screener accepts
          multiple NACE codes as an OR filter precisely for this reason.
        </P>
        <H2>Common pitfalls</H2>
        <UL>
          <li>
            <strong>Holding companies.</strong> A pure holding company declares NACE code{" "}
            <strong>64.20</strong> (activities of holding companies), which says nothing about
            what the underlying group does. Filtering only on operating codes therefore misses the
            holding entities of relevant groups; filtering only on holding codes misses the
            operating subsidiaries.
          </li>
          <li>
            <strong>Dormant or shell entities.</strong> Some entities declare a NACE code that
            reflects an intention rather than an activity. They show up in the sector but have no
            financials. Combining a NACE filter with a minimum revenue or headcount threshold
            removes most of these.
          </li>
          <li>
            <strong>Service vs. manufacturing.</strong> A company that designs and installs a
            product but contracts out the manufacturing may classify itself under either side.
            For a buy-side search, this means you should sketch the value chain first and then
            list the codes that touch it, rather than starting from a single &ldquo;obvious&rdquo;
            code.
          </li>
        </UL>
        <H2>Beyond the code: semantic search</H2>
        <P>
          The limitations of NACE classification are exactly the case for semantic search. A
          search for &ldquo;industrial bakery supplying retail and food service&rdquo; will pick
          up companies that match the description in their own self-presentation, regardless of
          whether they declared themselves under bakery or under wholesale food trade. NACE
          filters and semantic search are complementary: NACE gives you a clean, repeatable
          baseline; semantic search catches the entities that drift out of their declared code
          but actually belong in the sector.
        </P>
      </>
    ),
  },
  {
    slug: "belgian-shareholder-structures",
    title: "Reading Belgian shareholder structures from the registry",
    summary:
      "What the public registry tells you about ownership, what it does not, and how to triangulate a control picture from filings and the Official Gazette.",
    description:
      "How to reconstruct the ownership structure of a Belgian company from public sources: registry data, annual accounts, and the Belgian Official Gazette. What the public record discloses, what it omits, and where the limits sit.",
    publishedAt: "2026-05-05",
    readingMinutes: 7,
    body: (
      <>
        <P>
          One of the most common questions in deal sourcing and due diligence is also one of the
          hardest to answer cleanly from Belgian public sources: who actually owns this company?
          The Belgian regime is a hybrid of public registry data and a separate UBO register, and
          understanding what each one discloses is the difference between a confident answer and a
          guess.
        </P>
        <H2>What the KBO registry discloses</H2>
        <P>
          The KBO/BCE registry shows the legal entity, its registered office, its juridical form,
          its directors, and its functions (managing director, chair, statutory auditor,
          permanent representative for a corporate director, and so on). It does <em>not</em>{" "}
          disclose the shareholders. Knowing that someone is a director does not tell you they
          own the company; knowing who owns the company is not, in general, a question the public
          registry is built to answer.
        </P>
        <H2>What the annual accounts reveal</H2>
        <P>
          Companies that hold significant participations in other companies must disclose those
          holdings in a dedicated section of the annual accounts (typically as a list of
          subsidiaries with a CBE number, a percentage held, and a book value). This means the
          annual accounts of a parent company tell you what it owns, but the annual accounts of
          a subsidiary do not, in general, tell you who owns it. To reconstruct an ownership tree
          from the public record, you usually have to walk it from the top down: start from the
          presumed parent, read its participations, and check that each declared subsidiary
          confirms the link in its own filings.
        </P>
        <H2>What the Official Gazette adds</H2>
        <P>
          Capital actions are published in the Staatsblad: capital increases against cash or
          contribution in kind, capital reductions, share buy-backs, the issuance of new share
          classes, and statutory amendments that change the share register's structure. These
          notices identify the parties who subscribe to a capital increase or who tender shares
          in a buy-back. For a leveraged transaction, the relevant Staatsblad filings often
          include the contribution-in-kind notices that document who put what into the structure.
          Reading the publications timeline in chronological order is usually the fastest way to
          spot the points where control actually changed.
        </P>
        <H2>The UBO register</H2>
        <P>
          Belgium maintains a separate Ultimate Beneficial Owner register, accessible only with a
          legitimate-interest justification. The UBO register identifies the natural persons who
          ultimately control a Belgian entity above a 25% threshold or through other means. It is
          not freely public &mdash; an external researcher cannot look it up the way the KBO can
          be looked up. For a transaction, the target itself can extract its own UBO entry and
          share it; for a cold sourcing exercise, the public record is what you have, and the
          public record stops at the legal-entity level.
        </P>
        <H2>Triangulating a control picture</H2>
        <UL>
          <li>
            <strong>Start with the directors.</strong> The list of directors is public. If a
            single individual sits on the board of the Belgian company and on the board of the
            holding entity above it, that is a strong signal of effective control.
          </li>
          <li>
            <strong>Walk the parent's participations.</strong> The Datasnoop structure tab shows
            the parent-subsidiary relationships that are disclosed in annual accounts. The shape
            of the tree usually tells you which entity holds the operating value and which is a
            financing vehicle.
          </li>
          <li>
            <strong>Read capital actions.</strong> Each capital increase or share buy-back in the
            Staatsblad names the parties involved. A sequence of capital actions often discloses
            the timeline of an MBO or a sponsor entry that the registry alone would not reveal.
          </li>
          <li>
            <strong>Cross-check against people search.</strong> If the same handful of natural
            persons appears as director across a cluster of legally separate entities, that
            cluster is probably a single economic group regardless of how the formal structure is
            drawn.
          </li>
        </UL>
        <H2>Limits and honesty</H2>
        <P>
          The public record is good enough for sourcing, qualification, and most preliminary
          analysis. It is not good enough for a definitive ownership statement. For any decision
          of consequence &mdash; signing an LOI, taking a position in a competitive auction,
          structuring a transaction &mdash; you will need the share register, the UBO extract,
          and any shareholder agreements, all of which sit outside the public domain. Datasnoop
          gets you to the point where the right next conversation with the target becomes
          feasible; it does not, and cannot, replace that conversation.
        </P>
      </>
    ),
  },
];

export function getArticleBySlug(slug: string): LearnArticle | undefined {
  return LEARN_ARTICLES.find((a) => a.slug === slug);
}

export function getRelatedArticles(currentSlug: string, count = 3): LearnArticle[] {
  return LEARN_ARTICLES.filter((a) => a.slug !== currentSlug).slice(0, count);
}

export function ArticleBackLink() {
  return (
    <div className="pt-4 border-t border-slate-200 mt-8">
      <Link href="/learn" className="text-sm text-brand hover:underline">
        &larr; Back to the knowledge base
      </Link>
    </div>
  );
}
