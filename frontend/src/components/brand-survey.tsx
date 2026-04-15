"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { BarChart3 } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
const STORAGE_PREFIX = "datasnoop_poll_";

interface ActivePoll {
  id: number;
  title: string;
  question: string;
  options: string[];
}

export default function BrandSurvey() {
  const [poll, setPoll] = useState<ActivePoll | null>(null);
  const [visible, setVisible] = useState(false);
  const [voted, setVoted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Fetch active poll
    fetch(`${API_BASE}/api/polls/active`)
      .then((r) => r.json())
      .then((data) => {
        if (!data || !data.id) return;
        // Check if already voted/dismissed
        const key = `${STORAGE_PREFIX}${data.id}`;
        if (localStorage.getItem(key)) return;
        setPoll(data);
        // Show after 3 seconds
        setTimeout(() => setVisible(true), 3000);
      })
      .catch(() => {});
  }, []);

  async function handleVote(choice: string) {
    if (!poll) return;
    setSubmitting(true);
    try {
      await fetch(`${API_BASE}/api/polls/${poll.id}/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice }),
      });
    } catch {
      // Silent fail
    }
    localStorage.setItem(`${STORAGE_PREFIX}${poll.id}`, choice);
    setVoted(true);
    setSubmitting(false);
    setTimeout(() => setVisible(false), 2000);
  }

  function dismiss() {
    if (poll) localStorage.setItem(`${STORAGE_PREFIX}${poll.id}`, "dismissed");
    setVisible(false);
  }

  if (!visible || !poll) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <Card className="w-full max-w-sm mx-4 bg-white shadow-2xl">
        <CardContent className="pt-6 pb-5 px-6">
          {voted ? (
            <div className="text-center py-4">
              <BarChart3 className="w-8 h-8 text-indigo-500 mx-auto mb-2" />
              <p className="font-semibold text-slate-900">Thanks for your vote!</p>
            </div>
          ) : (
            <>
              <div className="text-center mb-5">
                <BarChart3 className="w-6 h-6 text-indigo-500 mx-auto mb-2" />
                <p className="text-sm font-bold uppercase tracking-wider text-indigo-600 mb-1">
                  {poll.title}
                </p>
                <h2 className="text-lg font-bold text-slate-900">
                  {poll.question}
                </h2>
              </div>

              <div className="space-y-2">
                {poll.options.map((opt) => (
                  <Button
                    key={opt}
                    variant="outline"
                    className="w-full justify-start text-left h-12 text-sm font-medium hover:bg-indigo-50 hover:border-indigo-300"
                    onClick={() => handleVote(opt)}
                    disabled={submitting}
                  >
                    {opt}
                  </Button>
                ))}
              </div>

              <button
                onClick={dismiss}
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
