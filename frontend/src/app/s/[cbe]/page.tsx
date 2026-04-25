"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getCompanyDetail, getCompanyFinancials } from "@/lib/api";
import type { CompanyDetail, FinancialsData } from "@/app/company/[cbe]/types";
import { fmtCbe, fmtEur } from "@/lib/format";
import { Building2, MapPin, TrendingUp, Users, Calendar, Copy, Check, ExternalLink } from "lucide-react";

/* #14 Shareable company summary card. Public, no-login-required view
 * designed to be copy-pasted into chats / email signatures / LinkedIn.
 *
 * URL: /s/[cbe] — intentionally short so it fits in a message. The
 * route is public; gating is enforced on the authenticated profile
 * page, not here.
 */

export default function ShareableCompanyCard() {
  const params = useParams();
  const rawCbe = params?.cbe;
  const cbe =
    typeof rawCbe === "string"
      ? rawCbe.replace(/\./g, "").padStart(10, "0")
      : Array.isArray(rawCbe) && rawCbe.length > 0
        ? rawCbe[0].replace(/\./g, "").padStart(10, "0")
        : "";

  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [financials, setFinancials] = useState<FinancialsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!cbe) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      getCompanyDetail(cbe).catch(() => null),
      getCompanyFinancials(cbe).catch(() => null),
    ])
      .then(([d, f]) => {
        if (cancelled) return;
        setDetail((d as CompanyDetail | null) ?? null);
        setFinancials((f as unknown as FinancialsData | null) ?? null);
        if (!d) setErr("Company not found.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [cbe]);

  const copyLink = () => {
    if (typeof window === "undefined") return;
    const url = `${window.location.origin}/s/${cbe}`;
    const onSuccess = () => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    };
    const fallback = () => {
      try {
        const ta = document.createElement("textarea");
        ta.value = url;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        onSuccess();
      } catch {
        /* no-op */
      }
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(url).then(onSuccess, fallback);
    } else {
      fallback();
    }
  };

  const latest = financials?.summary?.[0] ?? null;
  const address = detail
    ? [detail.street, detail.house_number].filter(Boolean).join(" ") +
      ([detail.zipcode, detail.city].filter(Boolean).length
        ? `, ${[detail.zipcode, detail.city].filter(Boolean).join(" ")}`
        : "")
    : "";

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-sm text-slate-400 animate-pulse">Loading...</div>
      </div>
    );
  }

  if (err || !detail) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="text-center">
          <p className="text-sm text-slate-500 mb-3">Company not found.</p>
          <Link href="/" className="text-xs text-brand hover:underline">
            Go to DataSnoop
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100 py-8 px-4">
      <div className="mx-auto max-w-[620px]">
        <div className="mb-4 flex items-center justify-between text-xs text-slate-400">
          <Link href="/" className="hover:text-brand">
            ← DataSnoop
          </Link>
          <button
            type="button"
            onClick={copyLink}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-slate-200 bg-white hover:bg-brand-soft/60 hover:border-brand/30 transition-colors"
            title="Copy shareable link"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-emerald-500" />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                Copy link
              </>
            )}
          </button>
        </div>

        <div className="rounded-2xl bg-white shadow-lg border border-slate-100 overflow-hidden">
          {/* Header band */}
          <div className="px-6 py-5 border-b border-slate-100 bg-gradient-to-r from-brand-soft to-white">
            <div className="flex items-center gap-3 mb-1">
              <div className="h-10 w-10 rounded-lg bg-brand-soft flex items-center justify-center">
                <Building2 className="h-5 w-5 text-brand" />
              </div>
              <div className="min-w-0">
                <h1 className="text-xl font-bold text-slate-900 truncate">
                  {detail.name || fmtCbe(cbe)}
                </h1>
                <div className="flex items-center gap-2 text-[11px] text-slate-500">
                  <span className="font-mono">CBE {fmtCbe(cbe)}</span>
                  {detail.jf_label && (
                    <>
                      <span className="text-slate-300">•</span>
                      <span className="uppercase tracking-wide font-semibold">{detail.jf_label}</span>
                    </>
                  )}
                  {detail.status === "AC" ? (
                    <>
                      <span className="text-slate-300">•</span>
                      <span className="inline-flex items-center gap-1 text-emerald-600">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                        Active
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="text-slate-300">•</span>
                      <span className="text-rose-500">Inactive</span>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Body */}
          <div className="px-6 py-5 space-y-4">
            {address && (
              <div className="flex items-start gap-2 text-sm text-slate-700">
                <MapPin className="h-4 w-4 text-slate-400 shrink-0 mt-0.5" />
                <span>{address}</span>
              </div>
            )}
            {detail.nace_code && (
              <div className="flex items-start gap-2 text-sm text-slate-700">
                <Calendar className="h-4 w-4 text-slate-400 shrink-0 mt-0.5" />
                <span>
                  <span className="font-mono text-xs text-slate-400 mr-1">NACE {detail.nace_code}</span>
                  {detail.nace_label && detail.nace_label !== detail.nace_code && detail.nace_label}
                </span>
              </div>
            )}
            {detail.website && (
              <div className="flex items-start gap-2 text-sm">
                <ExternalLink className="h-4 w-4 text-slate-400 shrink-0 mt-0.5" />
                <a
                  href={detail.website.startsWith("http") ? detail.website : `https://${detail.website}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-brand hover:underline truncate"
                >
                  {detail.website.replace(/^https?:\/\//, "")}
                </a>
              </div>
            )}

            {latest && (
              <div className="mt-4 pt-4 border-t border-slate-100">
                <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-2">
                  FY {latest.fiscal_year}
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <Stat label="Revenue" value={fmtEur(latest.revenue)} />
                  <Stat label="EBITDA" value={fmtEur(latest.ebitda)} />
                  <Stat
                    label="EBITDA %"
                    value={latest.ebitda_margin_pct != null ? `${latest.ebitda_margin_pct.toFixed(1)}%` : "—"}
                  />
                  <Stat label="FTE" value={latest.fte_total != null ? latest.fte_total.toString() : "—"} />
                </div>
              </div>
            )}
          </div>

          {/* CTA */}
          <div className="px-6 py-4 bg-slate-50 border-t border-slate-100 flex items-center justify-between text-xs">
            <span className="text-slate-500">
              Source: KBO + NBB + Staatsblad (public registers)
            </span>
            <Link
              href={`/company/${cbe}`}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-brand text-white hover:bg-[color:var(--brand-ink)] transition-colors font-medium"
            >
              <TrendingUp className="h-3.5 w-3.5" />
              Full profile
            </Link>
          </div>
        </div>

        <p className="mt-4 text-center text-[11px] text-slate-400">
          Powered by <Link href="/" className="hover:text-brand">DataSnoop</Link>
          {" · "}
          <Users className="h-3 w-3 inline -mt-0.5" /> 170k+ Belgian companies, daily refresh.
        </p>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] text-slate-400 uppercase tracking-wider mb-0.5">{label}</div>
      <div className="text-sm font-semibold text-slate-900 font-mono">{value}</div>
    </div>
  );
}
