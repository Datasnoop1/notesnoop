import { createBrowserClient } from "@supabase/ssr";

const isStaging = typeof window !== "undefined" && window.location.hostname.includes("staging.");

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
