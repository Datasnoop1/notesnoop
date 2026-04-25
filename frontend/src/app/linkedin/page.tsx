"use client";

import { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Upload, Search, Building2, Lock } from "lucide-react";
import Link from "next/link";
import { createClient } from "@/lib/supabase";

export default function LinkedInPage() {
  const [user, setUser] = useState<boolean>(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => setUser(!!data.user));
  }, []);

  return (
    <div className="mx-auto w-full max-w-[1200px] space-y-6">
      <div>
        <div className="flex items-center gap-3 mb-2">
          <svg className="w-6 h-6" viewBox="0 0 24 24" fill="#0A66C2"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
          <h1 className="text-2xl font-bold text-slate-900">LinkedIn Contacts</h1>
          <Badge variant="secondary" className="text-[10px] bg-amber-100 text-amber-700">Coming Soon</Badge>
        </div>
        <p className="text-sm text-slate-500">
          Import your LinkedIn connections and match them to Belgian companies in our database.
        </p>
      </div>

      {/* Feature preview */}
      <div className="grid gap-4">
        <Card className="bg-white border-l-4 border-l-[#0A66C2]">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-start gap-3">
              <Upload className="w-5 h-5 text-[#0A66C2] mt-0.5 shrink-0" />
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Import Connections</h3>
                <p className="text-xs text-slate-500 mt-1">
                  Connect your LinkedIn account to automatically import your professional network.
                  We match contacts to companies in our database based on their current employer.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-white border-l-4 border-l-brand">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-start gap-3">
              <Building2 className="w-5 h-5 text-brand mt-0.5 shrink-0" />
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Company Matching</h3>
                <p className="text-xs text-slate-500 mt-1">
                  See which of your contacts work at companies in our database.
                  Get instant access to financials, credit metrics, and company profiles
                  for companies in your network.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-white border-l-4 border-l-emerald-500">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-start gap-3">
              <Search className="w-5 h-5 text-emerald-500 mt-0.5 shrink-0" />
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Network Intelligence</h3>
                <p className="text-xs text-slate-500 mt-1">
                  Discover connections at target companies for warm introductions.
                  Filter your network by company size, sector, and financial health.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* CTA */}
      <Card className="bg-gradient-to-r from-[#0A66C2]/5 to-brand-soft/50 border-[#0A66C2]/20">
        <CardContent className="pt-5 pb-5 text-center">
          <Lock className="w-8 h-8 text-slate-300 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-slate-900 mb-1">
            This feature is under development
          </h3>
          <p className="text-xs text-slate-500 mb-4">
            LinkedIn Contacts integration is coming in a future update.
            We are working on LinkedIn API integration and approval.
          </p>
          {!user && (
            <Link href="/login">
              <Button className="bg-brand hover:bg-[color:var(--brand-ink)]">
                Sign in to get notified
              </Button>
            </Link>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
