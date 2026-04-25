"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";

export default function AuthCallback() {
  const router = useRouter();
  const [status, setStatus] = useState("Processing login...");

  useEffect(() => {
    async function handleAuth() {
      const supabase = createClient();

      // Check if there's a hash fragment (implicit flow)
      const hash = window.location.hash;
      if (hash && hash.includes("access_token")) {
        setStatus("Found access token, signing in...");
        // Supabase auto-detects tokens in the hash
        const { data, error } = await supabase.auth.getSession();
        if (data?.session) {
          setStatus("Signed in! Redirecting...");
          router.push("/");
          return;
        }
        if (error) {
          setStatus(`Error: ${error.message}`);
        }
      }

      // Check for code parameter (PKCE flow)
      const params = new URLSearchParams(window.location.search);
      const code = params.get("code");
      if (code) {
        setStatus("Exchanging auth code...");
        const { data, error } = await supabase.auth.exchangeCodeForSession(code);
        if (error) {
          setStatus(`Code exchange error: ${error.message}`);
          // Wait and retry
          await new Promise(r => setTimeout(r, 2000));
          router.push("/login?error=auth_failed");
          return;
        }
        if (data?.session) {
          setStatus("Signed in! Redirecting...");
          router.push("/");
          return;
        }
      }

      // Check if there's an error in hash
      if (hash && hash.includes("error")) {
        const hashParams = new URLSearchParams(hash.substring(1));
        const error = hashParams.get("error_description") || hashParams.get("error") || "Unknown error";
        setStatus(`Auth error: ${decodeURIComponent(error)}`);
        await new Promise(r => setTimeout(r, 3000));
        router.push("/login?error=auth_failed");
        return;
      }

      // No code or hash — check if already signed in
      const { data } = await supabase.auth.getSession();
      if (data?.session) {
        setStatus("Already signed in! Redirecting...");
        router.push("/");
        return;
      }

      // Nothing worked — show debug info
      setStatus(`No auth data found. URL: ${window.location.href.substring(0, 100)}...`);
      await new Promise(r => setTimeout(r, 5000));
      router.push("/login");
    }

    handleAuth();
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-[50vh]">
      <div className="text-center max-w-md">
        <div className="animate-spin h-8 w-8 border-2 border-brand border-t-transparent rounded-full mx-auto mb-4" />
        <p className="text-sm text-slate-600">{status}</p>
      </div>
    </div>
  );
}
