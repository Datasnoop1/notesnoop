import { createBrowserClient } from "@supabase/ssr";

/**
 * Staging detection — covers both DNS-based access (staging.datasnoop.be)
 * and raw-IP access (62.238.14.150:8080). The port:8080 check is load-
 * bearing: production runs on 80/443, so port 8080 uniquely identifies
 * staging regardless of hostname. Without it, IP-based access wrongly
 * ran as production, breaking the admin sign-in flow (Supabase OAuth
 * redirected to prod's Site URL and cookies landed on the wrong host).
 */
const isStaging = typeof window !== "undefined" &&
  (window.location.hostname.includes("staging.") || window.location.port === "8080");

/**
 * One-shot cleanup for commit 32723bd, which tried to scope the session
 * cookie to `.datasnoop.be` so sign-ins flowed between prod and staging.
 * In practice the apex binding broke session persistence — users logged
 * in, then lost their session on the next page load. We revert to the
 * Supabase default (host-only cookies) and actively delete any apex-
 * bound copies left over in browsers so host-only cookies can be set
 * cleanly. No-op once cookies are already host-only.
 */
function clearStaleApexCookies() {
  if (typeof document === "undefined") return;
  const { hostname } = window.location;
  if (hostname !== "datasnoop.be" && !hostname.endsWith(".datasnoop.be")) return;
  for (const raw of document.cookie.split(";")) {
    const name = raw.split("=")[0]?.trim();
    if (!name) continue;
    if (name.startsWith("sb-") || name.startsWith("supabase-")) {
      document.cookie = `${name}=; path=/; domain=.datasnoop.be; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
    }
  }
}

if (typeof window !== "undefined") {
  clearStaleApexCookies();
}

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      auth: {
        ...(isStaging ? { flowType: "implicit" } : {}),
      },
    }
  );
}
