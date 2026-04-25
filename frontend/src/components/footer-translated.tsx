"use client";

import Link from "next/link";
import { useTranslation } from "@/components/language-provider";

export default function FooterTranslated() {
  const { t } = useTranslation();

  return (
    <footer className="border-t border-slate-200 bg-white py-4 mt-auto">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-xs text-slate-400 space-y-1">
        <div>{t("footer.dataSources")}</div>
        <div className="flex items-center justify-center gap-1.5">
          <a href="/use-cases.html" className="hover:text-slate-600 hover:underline">
            Use cases
          </a>
          <span>|</span>
          <Link href="/privacy" className="hover:text-slate-600 hover:underline">
            {t("footer.privacyPolicy")}
          </Link>
          <span>|</span>
          <Link href="/terms" className="hover:text-slate-600 hover:underline">
            {t("footer.termsOfUse")}
          </Link>
        </div>
      </div>
    </footer>
  );
}
