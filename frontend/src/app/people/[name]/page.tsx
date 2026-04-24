"use client";

import { useEffect, useState, useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getPersonConnections,
  type PersonProfile,
  type PersonAdminRole,
  type PersonShareholding,
} from "@/lib/api";
import { fmtCbe, fmtEur } from "@/lib/format";
import { Card, CardContent } from "@/components/ui/card";
import { useTranslation } from "@/components/language-provider";
import {
  ArrowLeft,
  Loader2,
  Building,
  Briefcase,
  Users,
  Calendar,
  ExternalLink,
} from "lucide-react";

/* Person profile page (#19) — roles, companies involved in, timeline of
 * involvement. Pulls from /api/people/{name}/connections which unions the
 * NBB annual-filing snapshot with the fresher Staatsblad event log.
 *
 * Timeline view groups every admin mandate by year-of-start so the
 * operator sees when a person joined / left which boards across their
 * career.
 */

function formatYear(date: string | null | undefined): string {
  if (!date || date.length < 4) return "—";
  return date.slice(0, 4);
}

function sourceBadge(source: string | null) {
  if (source === "staatsblad") {
    return (
      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100">
        fresh
      </span>
    );
  }
  if (source === "merged") {
    return (
      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100">
        merged
      </span>
    );
  }
  return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-slate-50 text-slate-500 border border-slate-100">
      NBB
    </span>
  );
}

