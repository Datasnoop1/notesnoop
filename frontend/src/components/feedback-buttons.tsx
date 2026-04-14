"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { Bug, Lightbulb, Heart } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { createClient } from "@/lib/supabase";
import { submitFeedback } from "@/lib/api";
import type { User } from "@supabase/supabase-js";

function FeedbackDialog({
  type,
  icon,
  label,
  placeholder,
}: {
  type: "bug" | "suggestion";
  icon: React.ReactNode;
  label: string;
  placeholder: string;
}) {
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => setUser(data.user));
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => setUser(session?.user ?? null)
    );
    return () => subscription.unsubscribe();
  }, []);

  async function handleSubmit() {
    if (!description.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitFeedback(type, description.trim(), pathname, user?.email ?? undefined);
      setSubmitted(true);
      setDescription("");
      setTimeout(() => {
        setOpen(false);
        setSubmitted(false);
      }, 2000);
    } catch (err) {
      setError("Failed to submit. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger>
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-full hover:bg-slate-50 hover:border-slate-300 transition-colors cursor-pointer">
          {icon}
          {label}
        </span>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {type === "bug" ? "Report a Bug" : "Suggest a Feature"}
            </h2>
            <p className="text-sm text-slate-500">
              {type === "bug"
                ? "Describe what went wrong and we'll look into it."
                : "Tell us what would make Data Peak better."}
            </p>
          </div>

          {submitted ? (
            <div className="text-sm text-green-600 bg-green-50 border border-green-200 rounded-md px-4 py-3">
              Thank you! Your {type === "bug" ? "bug report" : "suggestion"} has been submitted.
            </div>
          ) : (
            <>
              <div>
                <Label htmlFor="feedback-desc">Description</Label>
                <Textarea
                  id="feedback-desc"
                  placeholder={placeholder}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={4}
                  className="mt-1"
                />
              </div>

              <div className="text-xs text-slate-400">
                {user
                  ? `Submitting as ${user.email} from page: ${pathname}`
                  : `Submitting anonymously from page: ${pathname}`}
              </div>

              {error && (
                <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                  {error}
                </div>
              )}

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
                <Button
                  className="bg-indigo-600 hover:bg-indigo-700"
                  onClick={handleSubmit}
                  disabled={submitting || !description.trim()}
                >
                  {submitting ? "Submitting..." : "Submit"}
                </Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function DonateButton() {
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [customAmount, setCustomAmount] = useState("");
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

  async function handleDonate(amountCents: number) {
    if (amountCents < 100) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/stripe/donate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: amountCents }),
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      }
    } catch {
      // Silent fail
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger>
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-rose-600 bg-rose-50 border border-rose-200 rounded-full hover:bg-rose-100 hover:border-rose-300 transition-colors cursor-pointer">
          <Heart className="w-3.5 h-3.5" />
          Support us
        </span>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xs">
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              Support Data Peak
            </h2>
            <p className="text-sm text-slate-500">
              Help us keep improving!
            </p>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {[5, 10, 25, 50].map((amt) => (
              <button
                key={amt}
                onClick={() => handleDonate(amt * 100)}
                disabled={loading}
                className="rounded-lg border border-slate-200 bg-white px-2 py-2.5 text-sm font-semibold text-slate-700 hover:border-rose-300 hover:bg-rose-50 hover:text-rose-600 transition-colors disabled:opacity-50"
              >
                {loading ? "..." : `\u20AC${amt}`}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              type="number"
              min={1}
              placeholder="Custom \u20AC"
              value={customAmount}
              onChange={(e) => setCustomAmount(e.target.value)}
              className="flex-1"
            />
            <Button
              onClick={() => {
                const val = parseFloat(customAmount);
                if (val > 0) handleDonate(Math.round(val * 100));
              }}
              disabled={loading || !customAmount || parseFloat(customAmount) <= 0}
              className="bg-rose-600 hover:bg-rose-700 text-white shrink-0"
            >
              {loading ? "..." : "Donate"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function FeedbackButtons() {
  return (
    <div className="flex items-center gap-1.5">
      <FeedbackDialog
        type="bug"
        icon={<Bug className="w-3.5 h-3.5" />}
        label="Report bug"
        placeholder="What happened? What did you expect to happen?"
      />
      <FeedbackDialog
        type="suggestion"
        icon={<Lightbulb className="w-3.5 h-3.5" />}
        label="Suggest idea"
        placeholder="What feature or improvement would you like to see?"
      />
      <DonateButton />
    </div>
  );
}
