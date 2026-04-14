import Link from "next/link";

export const metadata = {
  title: "Terms of Use - Data Peak",
  description: "Data Peak terms of use. Conditions governing your use of the platform.",
};

export default function TermsOfUsePage() {
  return (
    <div className="max-w-3xl mx-auto py-8">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Terms of Use</h1>
      <p className="text-sm text-slate-500 mb-8">Last updated: 14 April 2026</p>

      <div className="prose prose-slate prose-sm max-w-none space-y-6">
        {/* --- 1 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">1. Acceptance of Terms</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            By accessing or using Data Peak (&quot;the Service&quot;), you agree to be bound by these Terms of Use. If
            you do not agree to these terms, you must not access or use the Service. We reserve the right to modify
            these terms at any time without prior notice. Your continued use of the Service after any modifications
            constitutes acceptance of the updated terms.
          </p>
        </section>

        {/* --- 2 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">2. Description of Service</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            Data Peak is a platform that aggregates and displays publicly available data from Belgian government
            registries, including the KBO/BCE (Kruispuntbank van Ondernemingen), NBB/BNB (Nationale Bank van
            Belgi&euml;), and the Belgisch Staatsblad. The Service is provided for informational purposes only.
          </p>
        </section>

        {/* --- 3 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">3. No Warranty</h2>
          <p className="text-sm text-slate-600 leading-relaxed font-medium bg-amber-50 border border-amber-200 rounded-md px-4 py-3">
            THE SERVICE AND ALL DATA, CONTENT, AND MATERIALS AVAILABLE THROUGH IT ARE PROVIDED &quot;AS IS&quot; AND
            &quot;AS AVAILABLE&quot; WITHOUT ANY WARRANTY OF ANY KIND, WHETHER EXPRESS, IMPLIED, OR STATUTORY. DATA PEAK
            EXPRESSLY DISCLAIMS ALL WARRANTIES, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR
            A PARTICULAR PURPOSE, ACCURACY, COMPLETENESS, RELIABILITY, AVAILABILITY, TIMELINESS, AND NON-INFRINGEMENT.
            WE DO NOT WARRANT THAT THE DATA DISPLAYED IS ACCURATE, COMPLETE, CURRENT, OR ERROR-FREE.
          </p>
        </section>

        {/* --- 4 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">4. Limitation of Liability</h2>
          <p className="text-sm text-slate-600 leading-relaxed font-medium bg-amber-50 border border-amber-200 rounded-md px-4 py-3">
            TO THE FULLEST EXTENT PERMITTED BY APPLICABLE LAW, DATA PEAK, ITS OWNERS, OPERATORS, EMPLOYEES, AGENTS,
            AND AFFILIATES SHALL NOT BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR
            EXEMPLARY DAMAGES ARISING OUT OF OR IN CONNECTION WITH YOUR USE OF, OR INABILITY TO USE, THE SERVICE. THIS
            INCLUDES BUT IS NOT LIMITED TO DAMAGES FOR LOSS OF PROFITS, REVENUE, DATA, BUSINESS OPPORTUNITIES, OR
            GOODWILL, EVEN IF DATA PEAK HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. YOU ASSUME ALL RISK
            ASSOCIATED WITH YOUR USE OF THE SERVICE AND ANY DECISIONS MADE BASED ON THE DATA OR INFORMATION PROVIDED.
          </p>
        </section>

        {/* --- 5 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">5. Data Accuracy</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            The financial and corporate data displayed on Data Peak is sourced from publicly available government
            registries. While we strive to present this data faithfully, we do not guarantee its accuracy, completeness,
            or timeliness. Data may contain errors, delays, omissions, or discrepancies resulting from the source
            registries, data processing, or transmission. You should independently verify any data obtained through the
            Service before relying on it for any purpose, including but not limited to investment decisions, business
            transactions, due diligence, or legal proceedings.
          </p>
        </section>

        {/* --- 6 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">6. Account Termination</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            We reserve the right to suspend, restrict, or terminate your account and access to the Service at any time,
            for any reason or no reason, with or without notice. This includes but is not limited to violations of these
            Terms of Use, suspected fraudulent or abusive activity, or any other conduct that we, in our sole
            discretion, deem inappropriate. Upon termination, your right to use the Service ceases immediately. We shall
            not be liable to you or any third party for any termination of your access to the Service.
          </p>
        </section>

        {/* --- 7 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">7. Service Availability</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            We may modify, suspend, or discontinue the Service (or any part thereof) at any time, temporarily or
            permanently, with or without notice. We may also remove, alter, or restrict access to any data, content, or
            features at our sole discretion. We shall not be liable to you or any third party for any modification,
            suspension, or discontinuance of the Service.
          </p>
        </section>

        {/* --- 8 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">8. Intellectual Property</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            The underlying data displayed on the Service is sourced from public government registries and remains in the
            public domain. The platform design, user interface, software code, branding, and any original content
            created by Data Peak are the proprietary property of Data Peak and are protected by applicable intellectual
            property laws. You may not copy, reproduce, distribute, or create derivative works from the platform design
            or software without our express written permission.
          </p>
        </section>

        {/* --- 9 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">9. Acceptable Use</h2>
          <p className="text-sm text-slate-600 leading-relaxed mb-2">
            You agree not to:
          </p>
          <ul className="list-disc pl-5 text-sm text-slate-600 space-y-1">
            <li>Use automated tools, bots, scrapers, or crawlers to access, extract, or download data from the Service.</li>
            <li>Redistribute, republish, resell, or sublicense any data obtained from the Service without our express written permission.</li>
            <li>Use the data for commercial purposes without obtaining a commercial licence from Data Peak.</li>
            <li>Attempt to reverse-engineer, decompile, or disassemble any part of the Service.</li>
            <li>Interfere with or disrupt the Service or its infrastructure.</li>
            <li>Use the Service for any unlawful purpose or in violation of any applicable laws or regulations.</li>
            <li>Use personal data obtained from the Service for direct marketing purposes, in accordance with the KBO data licence restrictions.</li>
          </ul>
        </section>

        {/* --- 10 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">10. Indemnification</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            You agree to indemnify, defend, and hold harmless Data Peak, its owners, operators, employees, agents, and
            affiliates from and against any and all claims, liabilities, damages, losses, costs, and expenses (including
            reasonable legal fees) arising out of or in connection with: (a) your use of or access to the Service;
            (b) your violation of these Terms of Use; (c) your violation of any third-party rights; or (d) any decisions
            or actions taken based on data or information obtained through the Service.
          </p>
        </section>

        {/* --- 11 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">11. Governing Law and Jurisdiction</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            These Terms of Use shall be governed by and construed in accordance with the laws of Belgium, without regard
            to its conflict of law provisions. Any disputes arising out of or in connection with these Terms of Use or
            your use of the Service shall be subject to the exclusive jurisdiction of the courts of Belgium.
          </p>
        </section>

        {/* --- 12 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">12. Severability</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            If any provision of these Terms of Use is found to be invalid, illegal, or unenforceable by a court of
            competent jurisdiction, the remaining provisions shall continue in full force and effect.
          </p>
        </section>

        {/* --- 13 --- */}
        <section>
          <h2 className="text-lg font-semibold text-slate-800 mb-2">13. Contact</h2>
          <p className="text-sm text-slate-600 leading-relaxed">
            For any questions about these Terms of Use, please contact us at{" "}
            <a href="mailto:datapeak@invm.be" className="text-indigo-600 hover:underline">
              datapeak@invm.be
            </a>.
          </p>
        </section>

        {/* Back link */}
        <div className="pt-4 border-t border-slate-200">
          <Link href="/" className="text-sm text-indigo-600 hover:underline">
            &larr; Back to Data Peak
          </Link>
        </div>
      </div>
    </div>
  );
}
