"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  BadgeCheck,
  Building2,
  Clock3,
  Database,
  ExternalLink,
  GitMerge,
  Loader2,
  ShieldCheck,
  UserRound,
} from "lucide-react";

import {
  getPersonV1,
  type PersonV1Link,
  type PersonV1Profile,
  type PersonV1SourceCount,
} from "@/lib/api";
import { fmtCbe } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";


function formatDate(value: string | null | undefined): string {
  if (!value) return "n/a";
  return value.slice(0, 10);
}


function confidenceLabel(value: number | null | undefined): string {
  if (value == null) return "n/a";
  return `${Math.round(value * 100)}%`;
}


function sourceLabel(source: string): string {
  if (source === "staatsblad_event") return "Staatsblad";
  if (source === "administrator") return "Administrator";
  if (source === "shareholder") return "Shareholder";
  if (source === "affiliation") return "Affiliation";
  return source;
}


function SourceStat({ stat }: { stat: PersonV1SourceCount }) {
  return (
    <Card className="rounded-md border-slate-200 shadow-none">
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-medium uppercase text-slate-400">
              {sourceLabel(stat.source_table)}
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">
              {stat.link_count.toLocaleString()}
            </div>
          </div>
          <Database className="h-5 w-5 text-slate-400" />
        </div>
        <div className="mt-3 text-xs text-slate-500">
          Confidence {confidenceLabel(stat.min_confidence)} to {confidenceLabel(stat.max_confidence)}
        </div>
      </CardContent>
    </Card>
  );
}


function LinkRow({ link }: { link: PersonV1Link }) {
  return (
    <div className="grid grid-cols-[1.2fr_1fr_120px_96px] items-center gap-3 border-b border-slate-100 px-4 py-3 text-sm last:border-b-0 max-lg:grid-cols-1">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="rounded-md">
            {sourceLabel(link.source_table)}
          </Badge>
          <span className="truncate font-medium text-slate-900">
            {link.name_as_written || "Unnamed"}
          </span>
        </div>
        <div className="mt-1 truncate font-mono text-xs text-slate-400">
          {link.source_field || "source"}[{link.source_mention_seq}] {link.source_pk}
        </div>
      </div>
      <div className="min-w-0">
        {link.enterprise_number ? (
          <Link
            href={`/company/${link.enterprise_number}`}
            className="inline-flex max-w-full items-center gap-1 font-medium text-brand hover:underline"
          >
            <Building2 className="h-4 w-4 shrink-0" />
            <span className="truncate">{link.company_name || fmtCbe(link.enterprise_number)}</span>
            <ExternalLink className="h-3.5 w-3.5 shrink-0" />
          </Link>
        ) : (
          <span className="text-slate-400">No company</span>
        )}
        {link.enterprise_number && (
          <div className="mt-1 font-mono text-xs text-slate-400">
            {fmtCbe(link.enterprise_number)}
          </div>
        )}
      </div>
      <div>
        <Badge className="rounded-md bg-emerald-50 text-emerald-700 hover:bg-emerald-50">
          {confidenceLabel(link.confidence)}
        </Badge>
      </div>
      <div className="text-xs text-slate-500">
        {link.link_kind}
      </div>
    </div>
  );
}


