"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";

export default function AuthCallback() {
  const router = useRouter();

  useEffect(() => {
    const supabase = createClient();

    // The hash fragment contains the auth tokens from Supabase OAuth
    // Supabase client automatically picks them up from the URL
    supabase.auth.onAuthStateChange((event) => {
      if (event === "SIGNED_IN") {
        router.push("/");
      }
    });

    // Also try to get the session (handles code exchange for PKCE)
    const hash = window.location.hash;
    if (hash) {
      // Supabase auto-detects tokens in the hash
      setTimeout(() => router.push("/"), 2000);
    } else {
      // Check URL params for code exchange
      const params = new URLSearchParams(window.location.search);
      const code = params.get("code");
      if (code) {
        supabase.auth.exchangeCodeForSession(code).then(({ error }) => {
          if (!error) {
            router.push("/");
          } else {
            console.error("Auth callback error:", error);
            router.push("/login?error=auth_failed");
          }
        });
      } else {
        // No code or hash — just redirect
        router.push("/");
      }
    }
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-[50vh]">
      <div className="text-center">
        <div className="animate-spin h-8 w-8 border-2 border-indigo-600 border-t-transparent rounded-full mx-auto mb-4" />
        <p className="text-sm text-slate-500">Signing you in...</p>
      </div>
    </div>
  );
}