function AdminRoleRow({ role }: { role: PersonAdminRole }) {
  const ended = !!role.mandate_end;
  return (
    <div className={`px-3 py-2 border-b border-slate-50 last:border-0 flex items-center gap-3 ${ended ? "opacity-70" : ""}`}>
      <div className="min-w-0 flex-1">
        <Link
          href={`/company/${role.enterprise_number}`}
          className="text-sm font-medium text-indigo-600 hover:underline truncate block"
        >
          {role.company_name || fmtCbe(role.enterprise_number)}
        </Link>
        <div className="flex items-center gap-2 text-[11px] text-slate-400 mt-0.5">
          <span className="font-mono">{fmtCbe(role.enterprise_number)}</span>
          <span>•</span>
          <span>{role.role_label || role.role || "Administrator"}</span>
          {ended && (
            <>
              <span>•</span>
              <span className="text-rose-400">ended</span>
            </>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {role.revenue != null && (
          <span className="text-[11px] font-mono text-slate-500 w-24 text-right">
            {fmtEur(role.revenue)}
          </span>
        )}
        <span className="text-[11px] text-slate-400 w-28 text-right">
          {role.mandate_start
            ? ended
              ? `${formatYear(role.mandate_start)}–${formatYear(role.mandate_end)}`
              : `${formatYear(role.mandate_start)}–present`
            : role.as_of
              ? `as of ${formatYear(role.as_of)}`
              : "—"}
        </span>
        {sourceBadge(role.source)}
      </div>
    </div>
  );
}

function HoldingRow({ h }: { h: PersonShareholding }) {
  return (
    <div className="px-3 py-2 border-b border-slate-50 last:border-0 flex items-center gap-3">
      <div className="min-w-0 flex-1">
        <Link
          href={`/company/${h.enterprise_number}`}
          className="text-sm font-medium text-indigo-600 hover:underline truncate block"
        >
          {h.company_name || fmtCbe(h.enterprise_number)}
        </Link>
        <div className="flex items-center gap-2 text-[11px] text-slate-400 mt-0.5">
          <span className="font-mono">{fmtCbe(h.enterprise_number)}</span>
          {h.fiscal_year && <span>• FY{h.fiscal_year}</span>}
        </div>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        {h.revenue != null && (
          <span className="text-[11px] font-mono text-slate-500 w-24 text-right">
            {fmtEur(h.revenue)}
          </span>
        )}
        <span className="text-xs font-semibold text-slate-700 w-16 text-right">
          {h.ownership_pct != null ? `${h.ownership_pct.toFixed(1)}%` : "—"}
        </span>
      </div>
    </div>
  );
}

export default function PersonProfilePage() {
  const params = useParams();
  const { t: _t } = useTranslation();
  const rawName = params?.name;
  const name = useMemo(() => {
    if (typeof rawName === "string") return decodeURIComponent(rawName);
    if (Array.isArray(rawName) && rawName.length > 0) return decodeURIComponent(rawName[0]);
    return "";
  }, [rawName]);

  const [profile, setProfile] = useState<PersonProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!name) return;
    setLoading(true);
    setErr(null);
    getPersonConnections(name)
      .then((p) => setProfile(p))
      .catch(() => setErr("Could not load this person."))
      .finally(() => setLoading(false));
  }, [name]);

  // Timeline: group admin roles by year-of-mandate-start (or as_of when
  // mandate_start is missing). Sort years descending so the most recent
  // involvement surfaces first.
  const timeline = useMemo(() => {
    if (!profile) return [];
    const byYear = new Map<string, PersonAdminRole[]>();
    for (const r of profile.administrator_roles) {
      const anchor = r.mandate_start || r.as_of;
      const year = anchor && anchor.length >= 4 ? anchor.slice(0, 4) : "unknown";
      if (!byYear.has(year)) byYear.set(year, []);
      byYear.get(year)!.push(r);
    }
    return Array.from(byYear.entries())
      .sort((a, b) => (a[0] < b[0] ? 1 : -1))
      .map(([year, rows]) => ({ year, rows }));
  }, [profile]);

  if (!name) {
    return (
      <div className="mx-auto w-full max-w-[1000px] px-4 py-6">
        <p className="text-sm text-slate-500">No name specified.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1000px] px-4 py-6">
      <Link
        href="/people"
        className="mb-4 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-600"
      >
        <ArrowLeft className="h-3 w-3" /> Back to people
      </Link>

      <div className="mb-4">
        <h1 className="text-2xl font-semibold text-slate-900">{name}</h1>
        {profile && (
          <div className="mt-2 flex flex-wrap gap-4 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1">
              <Building className="h-3.5 w-3.5" /> {profile.total_companies} {profile.total_companies === 1 ? "company" : "companies"}
            </span>
            <span className="inline-flex items-center gap-1">
              <Briefcase className="h-3.5 w-3.5" /> {profile.admin_count} admin {profile.admin_count === 1 ? "role" : "roles"}
            </span>
            <span className="inline-flex items-center gap-1">
              <Users className="h-3.5 w-3.5" /> {profile.holding_count} {profile.holding_count === 1 ? "shareholding" : "shareholdings"}
            </span>
          </div>
        )}
      </div>

      {loading && (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-indigo-400" />
        </div>
      )}
      {err && !loading && (
        <p className="text-sm text-rose-500">{err}</p>
      )}

      {!loading && profile && profile.total_companies === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-slate-400">
            No company connections on file for this name.
            <br />
            <span className="text-xs text-slate-300">
              The KBO licence prohibits personal-data tracking for direct
              marketing; if you expected a result, the name may differ in
              register spelling.
            </span>
          </CardContent>
        </Card>
      )}

      {!loading && profile && profile.administrator_roles.length > 0 && (
        <Card className="mb-4">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-center gap-2 mb-3">
              <Briefcase className="h-4 w-4 text-slate-400" />
              <h2 className="text-sm font-semibold text-slate-700">
                Administrator roles ({profile.administrator_roles.length})
              </h2>
            </div>
            <div className="rounded-lg border border-slate-100 bg-white">
              {profile.administrator_roles.map((role, i) => (
                <AdminRoleRow key={`${role.enterprise_number}-${role.role}-${i}`} role={role} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {!loading && profile && profile.shareholdings.length > 0 && (
        <Card className="mb-4">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-center gap-2 mb-3">
              <Users className="h-4 w-4 text-slate-400" />
              <h2 className="text-sm font-semibold text-slate-700">
                Shareholdings ({profile.shareholdings.length})
              </h2>
            </div>
            <div className="rounded-lg border border-slate-100 bg-white">
              {profile.shareholdings.map((h, i) => (
                <HoldingRow key={`${h.enterprise_number}-${i}`} h={h} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {!loading && profile && timeline.length > 0 && (
        <Card className="mb-4">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-center gap-2 mb-3">
              <Calendar className="h-4 w-4 text-slate-400" />
              <h2 className="text-sm font-semibold text-slate-700">
                Timeline of involvement
              </h2>
            </div>
            <div className="relative pl-4">
              <span className="absolute top-2 bottom-2 left-1 w-px bg-slate-200" />
              {timeline.map(({ year, rows }) => (
                <div key={year} className="mb-3 relative">
                  <span className="absolute -left-3 top-1 inline-block w-2 h-2 rounded-full bg-indigo-400" />
                  <div className="text-[11px] font-mono text-slate-500 mb-1">
                    {year === "unknown" ? "No date" : year}
                  </div>
                  <ul className="space-y-1">
                    {rows.map((r, i) => (
                      <li key={`${r.enterprise_number}-${i}`} className="text-xs text-slate-600">
                        <Link
                          href={`/company/${r.enterprise_number}`}
                          className="text-indigo-600 hover:underline inline-flex items-center gap-1"
                        >
                          {r.company_name || fmtCbe(r.enterprise_number)}
                          <ExternalLink className="h-3 w-3" />
                        </Link>
                        <span className="text-slate-400"> — {r.role_label || r.role || "admin"}</span>
                        {r.mandate_end && (
                          <span className="text-rose-400"> • ended {formatYear(r.mandate_end)}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
