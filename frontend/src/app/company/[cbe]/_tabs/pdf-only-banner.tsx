"use client";

import React from "react";
import { useTranslation } from "@/components/language-provider";

/* PDF-only banner — shown on every financials tab (P&L, Cash Flow, Balance
 * Sheet, Credit, Valuation) when the company files its annual accounts
 * only as PDF (m120 / m211 / m212 — small filers). No structured data is
 * available from NBB's JSON-XBRL API for these filings, so the tabs are
 * empty. Linking to the NBB consult page lets the user grab the PDF
 * directly. */
export function PdfOnlyBanner({ cbe }: { cbe: string }) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl rounded-lg border border-amber-200 bg-amber-50 p-4 text-left">
      <p className="text-sm font-semibold text-amber-800 mb-1">
        {t("company.pnl.pdfOnlyTitle")}
      </p>
      <p className="text-xs text-amber-700 mb-2">
        {t("company.pnl.pdfOnlyBody")}
      </p>
      <a
        href={`https://consult.cbso.nbb.be/consult-enterprise/${cbe}`}
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs font-medium text-amber-700 underline hover:text-amber-900"
      >
        {t("company.pnl.pdfOnlyLink")} {"\u2192"}
      </a>
    </div>
  );
}
