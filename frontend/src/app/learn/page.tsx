import Link from "next/link";
import { BookOpen, Clock } from "lucide-react";
import { LEARN_ARTICLES } from "@/lib/learn-articles";

export const metadata = {
  title: "Knowledge base - Datasnoop",
  description:
    "Practical guides to Belgian company data: enterprise numbers, annual accounts, EBITDA in Belgian GAAP, the Official Gazette, NACE classification, and shareholder structures.",
};

export default function LearnIndexPage() {
  return (
    <div className="max-w-3xl mx-auto py-8">
      <div className="flex items-center gap-3 mb-2">
        <BookOpen className="w-5 h-5 text-brand" />
        <h1 className="text-2xl font-bold text-slate-900">Knowledge base</h1>
      </div>
      <p className="text-sm text-slate-500 mb-8 max-w-prose">
        Working guides to the public sources behind Belgian company intelligence: the enterprise
        registry, the National Bank&apos;s annual accounts, the Belgian Official Gazette, and the
        sector classifications that tie them together. Written for analysts and researchers who
        need to use the data, not just describe it.
      </p>

      <div className="space-y-4">
        {LEARN_ARTICLES.map((article) => (
          <Link
            key={article.slug}
            href={`/learn/${article.slug}`}
            className="block rounded-lg border border-slate-200 bg-white p-5 hover:border-brand hover:shadow-[0_4px_18px_rgba(22,135,232,0.06)] transition-all"
          >
            <div className="flex items-center gap-2 mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <Clock className="w-3 h-3" />
              {article.readingMinutes} min read
            </div>
            <h2 className="text-base font-semibold text-slate-900 mb-1.5">{article.title}</h2>
            <p className="text-sm text-slate-600 leading-relaxed">{article.summary}</p>
          </Link>
        ))}
      </div>

      <div className="pt-8 border-t border-slate-200 mt-8">
        <Link href="/" className="text-sm text-brand hover:underline">
          &larr; Back to Datasnoop
        </Link>
      </div>
    </div>
  );
}
