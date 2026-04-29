"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { useTranslation } from "@/components/language-provider";

export default function ResetPasswordPage() {
  const router = useRouter();
  const supabase = createClient();
  const { t } = useTranslation();

  const [ready, setReady] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    // Supabase verify-endpoint failures (expired / consumed link) land in the
    // URL hash, not in the SDK. Cap length so a malformed URL can't render a
    // huge red block.
    if (typeof window !== "undefined" && window.location.hash.includes("error")) {
      const params = new URLSearchParams(window.location.hash.substring(1));
      const raw = params.get("error_description") || params.get("error");
      if (raw) {
        const decoded = decodeURIComponent(raw).replace(/\+/g, " ");
        setError(decoded.length > 200 ? decoded.slice(0, 200) + "…" : decoded);
      }
    }

    // PASSWORD_RECOVERY is the only signal that authorises showing the form.
    // We deliberately do NOT accept SIGNED_IN or an existing session — that
    // would let a stale tab change a password without the email flow.
    const { data: sub } = supabase.auth.onAuthStateChange((event) => {
      if (!mounted) return;
      if (event === "PASSWORD_RECOVERY") {
        setReady(true);
        if (timeout) clearTimeout(timeout);
      }
    });

    // 8s covers slow-network PKCE code exchange before declaring the link dead.
    timeout = setTimeout(() => {
      if (!mounted) return;
      setReady((current) => {
        if (!current) setError(t("login.resetLinkInvalid"));
        return current;
      });
    }, 8000);

    return () => {
      mounted = false;
      if (timeout) clearTimeout(timeout);
      sub.subscription.unsubscribe();
    };
  }, [supabase.auth, t]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (newPassword.length < 6) {
      setError(t("account.passwordMinLength"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t("account.passwordMismatch"));
      return;
    }

    setSaving(true);
    const { error: updateError } = await supabase.auth.updateUser({
      password: newPassword,
    });
    setSaving(false);

    if (updateError) {
      setError(updateError.message);
      return;
    }

    setSuccess(true);
    setTimeout(() => router.replace("/"), 1200);
  }

  const formDisabled = !ready || saving || success;

  return (
    <div className="relative isolate flex items-center justify-center min-h-[70vh]">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 480px 360px at 30% 35%, rgba(22,135,232,0.18), transparent 65%), radial-gradient(ellipse 460px 360px at 75% 60%, rgba(31,155,143,0.14), transparent 65%), radial-gradient(ellipse 720px 520px at 50% 50%, rgba(234,245,255,0.5), transparent 70%)",
        }}
      />
      <Card className="w-full max-w-sm rounded-[20px] glass-card ring-0 bg-transparent">
        <CardContent className="pt-7 pb-6 px-7">
          <div className="text-center mb-6">
            <div className="w-10 h-10 rounded-xl bg-[#1687E8] flex items-center justify-center text-white font-bold text-lg mx-auto mb-4">
              D
            </div>
            <h1 className="text-[20px] font-bold text-[#08132B]">
              {t("login.setNewPasswordTitle")}
            </h1>
            <p className="text-[13px] text-[#5F6B85] mt-1.5">
              {t("login.setNewPasswordSubtitle")}
            </p>
          </div>

          {!ready && !error ? (
            <div className="text-center text-sm text-slate-500 py-4">
              <div className="animate-spin h-6 w-6 border-2 border-brand border-t-transparent rounded-full mx-auto mb-3" />
              {t("login.verifyingResetLink")}
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <Label htmlFor="new-password">{t("account.newPassword")}</Label>
                <Input
                  id="new-password"
                  type="password"
                  placeholder={t("account.newPasswordPlaceholder")}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={6}
                  disabled={formDisabled}
                />
              </div>
              <div>
                <Label htmlFor="confirm-password">{t("account.confirmPassword")}</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  minLength={6}
                  disabled={formDisabled}
                />
              </div>

              {error && (
                <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                  {error}
                </div>
              )}
              {success && (
                <div className="text-sm text-green-600 bg-green-50 border border-green-200 rounded-md px-3 py-2">
                  {t("account.passwordUpdated")}
                </div>
              )}

              <Button
                type="submit"
                className="w-full bg-[#1687E8] hover:bg-[#0F72C8] text-white rounded-xl h-11"
                disabled={formDisabled}
              >
                {saving ? t("account.updating") : t("account.updatePassword")}
              </Button>
            </form>
          )}

          <div className="text-center text-xs text-slate-500 mt-4">
            <Link href="/login" className="text-brand hover:underline font-medium">
              {t("login.backToSignIn")}
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
