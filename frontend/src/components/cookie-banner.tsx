"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

const COOKIE_CONSENT_KEY = "datasnoop_cookie_consent";

export default function CookieBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const consent = localStorage.getItem(COOKIE_CONSENT_KEY);
    if (!consent) {
      setVisible(true);
    }
  }, []);

  function handleAccept() {
    localStorage.setItem(COOKIE_CONSENT_KEY, "accepted");
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div className="fixed bottom-0 inset-x-0 z-50 p-4 pointer-events-none">
      <div className="max-w-lg mx-auto bg-white border border-slate-200 rounded-lg shadow-lg px-5 py-4 flex items-center gap-4 pointer-events-auto">
        <p className="text-sm text-slate-600 flex-1">
          We use essential cookies for authentication only. No tracking cookies.{" "}
          <Link href="/privacy" className="text-brand hover:underline whitespace-nowrap">
            Privacy Policy
          </Link>
        </p>
        <Button
          size="sm"
          onClick={handleAccept}
          className="bg-brand hover:bg-[color:var(--brand-ink)] shrink-0"
        >
          Accept
        </Button>
      </div>
    </div>
  );
}
