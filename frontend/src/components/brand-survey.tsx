"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
const STORAGE_KEY = "leadpeek_brand_vote";

const OPTIONS = [
  { value: "Data Snoop", emoji: "🔍" },
  { value: "Data Peek", emoji: "👁" },
  { value: "Data Peak", emoji: "⛰" },
];

export default function BrandSurvey() {
  const [visible, setVisible] = useState(false);
  const [voted, setVoted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Don't show if already voted
    if (localStorage.getItem(STORAGE_KEY)) return;
    // Show after 3 seconds
    const timer = setTimeout(() => setVisible(true), 3000);
    return () => clearTimeout(timer);
  }, []);

  async function handleVote(choice: string) {
    setSubmitting(true);
    try {
      await fetch(`${API_BASE}/api/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: "survey",
          page: "brand_name_vote",
          description: choice,
          user_email: null,
        }),
      });
    } catch {
      // Silent fail — vote still counts locally
    }
    localStorage.setItem(STORAGE_KEY, choice);
    setVoted(true);
    setSubmitting(false);
    setTimeout(() => setVisible(false), 2000);
  }

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <Card className="w-full max-w-sm mx-4 bg-white shadow-2xl">
        <CardContent className="pt-6 pb-5 px-6">
          {voted ? (
            <div className="text-center py-4">
              <div className="text-2xl mb-2">🙏</div>
              <p className="font-semibold text-slate-900">Thanks for your vote!</p>
            </div>
          ) : (
            <>
              <div className="text-center mb-5">
                <p className="text-sm font-bold uppercase tracking-wider text-indigo-600 mb-1">
                  Quick question
                </p>
                <h2 className="text-lg font-bold text-slate-900">
                  Which brand name do you prefer?
                </h2>
                <p className="text-xs text-slate-500 mt-1">
                  We're picking a name — your vote counts!
                </p>
              </div>

              <div className="space-y-2">
                {OPTIONS.map((opt) => (
                  <Button
                    key={opt.value}
                    variant="outline"
                    className="w-full justify-start text-left h-12 text-sm font-medium hover:bg-indigo-50 hover:border-indigo-300"
                    onClick={() => handleVote(opt.value)}
                    disabled={submitting}
                  >
                    <span className="mr-3 text-lg">{opt.emoji}</span>
                    {opt.value}
                  </Button>
                ))}
              </div>

              <button
                onClick={() => {
                  localStorage.setItem(STORAGE_KEY, "dismissed");
                  setVisible(false);
                }}
                className="w-full mt-3 text-xs text-slate-400 hover:text-slate-600 transition-colors"
              >
                Skip
              </button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
