import Link from "next/link";

export const metadata = {
  title: "Privacy Policy - Datasnoop",
  description: "Datasnoop privacy policy. How we collect, use, and protect your data.",
};

export default function PrivacyPolicyPage() {
  return (
    <div className="max-w-3xl mx-auto py-8">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Privacy Policy</h1>
      <p className="text-sm text-slate-500 mb-8">Last updated: 14 April 2026</p>

      <div className="prose prose-slate prose-sm max-w-none space-y-6">
        {/* --- 1 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">1. Controller</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            Datasnoop (&quot;we&quot;, &quot;us&quot;, &quot;our&quot;) is the data controller for personal data
            processed through this website. You can contact us at{" "}
            <a href="mailto:info@datasnoop.be" className="text-indigo-600 hover:underline">
              info@datasnoop.be
            </a>.
          </p>
        </section>

        {/* --- 2 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">2. Personal Data We Collect</h2>
          <p className="text-sm text-slate-600 leading-relaxed mb-2">
            We collect the minimum data necessary to operate the service:
          </p>
          <ul className="list-disc pl-5 text-sm text-slate-600 space-y-1">
            <li>
              <strong>Account data</strong> &mdash; your email address, provided when you create an account. We use
              this solely for authentication and account-related communications.
            </li>
            <li>
              <strong>Usage data</strong> &mdash; page views, search queries, and feature interactions. This data is
              collected in aggregate to understand how the service is used and to improve it. It is not linked to your
              identity.
            </li>
            <li>
              <strong>Cookies</strong> &mdash; we use essential cookies only, strictly for authentication and session
              management. We do not use tracking cookies, advertising cookies, or any third-party analytics cookies.
            </li>
          </ul>
        </section>

        {/* --- 3 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">3. Data Sources Displayed on This Platform</h2>
          <p className="text-sm text-slate-600 leading-relaxed mb-2">
            Datasnoop aggregates and displays information from the following publicly available government data sources:
          </p>
          <ul className="list-disc pl-5 text-sm text-slate-600 space-y-1">
            <li>
              <strong>KBO/BCE</strong> (Kruispuntbank van Ondernemingen / Banque-Carrefour des Entreprises) &mdash; the
              Belgian public registry of enterprises.
            </li>
            <li>
              <strong>NBB/BNB</strong> (Nationale Bank van Belgi&euml; / Banque Nationale de Belgique) &mdash; publicly
              filed annual accounts available through the Central Balance Sheet Office (CBSO).
            </li>
            <li>
              <strong>Belgisch Staatsblad / Moniteur belge</strong> &mdash; the Belgian Official Gazette, which
              publishes corporate appointments, modifications, and other legal acts.
            </li>
          </ul>
          <p className="text-sm text-slate-600 leading-relaxed mt-2">
            All of these data sources are publicly available. Datasnoop does not collect, scrape, or process private or
            non-public personal data from any source.
          </p>
        </section>

        {/* --- 4 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">4. How We Use Your Data</h2>
          <ul className="list-disc pl-5 text-sm text-slate-600 space-y-1">
            <li>To authenticate you and maintain your session.</li>
            <li>To provide and improve the service.</li>
            <li>To communicate with you about your account if necessary (e.g., password resets).</li>
          </ul>
          <p className="text-sm text-slate-600 leading-relaxed mt-2">
            We do <strong>not</strong> sell, rent, or share your personal data with third parties for marketing or any
            other commercial purpose.
          </p>
        </section>

        {/* --- 5 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">5. Cookies</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            We use only essential cookies required for authentication and session management. These cookies are strictly
            necessary for the functioning of the service and cannot be disabled without breaking core functionality. We
            do not use any tracking, analytics, or advertising cookies.
          </p>
        </section>

        {/* --- 6 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">6. Data Retention</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            Your account data (email address) is retained for as long as your account remains active. If you request
            deletion of your account, we will delete your personal data within a reasonable timeframe. Anonymised,
            aggregated usage data may be retained indefinitely as it cannot be linked to any individual.
          </p>
        </section>

        {/* --- 7 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">7. Your Rights Under GDPR</h2>
          <p className="text-sm text-slate-600 leading-relaxed mb-2">
            Under the General Data Protection Regulation (EU) 2016/679, you have the following rights regarding your
            personal data:
          </p>
          <ul className="list-disc pl-5 text-sm text-slate-600 space-y-1">
            <li><strong>Right of access</strong> &mdash; you may request a copy of the personal data we hold about you.</li>
            <li><strong>Right to rectification</strong> &mdash; you may request correction of inaccurate or incomplete data.</li>
            <li><strong>Right to erasure</strong> &mdash; you may request deletion of your personal data.</li>
            <li><strong>Right to data portability</strong> &mdash; you may request your data in a structured, commonly used format.</li>
            <li><strong>Right to object</strong> &mdash; you may object to the processing of your personal data.</li>
            <li><strong>Right to restriction of processing</strong> &mdash; you may request that we limit how we use your data.</li>
          </ul>
          <p className="text-sm text-slate-600 leading-relaxed mt-2">
            To exercise any of these rights, please contact us at{" "}
            <a href="mailto:info@datasnoop.be" className="text-indigo-600 hover:underline">
              info@datasnoop.be
            </a>. We will respond within 30 days.
          </p>
        </section>

        {/* --- 8 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">8. Account Deletion</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            You may request deletion of your account and all associated personal data at any time by emailing{" "}
            <a href="mailto:info@datasnoop.be" className="text-indigo-600 hover:underline">
              info@datasnoop.be
            </a>. Upon receiving your request, we will delete your account data within a reasonable timeframe and confirm
            deletion by email.
          </p>
        </section>

        {/* --- 9 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">9. Security</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            We take reasonable technical and organisational measures to protect your personal data. However, no method of
            electronic storage or transmission is 100% secure, and we cannot guarantee absolute security. You use the
            service at your own risk.
          </p>
        </section>

        {/* --- 10 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">10. Changes to This Policy</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            We may update this privacy policy from time to time. Any changes will be posted on this page with an updated
            &quot;Last updated&quot; date. Continued use of the service after any changes constitutes acceptance of the
            revised policy.
          </p>
        </section>

        {/* --- 11 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">11. Contact</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            For any questions or concerns about this privacy policy or our data practices, please contact us at{" "}
            <a href="mailto:info@datasnoop.be" className="text-indigo-600 hover:underline">
              info@datasnoop.be
            </a>.
          </p>
        </section>

        {/* Back link */}
        <div className="pt-4 border-t border-slate-200">
          <Link href="/" className="text-sm text-indigo-600 hover:underline">
            &larr; Back to Datasnoop
          </Link>
        </div>
      </div>
    </div>
  );
}
