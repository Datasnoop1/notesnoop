/**
 * Unified auth helper — Phase 2 of docs/auth-migration-clerk-final.md.
 *
 * Goal: downstream pages import `getCurrentUser`/`useCurrentUser` and don't
 * have to know whether Supabase or Clerk is the active auth provider. The
 * branch is selected at module load via `NEXT_PUBLIC_USE_CLERK`, the same
 * flag that gates the `proxy.ts` middleware and the `<ClerkProvider>` wrap
 * in `app/layout.tsx`.
 *
 * The shape returned to consumers is intentionally minimal:
 *
 *   { id: string, email: string } | null
 *
 * - `id` is the DataSnoop user id (Supabase UUID). When the Clerk path is
 *   active, this is read from `external_id` (which the migration script
 *   sets at import time, see Phase 4/5.5). For NEW Clerk sign-ups during
 *   the race window before the `user.created` webhook lands, the helper
 *   falls back to Clerk's `sub` so callers always get a non-null id; the
 *   backend's `clerk_user_map` lookup translates it to the DataSnoop id
 *   on the API side.
 * - `email` is the user's primary email address.
 *
 * NOTE: Phase 2 ships this helper but does NOT migrate the 9 existing
 * Supabase-path consumer files (login, account, admin, nav, staging-gate,
 * auth/callback, auth/reset-password, lib/supabase, linkedin). They keep
 * using the Supabase client directly until Phase 4 or 5. As a result,
 * with `NEXT_PUBLIC_USE_CLERK=false` (the default), this helper is
 * effectively unused at runtime in production.
 */

import { createClient } from "@/lib/supabase";

const USE_CLERK = process.env.NEXT_PUBLIC_USE_CLERK === "true";

export type CurrentUser = {
  /** DataSnoop user id (Supabase UUID). Falls back to Clerk `sub` during the JWT race window for new sign-ups. */
  id: string;
  /** Primary email address. */
  email: string;
};

/**
 * Server-side current-user lookup. Safe to call from Server Components,
 * Route Handlers, and Server Actions.
 *
 * On the Clerk path this uses dynamic `import()` so the Supabase build
 * doesn't accidentally try to resolve `@clerk/nextjs/server` at runtime
 * when the flag is off (and vice versa).
 */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  if (USE_CLERK) {
    const { auth, currentUser } = await import("@clerk/nextjs/server");
    const { userId, sessionClaims } = await auth();
    if (!userId) return null;

    // Prefer the DataSnoop id baked into the JWT claim by the Clerk JWT
    // template (`datasnoop_user_id` -> `{{user.external_id}}`). For NEW
    // sign-ups the claim can be missing for ~one request before the
    // webhook lands; fall back to Clerk's `sub` so we never return null
    // for a signed-in user. Backend `clerk_user_map` resolves either id.
    const claims = (sessionClaims ?? {}) as Record<string, unknown>;
    const datasnoopUserId =
      typeof claims.datasnoop_user_id === "string" ? claims.datasnoop_user_id : null;
    const id = datasnoopUserId ?? userId;

    const user = await currentUser();
    const email = user?.primaryEmailAddress?.emailAddress ?? user?.emailAddresses?.[0]?.emailAddress ?? "";
    return { id, email };
  }

  // Supabase path — server-side. The frontend's existing Supabase client
  // is browser-only (uses `createBrowserClient`), so for now the server
  // branch only exposes what's available via session claims; consumers
  // that need server-side Supabase user lookup keep using the existing
  // `@supabase/ssr` integration directly until Phase 4/5 migration. We
  // return null here and let server-component callers fall back to
  // `useCurrentUser()` on the client.
  return null;
}

/**
 * Client-side current-user lookups.
 *
 * Two named hooks — one per provider — each calls hooks unconditionally
 * to satisfy React's Rules of Hooks. Consumers (Phase 4+) pick the right
 * hook based on which provider their component subtree is under
 * (Clerk path is wrapped in <ClerkProvider>; Supabase path is not).
 *
 * No combined `useCurrentUser` wrapper is exported on purpose — picking
 * the hook conditionally inside a single function call would violate
 * Rules of Hooks even though `USE_CLERK` is module-load-constant.
 *
 * Phase 4/5 introduces consumers; until then this file's client hooks
 * are unused.
 */
export { useCurrentUserClerk, useCurrentUserSupabase };

// ---- Clerk-path client hook ---------------------------------------------

function useCurrentUserClerk(): CurrentUser | null {
  // Lazy require so the Supabase-only build doesn't pull Clerk's client
  // bundle when the flag is off. ESLint won't love this but it's the
  // simplest way to keep the two paths fully isolated until Phase 4/5.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { useAuth, useUser } = require("@clerk/nextjs") as typeof import("@clerk/nextjs");
  const { sessionClaims, userId, isSignedIn } = useAuth();
  const { user } = useUser();
  if (!isSignedIn || !userId) return null;
  const claims = (sessionClaims ?? {}) as Record<string, unknown>;
  const datasnoopUserId =
    typeof claims.datasnoop_user_id === "string" ? claims.datasnoop_user_id : null;
  const id = datasnoopUserId ?? userId;
  const email = user?.primaryEmailAddress?.emailAddress ?? user?.emailAddresses?.[0]?.emailAddress ?? "";
  return { id, email };
}

// ---- Supabase-path client hook ------------------------------------------

function useCurrentUserSupabase(): CurrentUser | null {
  // Mirror the Supabase pattern already used in `components/nav.tsx` and
  // `app/account/page.tsx`. Inlined as `useState`/`useEffect` so this
  // helper has no extra dependencies. The browser client is created lazily
  // on first call to keep SSR happy.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react") as typeof import("react");
  const [u, setU] = React.useState<CurrentUser | null>(null);
  React.useEffect(() => {
    const supabase = createClient();
    let mounted = true;
    supabase.auth.getUser().then(({ data }) => {
      if (!mounted) return;
      const sbUser = data.user;
      if (!sbUser) {
        setU(null);
      } else {
        setU({ id: sbUser.id, email: sbUser.email ?? "" });
      }
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!mounted) return;
      const sbUser = session?.user;
      if (!sbUser) {
        setU(null);
      } else {
        setU({ id: sbUser.id, email: sbUser.email ?? "" });
      }
    });
    return () => {
      mounted = false;
      sub.subscription.unsubscribe();
    };
  }, []);
  return u;
}
