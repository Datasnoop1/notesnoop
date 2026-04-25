"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useTranslation } from "@/components/language-provider";
import { Lock } from "lucide-react";
import Link from "next/link";

type Mode = "login" | "signup" | "forgot";

export default function LoginPage() {
  const router = useRouter();
  const supabase = createClient();
  const { t } = useTranslation();

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function switchMode(m: Mode) {
    setMode(m);
    setError(null);
    setMessage(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setMessage(null);

    if (mode === "forgot") {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/account`,
      });
      if (error) {
        setError(error.message);
      } else {
        setMessage(t("login.checkEmailReset"));
      }
    } else if (mode === "login") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        setError(error.message);
      } else {
        router.replace("/");
      }
    } else {
      const { error } = await supabase.auth.signUp({ email, password });
      if (error) {
        setError(error.message);
      } else {
        setMessage(t("login.checkEmailConfirm"));
      }
    }
    setLoading(false);
  }

  async function handleOAuth(provider: "google" | "linkedin_oidc") {
    setLoading(true);
    setError(null);
    // On staging, we need explicit redirectTo since Supabase Site URL is production.
    // Detect staging via hostname OR port 8080 (raw-IP access uses port 8080;
    // hostname-based match alone misses 62.238.14.150:8080).
    const isStaging = window.location.hostname.includes("staging.")
      || window.location.port === "8080";
    const { error } = await supabase.auth.signInWithOAuth({
      provider,
      ...(isStaging ? { options: { redirectTo: `${window.location.origin}/auth/callback` } } : {}),
    });
    if (error) {
      setError(error.message);
      setLoading(false);
    }
  }

  const titles: Record<Mode, string> = {
    login: t("login.signInTitle"),
    signup: t("login.createAccountTitle"),
    forgot: t("login.resetPasswordTitle"),
  };

  const buttonLabels: Record<Mode, string> = {
    login: t("login.signInButton"),
    signup: t("login.createAccountButton"),
    forgot: t("login.sendResetLink"),
  };

  return (
    <div className="relative isolate flex items-center justify-center min-h-[70vh]">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 560px 400px at center, rgba(11,92,255,0.06), transparent 60%)",
        }}
      />
      <Card className="w-full max-w-sm rounded-[20px] border-[#E3EAF4] bg-white shadow-[0_12px_48px_rgba(15,23,42,0.08)]">
        <CardContent className="pt-7 pb-6 px-7">
          {/* Header */}
          <div className="text-center mb-6">
            <div className="w-10 h-10 rounded-xl bg-[#0B5CFF] flex items-center justify-center text-white font-bold text-lg mx-auto mb-4">
              D
            </div>
            <h1 className="text-[20px] font-bold text-[#07142F]">
              {titles[mode]}
            </h1>
            <p className="text-[13px] text-[#5F6B85] mt-1.5">
              {mode === "forgot"
                ? t("login.resetSubtitle")
                : t("login.subtitle")}
            </p>
          </div>

          {/* OAuth providers (login/signup only) */}
          {mode !== "forgot" && (
            <>
              <div className="space-y-2 mb-3">
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={() => handleOAuth("google")}
                  disabled={loading}
                >
                  <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                  </svg>
                  {t("login.continueWithGoogle")}
                </Button>
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={() => handleOAuth("linkedin_oidc")}
                  disabled={loading}
                >
                  <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24" fill="#0A66C2">
                    <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
                  </svg>
                  {t("login.continueWithLinkedIn")}
                </Button>
              </div>

              <div className="relative my-3">
                <Separator />
                <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-white px-3 text-xs text-slate-400">
                  {t("login.or")}
                </span>
              </div>
            </>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label htmlFor="email">{t("login.email")}</Label>
              <Input
                id="email"
                type="email"
                placeholder={t("login.emailPlaceholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {mode !== "forgot" && (
              <div>
                <Label htmlFor="password">{t("login.password")}</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder={mode === "signup" ? t("login.passwordPlaceholder") : ""}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={6}
                />
              </div>
            )}

            {error && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                {error}
              </div>
            )}
            {message && (
              <div className="text-sm text-green-600 bg-green-50 border border-green-200 rounded-md px-3 py-2">
                {message}
              </div>
            )}

            <Button
              type="submit"
              className="w-full bg-[#0B5CFF] hover:bg-[#084ED8] text-white rounded-xl h-11"
              disabled={loading}
            >
              {loading ? t("login.pleaseWait") : buttonLabels[mode]}
            </Button>
          </form>

          {/* Terms notice (signup mode) */}
          {mode === "signup" && (
            <p className="text-center text-[11px] text-slate-400 mt-3">
              {t("login.termsNotice")}{" "}
              <Link href="/terms" className="text-brand hover:underline">{t("login.termsOfUse")}</Link>
              {" "}{t("login.and")}{" "}
              <Link href="/privacy" className="text-brand hover:underline">{t("login.privacyPolicy")}</Link>.
            </p>
          )}

          {/* Footer links */}
          <div className="text-center text-xs text-slate-500 mt-3 space-y-1.5">
            {mode === "login" && (
              <>
                <button
                  onClick={() => switchMode("forgot")}
                  className="text-brand hover:underline font-medium block mx-auto"
                >
                  {t("login.forgotPassword")}
                </button>
                <p>
                  {t("login.noAccount")}{" "}
                  <button onClick={() => switchMode("signup")} className="text-brand hover:underline font-medium">
                    {t("login.signUp")}
                  </button>
                </p>
              </>
            )}
            {mode === "signup" && (
              <p>
                {t("login.alreadyHaveAccount")}{" "}
                <button onClick={() => switchMode("login")} className="text-brand hover:underline font-medium">
                  {t("login.signInButton")}
                </button>
              </p>
            )}
            {mode === "forgot" && (
              <p>
                {t("login.rememberPassword")}{" "}
                <button onClick={() => switchMode("login")} className="text-brand hover:underline font-medium">
                  {t("login.signInButton")}
                </button>
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
