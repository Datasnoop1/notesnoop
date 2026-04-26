"use client";

import Link from "next/link";
import { useTranslation } from "@/components/language-provider";

export default function FooterTranslated() {
  const { t } = useTranslation();

  return (
    <footer className="border-t border-slate-200 bg-white py-4 mt-auto ds-safe-bottom">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-xs text-slate-400 space-y-1.5">
        <div>{t("footer.dataSources")}</div>
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
          <a href="/use-cases.html" className="min-h-[36px] inline-flex items-center hover:text-slate-600 hover:underline active:text-slate-700">
            Use cases
          </a>
          <span aria-hidden className="text-slate-300">|</span>
          <Link href="/privacy" className="min-h-[36px] inline-flex items-center hover:text-slate-600 hover:underline active:text-slate-700">
            {t("footer.privacyPolicy")}
          </Link>
          <span aria-hidden className="text-slate-300">|</span>
          <Link href="/terms" className="min-h-[36px] inline-flex items-center hover:text-slate-600 hover:underline active:text-slate-700">
            {t("footer.termsOfUse")}
          </Link>
        </div>
      </div>
    </footer>
  );
}
