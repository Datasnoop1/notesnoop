"use client";

import React, { useEffect, useState } from "react";
import {
  X,
  Sparkles,
  Building2,
  ShoppingBag,
  Users,
  Trophy,
  Clock,
  Globe,
  Link2 as Linkedin,
  Loader2,
  CheckCircle2,
  ExternalLink,
  ThumbsUp,
  ThumbsDown,
  RefreshCw,
} from "lucide-react";
import type { AiInsights } from "@/lib/api";

/* ---------- Types ---------- */

interface InsightsOverlayProps {
  open: boolean;
  onClose: () => void;
  insights: AiInsights | null;
  loading: boolean;
  companyName: string;
  onGenerate: () => void;
  onRegenerate?: () => void;
  onFeedback?: (feedback: { overall: "up" | "down"; websiteCorrect?: boolean; linkedinCorrect?: boolean; insightCorrect?: boolean; comment?: string }) => void;
}

/* ---------- Step indicator ---------- */

type StepStatus = "pending" | "active" | "done";

interface PipelineStep {
  label: string;
  status: StepStatus;
}

function StepIndicator({ steps }: { steps: PipelineStep[] }) {
  return (
    <div className="space-y-3">
      {steps.map((step, i) => (
        <div key={i} className="flex items-center gap-3">
          {step.status === "done" ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
          ) : step.status === "active" ? (
            <Loader2 className="h-4 w-4 animate-spin text-indigo-500 shrink-0" />
          ) : (
            <div className="h-4 w-4 rounded-full border-2 border-slate-200 shrink-0" />
          )}
          <span
            className={`text-sm ${
              step.status === "active"
                ? "text-indigo-600 font-medium"
                : step.status === "done"
                ? "text-slate-500"
                : "text-slate-400"
            }`}
          >
            {step.label}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ---------- Section card ---------- */

function InsightSection({
  icon,
  title,
  content,
}: {
  icon: React.ReactNode;
  title: string;
  content: string;
}) {
  if (!content) return null;
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-indigo-500">{icon}</span>
        <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
          {title}
        </h4>
      </div>
      <p className="text-sm text-slate-700 leading-relaxed">{content}</p>
    </div>
  );
}

/* ---------- Main component ---------- */

/* ---------- Feedback toggle ---------- */

function FeedbackToggle({ label, value, onChange }: { label: string; value: boolean | null; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-slate-500">{label}:</span>
      <button
        onClick={() => onChange(true)}
        className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors ${value === true ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300" : "bg-slate-100 text-slate-400 hover:bg-emerald-50"}`}
      >
        Correct
      </button>
      <button
        onClick={() => onChange(false)}
        className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors ${value === false ? "bg-rose-100 text-rose-700 ring-1 ring-rose-300" : "bg-slate-100 text-slate-400 hover:bg-rose-50"}`}
      >
        Wrong
      </button>
    </div>
  );
}

export function InsightsOverlay({
  open,
  onClose,
  insights,
  loading,
  companyName,
  onGenerate,
  onRegenerate,
  onFeedback,
}: InsightsOverlayProps) {
  const [feedbackGiven, setFeedbackGiven] = useState<"up" | "down" | null>(null);
  const [showImprovementPicker, setShowImprovementPicker] = useState(false);
  /* Animated pipeline steps while loading */
  const [steps, setSteps] = useState<PipelineStep[]>([
    { label: "Gathering company information...", status: "pending" },
    { label: "Generating insights...", status: "pending" },
    { label: "Reviewing & validating...", status: "pending" },
  ]);
  const [elapsed, setElapsed] = useState(0);
  const [startTime, setStartTime] = useState<number | null>(null);

  /* Progress simulation: advance steps based on elapsed time */
  useEffect(() => {
    if (!loading) {
      // When loading stops, mark all steps done
      setSteps((prev) => prev.map((s) => ({ ...s, status: "done" as StepStatus })));
      setStartTime(null);
      return;
    }

    setStartTime(Date.now());
    setElapsed(0);

    // Initial state: step 1 active
    setSteps([
      { label: "Gathering company information...", status: "active" },
      { label: "Generating insights...", status: "pending" },
      { label: "Reviewing & validating...", status: "pending" },
    ]);

    // Advance to step 2 after ~5s
    const t1 = setTimeout(() => {
      setSteps([
        { label: "Gathering company information...", status: "done" },
        { label: "Generating insights...", status: "active" },
        { label: "Reviewing & validating...", status: "pending" },
      ]);
    }, 5000);

    // Advance to step 3 after ~20s
    const t2 = setTimeout(() => {
      setSteps([
        { label: "Gathering company information...", status: "done" },
        { label: "Generating insights...", status: "done" },
        { label: "Reviewing & validating...", status: "active" },
      ]);
    }, 20000);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [loading]);

  /* Elapsed timer */
  useEffect(() => {
    if (!startTime) return;
    const interval = setInterval(
      () => setElapsed(Math.floor((Date.now() - startTime) / 1000)),
      1000,
    );
    return () => clearInterval(interval);
  }, [startTime]);

  /* Close on Escape key */
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-[2px]"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="w-full max-w-3xl max-h-[85vh] overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-100 bg-white/95 backdrop-blur-sm px-6 py-4 rounded-t-2xl">
            <div className="flex items-center gap-2.5">
              <div className="h-8 w-8 rounded-lg bg-indigo-50 flex items-center justify-center">
                <Sparkles className="h-4 w-4 text-indigo-500" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
                  AI Insights
                  <span className="text-[8px] font-bold bg-amber-100 text-amber-600 px-1.5 py-0.5 rounded-full uppercase tracking-widest">Alpha</span>
                </h3>
                <p className="text-[11px] text-slate-400">{companyName}</p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {insights && onRegenerate && (
                <button
                  onClick={() => { setFeedbackGiven(null); setShowImprovementPicker(false); onRegenerate(); }}
                  disabled={loading}
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-indigo-50 hover:text-indigo-600 transition-colors disabled:opacity-50"
                  title="Regenerate insights"
                >
                  <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                </button>
              )}
              <button
                onClick={onClose}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="p-6">
            {/* ── Feedback bar (top of content, only when insights exist) ── */}
            {insights && !loading && (
              <div className="mb-4 rounded-lg border border-slate-100 bg-slate-50/50 p-3">
                {!feedbackGiven ? (
                  <>
                    {/* Step 1: Show URLs + ask if correct */}
                    {!showImprovementPicker ? (
                      <div className="space-y-2.5">
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
                          {insights.website_url && (
                            <span className="inline-flex items-center gap-1">
                              <Globe className="h-3 w-3 text-slate-400" />
                              <a href={insights.website_url.startsWith("http") ? insights.website_url : `https://${insights.website_url}`} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline truncate max-w-[200px]">
                                {insights.website_url.replace(/^https?:\/\//, "")}
                              </a>
                            </span>
                          )}
                          {insights.linkedin_url && (
                            <span className="inline-flex items-center gap-1">
                              <Linkedin className="h-3 w-3 text-blue-500" />
                              <a href={insights.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline truncate max-w-[200px]">
                                {insights.linkedin_url.replace(/^https?:\/\/www\.linkedin\.com\/company\//, "")}
                              </a>
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-500">Is this correct?</span>
                          <button
                            onClick={() => { setFeedbackGiven("up"); onFeedback?.({ overall: "up", websiteCorrect: true, linkedinCorrect: true, insightCorrect: true }); }}
                            className="inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100 transition-colors"
                          >
                            <ThumbsUp className="h-3 w-3" /> Looks good
                          </button>
                          <button
                            onClick={() => setShowImprovementPicker(true)}
                            className="inline-flex items-center gap-1 rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1 text-[11px] font-medium text-rose-700 hover:bg-rose-100 transition-colors"
                          >
                            <ThumbsDown className="h-3 w-3" /> Needs improvement
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* Step 2: Ask what needs improvement */
                      <div className="space-y-2.5">
                        <p className="text-xs font-medium text-slate-600">What needs improvement?</p>
                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => { setFeedbackGiven("down"); onFeedback?.({ overall: "down", websiteCorrect: false, linkedinCorrect: undefined, insightCorrect: undefined }); if (onRegenerate) setTimeout(() => onRegenerate(), 1500); }}
                            className={`rounded-md border px-3 py-1.5 text-[11px] font-medium transition-colors border-rose-200 text-rose-700 hover:bg-rose-100 bg-rose-50`}
                          >
                            <Globe className="h-3 w-3 inline mr-1" /> Wrong website
                          </button>
                          <button
                            onClick={() => { setFeedbackGiven("down"); onFeedback?.({ overall: "down", websiteCorrect: undefined, linkedinCorrect: false, insightCorrect: undefined }); if (onRegenerate) setTimeout(() => onRegenerate(), 1500); }}
                            className={`rounded-md border px-3 py-1.5 text-[11px] font-medium transition-colors border-rose-200 text-rose-700 hover:bg-rose-100 bg-rose-50`}
                          >
                            <Linkedin className="h-3 w-3 inline mr-1" /> Wrong LinkedIn
                          </button>
                          <button
                            onClick={() => { setFeedbackGiven("down"); onFeedback?.({ overall: "down", websiteCorrect: undefined, linkedinCorrect: undefined, insightCorrect: false }); if (onRegenerate) setTimeout(() => onRegenerate(), 1500); }}
                            className={`rounded-md border px-3 py-1.5 text-[11px] font-medium transition-colors border-rose-200 text-rose-700 hover:bg-rose-100 bg-rose-50`}
                          >
                            <Sparkles className="h-3 w-3 inline mr-1" /> Wrong insights text
                          </button>
                          <button
                            onClick={() => { setFeedbackGiven("down"); onFeedback?.({ overall: "down", websiteCorrect: false, linkedinCorrect: false, insightCorrect: false }); if (onRegenerate) setTimeout(() => onRegenerate(), 1500); }}
                            className={`rounded-md border px-3 py-1.5 text-[11px] font-medium transition-colors border-rose-200 text-rose-700 hover:bg-rose-100 bg-rose-50`}
                          >
                            Everything is wrong
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                ) : feedbackGiven === "up" ? (
                  <div className="flex items-center gap-2 text-xs text-emerald-600">
                    <CheckCircle2 className="h-3.5 w-3.5" /> Thanks — confirmed correct!
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin text-indigo-500" /> Regenerating with your feedback...
                  </div>
                )}
              </div>
            )}

            {/* Loading state */}
            {loading && !insights && (
              <div className="py-4">
                <StepIndicator steps={steps} />
                <div className="mt-6 pt-4 border-t border-slate-100">
                  <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full animate-pulse"
                      style={{
                        width: `${Math.min(95, elapsed * 1.5)}%`,
                        transition: "width 1s ease",
                      }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-slate-400 mt-1.5">
                    <span>{elapsed}s elapsed</span>
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-1.5 w-1.5 rounded-full bg-indigo-400 animate-pulse" />
                      Working...
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Insights display */}
            {insights && (
              <div className="space-y-3">
                <InsightSection
                  icon={<Building2 className="h-4 w-4" />}
                  title="What they do"
                  content={insights.business_description}
                />
                <InsightSection
                  icon={<ShoppingBag className="h-4 w-4" />}
                  title="Products & Services"
                  content={insights.products_services}
                />
                <InsightSection
                  icon={<Users className="h-4 w-4" />}
                  title="Target Customers"
                  content={insights.target_customers}
                />
                <InsightSection
                  icon={<Trophy className="h-4 w-4" />}
                  title="Market Position"
                  content={insights.competitive_position}
                />
                <InsightSection
                  icon={<Clock className="h-4 w-4" />}
                  title="Company History"
                  content={insights.company_history}
                />

                {/* Key Management */}
                {insights.key_management && insights.key_management.length > 0 && (
                  <div className="rounded-lg border border-slate-100 bg-slate-50/50 p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Users className="h-4 w-4 text-slate-400" />
                      <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Key Management</h4>
                    </div>
                    <div className="space-y-1.5">
                      {insights.key_management.map((person, i) => (
                        <div key={i} className="flex items-center gap-2 text-sm">
                          <span className="font-medium text-slate-700">{person.name}</span>
                          {person.role && <span className="text-xs text-slate-400">— {person.role}</span>}
                          {person.linkedin_url && (
                            <a
                              href={person.linkedin_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="ml-auto text-blue-500 hover:text-blue-700 transition-colors"
                            >
                              <Linkedin className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Group context note */}
                {insights.group_context && (
                  <p className="text-xs text-slate-400 italic px-1">
                    Part of: {insights.group_context}
                  </p>
                )}

                {/* Links */}
                {(insights.website_url || insights.linkedin_url) && (
                  <div className="flex flex-wrap gap-3 pt-2">
                    {insights.website_url && (
                      <a
                        href={
                          insights.website_url.startsWith("http")
                            ? insights.website_url
                            : `https://${insights.website_url}`
                        }
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 transition-colors rounded-md border border-indigo-100 bg-indigo-50/50 px-3 py-1.5"
                      >
                        <Globe className="h-3.5 w-3.5" />
                        Website
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                    {insights.linkedin_url && (
                      <a
                        href={insights.linkedin_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-800 transition-colors rounded-md border border-blue-100 bg-blue-50/50 px-3 py-1.5"
                      >
                        <Linkedin className="h-3.5 w-3.5" />
                        LinkedIn
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                )}

                {/* Feedback moved to top of overlay */}
              </div>
            )}

            {/* Empty state — no insights, not loading */}
            {!insights && !loading && (
              <div className="py-8 text-center">
                <div className="mx-auto mb-4 h-12 w-12 rounded-full bg-indigo-50 flex items-center justify-center">
                  <Sparkles className="h-6 w-6 text-indigo-400" />
                </div>
                <p className="text-sm text-slate-600 mb-1">
                  No AI insights available yet
                </p>
                <p className="text-xs text-slate-400 mb-4">
                  Generate a structured company intelligence brief using AI
                </p>
                <button
                  onClick={onGenerate}
                  className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors"
                >
                  <Sparkles className="h-4 w-4" />
                  Generate Insights
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
