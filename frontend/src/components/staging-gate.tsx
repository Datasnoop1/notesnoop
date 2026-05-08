"use client";

/**
 * StagingGate — renders a "staging is admin-only" blocker card when the
 * backend reports STAGING_MODE=true and the caller is not an admin
 * (including anonymous visitors).
 *
 * We trust the backend's own self-report (from /api/me/is-admin) rather
 * than hostname-sniffing on the client, because staging gets hit via
 * staging.datasnoop.be, the raw IP, and occasionally LAN hostnames —
 * all of which would need bespoke detection rules.
 *
 * To avoid a flash of landing-page content on staging, we use a cheap
 * hostname heuristic to decide whether to render children or a neutral
 * loader while /api/me/is-admin is in flight. On prod hostnames we
 * render children immediately (no perceptible cost); only a clear
 * "staging + not admin" response flips us to the blocker.
 */

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { getAuthToken } from "@/lib/api";
import { useAuth as useClerkAuth } from "@clerk/nextjs";

const USE_CLERK = process.env.NEXT_PUBLIC_USE_CLERK === "true";

/** Routes that should always render without the staging admin-only blocker.
 *  Public demos / share pages that external viewers must reach regardless
 *  of login state. */
const PUBLIC_DEMO_PATHS = ["/demo/"];

/** Routes that must stay reachable on staging for anonymous users —
 *  otherwise they'd have no way to sign in and become admin. */
const PUBLIC_AUTH_PATHS = ["/login", "/auth/"];

type GateState =
  | { kind: "unknown" } // before the first check completes
  | { kind: "allow" } // prod, or admin on staging
  | { kind: "block"; email: string | null };

function looksLikeStaging(): boolean {
  if (typeof window === "undefined") return false;
  const { hostname, port } = window.location;
  // staging.datasnoop.be, staging-*.datasnoop.be, and any :8080 origin
  // (direct-IP staging access during deploys). Not exhaustive — the
  // backend's staging_mode flag is the ground truth.
  return hostname.includes("staging") || port === "8080";
}

export default function StagingGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "";
  const isPublicDemo = PUBLIC_DEMO_PATHS.some((p) => pathname.startsWith(p));
  const isPublicAuth = PUBLIC_AUTH_PATHS.some(
    (p) => pathname === p || pathname.startsWith(p),
  );
  const [state, setState] = useState<GateState>({ kind: "unknown" });

  // On the Clerk path, getAuthToken() returns null until Clerk's
  // session is hydrated. useAuth() flips `isLoaded: true` only after
  // the SDK has resolved the session — and is the public hook backing
  // getToken(), so by the time we observe it ready, getAuthToken()
  // can return a real Bearer. useUser() flips a tick earlier and
  // racing it past getToken() left the very first /api/me/is-admin
  // going anon, sticking us in is_admin=false. The userId portion of
  // the identity key also re-runs the effect on sign-in / sign-out
  // even when the pathname doesn't change.
  const { isLoaded: clerkLoaded, userId: clerkUserId } = useClerkAuth();
  const clerkIdentity = USE_CLERK
    ? `${clerkLoaded ? "loaded" : "boot"}:${clerkUserId ?? "none"}`
    : "n/a";

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
        // Use the unified auth-token helper so we send the Clerk token when
        // USE_CLERK=true and the Supabase token otherwise. Backend's auth
        // router accepts both (routes by JWT iss).
        const token = await getAuthToken();

        const res = await fetch("/api/me/is-admin", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });

        if (!res.ok) {
          // Fail-open on infra errors so we don't lock users out of
          // prod on a 5xx. The backend middleware is the hard gate; if
          // the endpoint itself is broken there's nothing to protect
          // against anyway.
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

    // Re-check when auth state flips (sign in / sign out). On the Clerk
    // path, Clerk emits its own session events; for now we just re-check
    // periodically via the React effect re-run when the user signs in/out
    // (Clerk's nav <UserButton /> flow already navigates, which retriggers
    // the effect). On the Supabase path, listen for onAuthStateChange.
    if (USE_CLERK) {
      // Clerk handles auth state via its own provider; staging-gate
      // re-checks naturally on route changes (via pathname dep) and on
      // initial mount. No additional subscription needed for the
      // Phase 5 staging smoke test.
      return () => {
        cancelled = true;
      };
    }
    const supabase = createClient();
    const { data: sub } = supabase.auth.onAuthStateChange(() => {
      check();
    });

    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, [isPublicDemo, clerkIdentity]);

  // Always let login / oauth-callback and public demo pages render,
  // even if the visitor would otherwise be blocked. Otherwise
  // anonymous users would have no way to sign in to become admin,
  // and share/demo links would break for external viewers.
  if (isPublicAuth || isPublicDemo) {
    return <>{children}</>;
  }

  if (state.kind === "block") {
    return <BlockerCard email={state.email} />;
  }

  if (state.kind === "unknown" && looksLikeStaging()) {
    return <GateLoader />;
  }

  return <>{children}</>;
}

function GateLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="text-xs text-slate-400">Checking access…</div>
    </div>
  );
}

function BlockerCard({ email }: { email: string | null }) {
  const isAnonymous = !email;
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
          <a href="https://datasnoop.be" className="text-brand hover:underline">
            datasnoop.be
          </a>
          .
        </p>
        <div className="mt-5 flex items-center justify-center gap-2">
          {isAnonymous ? (
            <a
              href="/login"
              className="inline-flex items-center h-9 px-4 text-xs font-medium text-white bg-brand rounded-md hover:bg-[color:var(--brand-ink)] transition-colors"
            >
              Sign in as admin
            </a>
          ) : (
            <a
              href="https://datasnoop.be"
              className="inline-flex items-center h-9 px-4 text-xs font-medium text-white bg-brand rounded-md hover:bg-[color:var(--brand-ink)] transition-colors"
            >
              Go to datasnoop.be
            </a>
          )}
        </div>
        {email && (
          <p className="mt-3 text-[11px] text-slate-400">
            Signed in as <span className="font-mono">{email}</span>
          </p>
        )}
      </div>
    </div>
  );
}
