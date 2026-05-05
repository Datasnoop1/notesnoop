import Link from "next/link";
import { notFound } from "next/navigation";
import { Clock } from "lucide-react";
import {
  LEARN_ARTICLES,
  getArticleBySlug,
  getRelatedArticles,
  ArticleBackLink,
} from "@/lib/learn-articles";

export function generateStaticParams() {
  return LEARN_ARTICLES.map((a) => ({ slug: a.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = getArticleBySlug(slug);
  if (!article) return { title: "Not found - Datasnoop" };
  return {
    title: `${article.title} - Datasnoop`,
    description: article.description,
  };
}

export default async function LearnArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = getArticleBySlug(slug);
  if (!article) notFound();

  const related = getRelatedArticles(article.slug, 3);

  return (
    <div className="max-w-3xl mx-auto py-8">
      <div className="mb-6">
        <Link
          href="/learn"
          className="text-xs text-slate-500 hover:text-brand hover:underline"
        >
          Knowledge base
        </Link>
      </div>

      <h1 className="text-2xl font-bold text-slate-900 mb-2 leading-tight">{article.title}</h1>
      <div className="flex items-center gap-2 mb-8 text-xs text-slate-500">
        <Clock className="w-3 h-3" />
        <span>{article.readingMinutes} min read</span>
        <span aria-hidden>·</span>
        <span>Last updated {article.publishedAt}</span>
      </div>

      <div className="prose prose-slate prose-sm max-w-none space-y-4">{article.body}</div>

      {related.length > 0 && (
        <div className="mt-12 pt-8 border-t border-slate-200">
          <h2 className="text-sm font-semibold text-slate-800 uppercase tracking-wide mb-4">
            Related articles
          </h2>
          <div className="space-y-3">
            {related.map((r) => (
              <Link
                key={r.slug}
                href={`/learn/${r.slug}`}
                className="block rounded-md border border-slate-200 bg-white p-3 hover:border-brand transition-colors"
              >
                <div className="text-sm font-semibold text-slate-900 mb-0.5">{r.title}</div>
                <div className="text-xs text-slate-500">{r.summary}</div>
              </Link>
            ))}
          </div>
        </div>
      )}

      <ArticleBackLink />
    </div>
  );
}
