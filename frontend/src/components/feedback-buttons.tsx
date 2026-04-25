"use client";

import { useState } from "react";
import { Mail, Heart } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

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
        <span
          title="Support us"
          aria-label="Support us"
          className="inline-flex items-center gap-1.5 h-8 px-2 rounded-md text-[12px] font-medium text-rose-400 hover:text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer"
        >
          <Heart className="w-4 h-4" />
          <span>Donate</span>
        </span>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xs">
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              Support Datasnoop
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
                {loading ? "..." : `€${amt}`}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              type="number"
              min={1}
              placeholder="Custom €"
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
      <a
        href="mailto:claude@datasnoop.be?subject=DataSnoop%20feedback"
        title="Send feedback to claude@datasnoop.be"
        aria-label="Send feedback to claude@datasnoop.be"
        className="inline-flex items-center gap-1.5 h-8 px-2 rounded-md text-[12px] font-medium text-gray-400 hover:text-brand hover:bg-brand-soft/60 transition-colors cursor-pointer"
      >
        <Mail className="w-4 h-4" />
        <span>Feedback</span>
      </a>
      <DonateButton />
    </div>
  );
}
