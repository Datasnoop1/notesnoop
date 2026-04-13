"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { Bug, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTrigger,
} from "@/components/ui/dialog";
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
                : "Tell us what would make LeadPeek better."}
            </p>
          </div>

          {!user ? (
            <div className="text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-md px-4 py-3">
              <a href="/login" className="text-indigo-600 hover:underline font-medium">
                Sign in
              </a>{" "}
              to submit {type === "bug" ? "bug reports" : "suggestions"}.
            </div>
          ) : submitted ? (
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
                Submitting as {user.email} from page: {pathname}
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
    </div>
  );
}
