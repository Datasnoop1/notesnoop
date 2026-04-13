"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import type { User } from "@supabase/supabase-js";

export default function AccountPage() {
  const router = useRouter();
  const supabase = createClient();

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
      setError("Password must be at least 6 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSaving(true);
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) {
      setError(error.message);
    } else {
      setMessage("Password updated successfully.");
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

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Account Settings</h1>
        <p className="text-sm text-slate-500 mt-1">Manage your account</p>
      </div>

      {/* Profile info */}
      <Card className="bg-white">
        <CardContent className="pt-6 space-y-4">
          <h2 className="font-semibold text-slate-900">Profile</h2>
          <div>
            <Label className="text-slate-500">Email</Label>
            <p className="text-sm font-medium text-slate-900 mt-1">{user.email}</p>
          </div>
          <div>
            <Label className="text-slate-500">Account created</Label>
            <p className="text-sm font-medium text-slate-900 mt-1">
              {new Date(user.created_at).toLocaleDateString()}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Subscription tier */}
      <Card className="bg-white">
        <CardContent className="pt-6 space-y-4">
          <h2 className="font-semibold text-slate-900">Subscription</h2>
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-semibold bg-slate-100 text-slate-700 border border-slate-200">
              Free
            </span>
            <span className="text-sm text-slate-500">
              Limited searches and exports
            </span>
          </div>
          <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
            <h3 className="font-semibold text-indigo-900 text-sm">Power User</h3>
            <p className="text-sm text-indigo-700 mt-1">
              Unlimited searches, full financial data, CSV exports, and priority support.
            </p>
            <button
              disabled
              className="mt-3 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md opacity-50 cursor-not-allowed"
            >
              Coming soon
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Change password */}
      <Card className="bg-white">
        <CardContent className="pt-6">
          <h2 className="font-semibold text-slate-900 mb-4">Change Password</h2>
          <form onSubmit={handleChangePassword} className="space-y-4">
            <div>
              <Label htmlFor="new-password">New password</Label>
              <Input
                id="new-password"
                type="password"
                placeholder="Min 6 characters"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={6}
              />
            </div>
            <div>
              <Label htmlFor="confirm-password">Confirm new password</Label>
              <Input
                id="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={6}
              />
            </div>

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
              className="bg-indigo-600 hover:bg-indigo-700"
              disabled={saving}
            >
              {saving ? "Updating..." : "Update password"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
