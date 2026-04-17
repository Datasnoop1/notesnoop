"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";
import FontSwitcher from "@/components/font-switcher";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Mail, Calendar, CreditCard, Lock, Palette } from "lucide-react";
import type { User } from "@supabase/supabase-js";
import { useTranslation } from "@/components/language-provider";

export default function AccountPage() {
  const router = useRouter();
  const supabase = createClient();
  const { t } = useTranslation();

  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (!data.user) {
        router.push("/login");
      } else {
        setUser(data.user);
      }
      setLoading(false);
    });
  }, [router, supabase.auth]);

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);

    if (newPassword.length < 6) {
      setError(t("account.passwordMinLength"));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t("account.passwordMismatch"));
      return;
    }

    setSaving(true);
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) {
      setError(error.message);
    } else {
      setMessage(t("account.passwordUpdated"));
      setNewPassword("");
      setConfirmPassword("");
    }
    setSaving(false);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-pulse text-slate-400">Loading...</div>
      </div>
    );
  }

  if (!user) return null;

  const initials = user.email?.slice(0, 2).toUpperCase() ?? "?";
  const provider = user.app_metadata?.provider || "email";

  return (
    <div className="mx-auto w-full max-w-[1200px] space-y-6">
      {/* Profile header */}
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-full bg-indigo-600 text-white flex items-center justify-center text-xl font-bold shrink-0">
          {initials}
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">{user.email}</h1>
          <div className="flex items-center gap-3 mt-1 text-xs text-slate-400">
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {t("account.joined")} {new Date(user.created_at).toLocaleDateString("en-GB", { month: "short", year: "numeric" })}
            </span>
            <span className="capitalize flex items-center gap-1">
              <Mail className="w-3 h-3" />
              {provider}
            </span>
          </div>
        </div>
      </div>

      {/* Two-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Left column */}
        <div className="space-y-4">
          {/* Subscription */}
          <Card className="bg-white">
            <CardContent className="pt-5 pb-5">
              <div className="flex items-center gap-2 mb-3">
                <CreditCard className="w-4 h-4 text-slate-400" />
                <h2 className="text-sm font-semibold text-slate-900">{t("account.subscription")}</h2>
              </div>
              <div className="flex items-center gap-2 mb-3">
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 border border-slate-200">
                  {t("account.free")}
                </span>
                <span className="text-xs text-slate-400">{t("account.limitedSearches")}</span>
              </div>
              <div className="bg-indigo-50/70 border border-indigo-100 rounded-lg p-3">
                <h3 className="font-semibold text-indigo-900 text-xs">{t("account.powerUser")}</h3>
                <p className="text-[11px] text-indigo-600/80 mt-0.5">
                  {t("account.powerUserDesc")}
                </p>
                <button
                  disabled
                  className="mt-2 px-3 py-1.5 bg-indigo-600 text-white text-xs font-medium rounded-md opacity-50 cursor-not-allowed"
                >
                  {t("account.comingSoon")}
                </button>
              </div>
            </CardContent>
          </Card>

          {/* Appearance */}
          <Card className="bg-white">
            <CardContent className="pt-5 pb-5">
              <div className="flex items-center gap-2 mb-3">
                <Palette className="w-4 h-4 text-slate-400" />
                <h2 className="text-sm font-semibold text-slate-900">{t("account.appearance")}</h2>
              </div>
              <FontSwitcher />
            </CardContent>
          </Card>
        </div>

        {/* Right column */}
        <div>
          {/* Security */}
          <Card className="bg-white">
            <CardContent className="pt-5 pb-5">
              <div className="flex items-center gap-2 mb-4">
                <Lock className="w-4 h-4 text-slate-400" />
                <h2 className="text-sm font-semibold text-slate-900">{t("account.security")}</h2>
              </div>
              <form onSubmit={handleChangePassword} className="space-y-3">
                <div>
                  <Label htmlFor="new-password" className="text-xs">{t("account.newPassword")}</Label>
                  <Input
                    id="new-password"
                    type="password"
                    placeholder={t("account.newPasswordPlaceholder")}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={6}
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label htmlFor="confirm-password" className="text-xs">{t("account.confirmPassword")}</Label>
                  <Input
                    id="confirm-password"
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={6}
                    className="mt-1"
                  />
                </div>

                {error && (
                  <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                    {error}
                  </div>
                )}
                {message && (
                  <div className="text-xs text-green-600 bg-green-50 border border-green-200 rounded-md px-3 py-2">
                    {message}
                  </div>
                )}

                <Button
                  type="submit"
                  size="sm"
                  className="bg-indigo-600 hover:bg-indigo-700"
                  disabled={saving}
                >
                  {saving ? t("account.updating") : t("account.updatePassword")}
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
