import { createBrowserClient } from "@supabase/ssr";

const isStaging = typeof window !== "undefined" && window.location.hostname.includes("staging.");

/**
 * Scope the Supabase session cookie to the apex domain (.datasnoop.be) when
 * we're running on a datasnoop host. One sign-in on either datasnoop.be or
 * staging.datasnoop.be then yields a session that's valid on both — flipping
 * between the two no longer forces a re-login.
 *
 * Returns undefined for localhost / IP-based access so the browser falls
 * back to host-only cookies (which is what dev needs).
 */
function getCookieDomain(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const hostname = window.location.hostname;
  if (hostname === "datasnoop.be" || hostname.endsWith(".datasnoop.be")) {
    return ".datasnoop.be";
  }
  return undefined;
}

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      auth: {
        ...(isStaging ? { flowType: "implicit" } : {}),
      },
      cookieOptions: {
        domain: getCookieDomain(),
      },
    }
  );
}
