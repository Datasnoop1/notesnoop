"use client";

/**
 * StagingGate — renders a "staging is admin-only" blocker card when the
 * backend reports STAGING_MODE=true and the current user is not admin.
 *
 * We trust the backend's own self-report (from /api/me/is-admin) rather
 * than hostname-sniffing on the client, because staging gets hit via
 * staging.datasnoop.be, the raw IP, and occasionally LAN hostnames —
 * all of which would need bespoke detection rules.
 *
 * Initial render mirrors the children so the landing page stays fast
 * and SSR output matches client output on prod. The gate only flips to
 * "block" after we've heard from the server that we're on staging AND
 * the user is authenticated but not an admin.
 */

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase";

/** Routes that should always render without the staging admin-only blocker.
 *  These are public demo / share pages that need to work for external viewers
 *  regardless of login state. */
const PUBLIC_DEMO_PATHS = ["/demo/"];

type GateState =
  | { kind: "unknown" } // before the first check completes
  | { kind: "allow" } // prod, or admin on staging, or no session
  | { kind: "block"; email: string | null };

export default function StagingGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "";
  const isPublicDemo = PUBLIC_DEMO_PATHS.some((p) => pathname.startsWith(p));
  const [state, setState] = useState<GateState>({ kind: "unknown" });

  useEffect(() => {
    let cancelled = false;

    // Public demo routes never show the blocker — external viewers with no
    // login (or non-admin login) must be able to see them.
    if (isPublicDemo) {
      setState({ kind: "allow" });
      return;
    }

    async function check() {
      try {
        const supabase = createClient();
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token;

        // No session → let the normal app render. Public pages don't
        // need the gate, and protected pages will show their own "sign
        // in" prompt when the user navigates to them.
        if (!token) {
          if (!cancelled) setState({ kind: "allow" });
          return;
        }

        const res = await fetch("/api/me/is-admin", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          // 401 from the gate itself (invalid token) — let the app handle
          // the redirect. 5xx — fail open, don't block the user on an
          // infra hiccup.
          if (!cancelled) setState({ kind: "allow" });
          return;
        }
        const body: { email: string | null; is_admin: boolean; staging_mode: boolean } = await res.json();
        if (cancelled) return;

        if (body.staging_mode && !body.is_admin) {
          setState({ kind: "block", email: body.email });
        } else {
          setState({ kind: "allow" });
        }
      } catch {
        if (!cancelled) setState({ kind: "allow" });
      }
    }

    check();

    // Re-check when auth state flips (sign in / sign out).
    const supabase = createClient();
    const { data: sub } = supabase.auth.onAuthStateChange(() => {
      check();
    });

    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, [isPublicDemo]);

  if (state.kind === "block") {
    return <BlockerCard email={state.email} />;
  }

  return <>{children}</>;
}

function BlockerCard({ email }: { email: string | null }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="max-w-md w-full rounded-xl border border-slate-200 bg-white shadow-sm p-8 text-center">
        <div className="mx-auto mb-4 h-12 w-12 rounded-full bg-amber-50 border border-amber-100 flex items-center justify-center">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.8}
            className="h-6 w-6 text-amber-600"
            aria-hidden="true"
          >
            <rect x="4" y="10" width="16" height="10" rx="2" />
            <path d="M8 10V7a4 4 0 018 0v3" />
          </svg>
        </div>
        <h1 className="text-lg font-semibold text-slate-800">
          Staging is admin-only
        </h1>
        <p className="mt-2 text-sm text-slate-500 leading-relaxed">
          This environment is restricted to DataSnoop admins. For the live site, please use{" "}
          <a href="https://datasnoop.be" className="text-indigo-600 hover:underline">
            datasnoop.be
          </a>
          .
        </p>
        {email && (
          <p className="mt-3 text-[11px] text-slate-400">
            Signed in as <span className="font-mono">{email}</span>
          </p>
        )}
      </div>
    </div>
  );
}