export default function PersonV1Page() {
  const params = useParams();
  const rawId = params?.id;
  const id = useMemo(() => {
    if (typeof rawId === "string") return rawId;
    if (Array.isArray(rawId) && rawId.length > 0) return rawId[0];
    return "";
  }, [rawId]);

  const [result, setResult] = useState<{
    id: string;
    profile: PersonV1Profile | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!id) return;
    let active = true;
    getPersonV1(id)
      .then((value) => {
        if (active) setResult({ id, profile: value, error: null });
      })
      .catch(() => {
        if (active) setResult({ id, profile: null, error: "Person profile unavailable." });
      });
    return () => {
      active = false;
    };
  }, [id]);

  const loading = !!id && result?.id !== id;
  const profile = result?.id === id ? result.profile : null;
  const error = result?.id === id ? result.error : null;

  if (loading) {
    return (
      <main className="mx-auto flex min-h-[60vh] max-w-6xl items-center justify-center px-6">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading person audit
        </div>
      </main>
    );
  }

  if (error || !profile) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-10">
        <Link href="/people" className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-brand">
          <ArrowLeft className="h-4 w-4" />
          People
        </Link>
        <div className="mt-10 rounded-md border border-slate-200 bg-white p-8">
          <div className="flex items-center gap-3 text-slate-900">
            <ShieldCheck className="h-5 w-5 text-slate-400" />
            <h1 className="text-xl font-semibold">Person profile unavailable.</h1>
          </div>
        </div>
      </main>
    );
  }

  const person = profile.person;
  const activeLinks = profile.links.length;

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <Link href="/people" className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-brand">
          <ArrowLeft className="h-4 w-4" />
          People
        </Link>
        <Badge variant="outline" className="rounded-md">
          <ShieldCheck className="mr-1 h-3.5 w-3.5" />
          Internal
        </Badge>
      </div>

      <section className="grid gap-6 lg:grid-cols-[1.4fr_0.8fr]">
        <div>
          <div className="flex flex-wrap items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-md bg-slate-900 text-white">
              <UserRound className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="break-words text-3xl font-semibold tracking-normal text-slate-950">
                {person.canonical_name}
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-500">
                <span className="font-mono">{person.person_id}</span>
                <span>{person.primary_postcode || "n/a"}</span>
                <span>{person.primary_city || "n/a"}</span>
              </div>
            </div>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <Card className="rounded-md border-slate-200 shadow-none">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-400">
                  <BadgeCheck className="h-4 w-4" />
                  Links
                </div>
                <div className="mt-2 text-2xl font-semibold text-slate-900">{activeLinks.toLocaleString()}</div>
              </CardContent>
            </Card>
            <Card className="rounded-md border-slate-200 shadow-none">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-400">
                  <Building2 className="h-4 w-4" />
                  Roles
                </div>
                <div className="mt-2 text-2xl font-semibold text-slate-900">
                  {(person.role_count || 0).toLocaleString()}
                </div>
              </CardContent>
            </Card>
            <Card className="rounded-md border-slate-200 shadow-none">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-400">
                  <Clock3 className="h-4 w-4" />
                  Seen
                </div>
                <div className="mt-2 text-sm font-semibold text-slate-900">
                  {formatDate(person.first_seen_date)} to {formatDate(person.last_seen_date)}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        <Card className="rounded-md border-slate-200 shadow-none">
          <CardContent className="space-y-3 p-5 text-sm">
            <div className="flex items-center gap-2 font-semibold text-slate-900">
              <GitMerge className="h-4 w-4 text-slate-400" />
              Cluster
            </div>
            <div className="grid grid-cols-[120px_1fr] gap-y-2 text-slate-600">
              <span className="text-slate-400">Status</span>
              <span>{person.status}</span>
              <span className="text-slate-400">Version</span>
              <span className="break-all font-mono text-xs">{person.cluster_version || "n/a"}</span>
              <span className="text-slate-400">Created</span>
              <span>{formatDate(person.created_at)}</span>
              <span className="text-slate-400">Public flag</span>
              <span>{profile.public_url_enabled ? "on" : "off"}</span>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="mt-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {profile.source_counts.map((stat) => (
          <SourceStat key={stat.source_table} stat={stat} />
        ))}
      </section>

      <section className="mt-8 rounded-md border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold uppercase text-slate-500">Source Links</h2>
          <span className="text-xs text-slate-400">{activeLinks.toLocaleString()} rows</span>
        </div>
        {profile.links.length > 0 ? (
          profile.links.map((link) => <LinkRow key={`${link.source_table}-${link.source_pk}-${link.source_mention_seq}`} link={link} />)
        ) : (
          <div className="px-4 py-8 text-sm text-slate-400">No source links.</div>
        )}
      </section>

      <section className="mt-8 rounded-md border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold uppercase text-slate-500">Merge History</h2>
        </div>
        {profile.merge_log.length > 0 ? (
          profile.merge_log.map((entry) => (
            <div key={entry.id} className="border-b border-slate-100 px-4 py-3 text-sm last:border-b-0">
              <div className="font-medium text-slate-900">{entry.op_kind}</div>
              <div className="mt-1 text-xs text-slate-500">
                {formatDate(entry.op_at)} by {entry.op_by || "system"}
              </div>
              {entry.reason && <div className="mt-2 text-slate-600">{entry.reason}</div>}
            </div>
          ))
        ) : (
          <div className="px-4 py-8 text-sm text-slate-400">No merge events.</div>
        )}
      </section>
    </main>
  );
}
