"use client";

import Link from "next/link";
import AdUnit from "@/components/ad-unit";
import { useTranslation } from "@/components/language-provider";
import {
  Search,
  SlidersHorizontal,
  Building,
  BarChart,
  UserSearch,
  Sparkles,
  Heart,
  FileText,
  Users,
  Scale,
  Download,
  BookOpen,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface GuideSection {
  icon: LucideIcon;
  titleKey: string;
  bodyKey: string;
  href?: string;
}

const sections: GuideSection[] = [
  { icon: Search, titleKey: "guide.searchTitle", bodyKey: "guide.searchBody", href: "/search" },
  { icon: SlidersHorizontal, titleKey: "guide.screenerTitle", bodyKey: "guide.screenerBody", href: "/screener" },
  { icon: Building, titleKey: "guide.companyTitle", bodyKey: "guide.companyBody", href: "/company" },
  { icon: Sparkles, titleKey: "guide.aiTitle", bodyKey: "guide.aiBody" },
  { icon: Users, titleKey: "guide.similarTitle", bodyKey: "guide.similarBody" },
  { icon: FileText, titleKey: "guide.publicationsTitle", bodyKey: "guide.publicationsBody" },
  { icon: BarChart, titleKey: "guide.statsTitle", bodyKey: "guide.statsBody", href: "/stats" },
  { icon: UserSearch, titleKey: "guide.peopleTitle", bodyKey: "guide.peopleBody", href: "/people" },
  { icon: Heart, titleKey: "guide.favouritesTitle", bodyKey: "guide.favouritesBody", href: "/favourites" },
  { icon: Scale, titleKey: "guide.compareTitle", bodyKey: "guide.compareBody", href: "/compare" },
  { icon: Download, titleKey: "guide.exportTitle", bodyKey: "guide.exportBody" },
];

export default function GuidePage() {
  const { t } = useTranslation();

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div className="flex items-center gap-3 mb-2">
        <BookOpen className="w-5 h-5 text-brand" />
        <h1 className="text-lg font-bold text-slate-900">{t("guide.title")}</h1>
      </div>
      <p className="text-sm text-slate-500 -mt-4">
        {t("guide.intro")}
      </p>

      <div className="space-y-4">
        {sections.map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.titleKey} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center gap-2 mb-2">
                <Icon className="w-4 h-4 text-brand shrink-0" />
                <h2 className="text-sm font-semibold text-slate-900">
                  {s.href ? (
                    <Link href={s.href} className="hover:text-brand hover:underline transition-colors">
                      {t(s.titleKey)}
                    </Link>
                  ) : t(s.titleKey)}
                </h2>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed pl-6">{t(s.bodyKey)}</p>
            </div>
          );
        })}
      </div>

      {/* Ad placement: end of guide */}
      <AdUnit slot="3722838377" format="fluid" className="rounded-lg" />

      <div className="text-center py-4">
        <Link href="/" className="text-xs text-brand hover:text-[color:var(--brand-ink)] font-medium transition-colors">
          {t("guide.backToDashboard")}
        </Link>
      </div>
    </div>
  );
}
