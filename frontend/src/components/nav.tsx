"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React, { useState, useEffect } from "react";
import { Menu, LogOut, User, Bell } from "lucide-react";
import HeaderSearch from "@/components/header-search";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { createClient } from "@/lib/supabase";
import FeedbackButtons from "@/components/feedback-buttons";
import LanguageSwitcher from "@/components/language-switcher";
import { useTranslation } from "@/components/language-provider";
import { getNotifications, markNotificationsRead } from "@/lib/api";
import type { FavNotification } from "@/lib/api";
import type { User as SupabaseUser } from "@supabase/supabase-js";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<SupabaseUser | null>(null);
  const [notifCount, setNotifCount] = useState(0);
  const [notifs, setNotifs] = useState<FavNotification[]>([]);
  const [showNotifs, setShowNotifs] = useState(false);
  const [logoPath, setLogoPath] = useState("/logos/dog-telescope-clean.jpeg");

  const NAV_LINKS = [
    { label: t("nav.favourites"), href: "/favourites" },
    { label: t("nav.compare"), href: "/compare" },
    { label: t("nav.aggregate"), href: "/aggregate" },
    { label: t("nav.screener"), href: "/screener" },
  ];

  // Mobile dot-row uses NAV_LINKS — keep one source of truth.

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => setUser(data.user));

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event, session) => {
        setUser(session?.user ?? null);
        if (event === "SIGNED_IN" && session?.access_token) {
          fetch("/api/dashboard", {
            headers: { Authorization: `Bearer ${session.access_token}` },
          }).catch(() => {});
        }
      }
    );
    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!user) { setNotifCount(0); setNotifs([]); return; }
    getNotifications()
      .then((data) => { setNotifCount(data.count); setNotifs(data.notifications); })
      .catch(() => {});
  }, [user]);

  // Fetch site logo from public config (once on mount)
  useEffect(() => {
    fetch(`${API_BASE}/api/site-config`)
      .then((r) => r.json())
      .then((data) => {
        if (data.site_logo) setLogoPath(data.site_logo);
      })
      .catch(() => {});
  }, []);

  async function handleSignOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    setUser(null);
    router.push("/login");
  }

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "?";
  const isLanding = pathname === "/";
  const hideHeaderSearch = isLanding || pathname === "/search";

  return (
    <header className="sticky top-0 z-50 bg-white border-b border-slate-200/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className={`flex items-center h-16 ${isLanding ? "justify-center" : "justify-between"}`}>
          {/* Brand — hidden on landing (brand lives in the hero there) */}
          {isLanding ? (
            <span aria-hidden className="w-0" />
          ) : (
            <Link href="/" className="flex items-center gap-2.5 group shrink-0">
              <img src={logoPath} alt="Datasnoop" width={44} height={44} className="shrink-0 group-hover:scale-105 transition-transform rounded-md bg-white/95" />
              <span className="text-base font-semibold text-slate-900 tracking-tight">
                Datasnoop
              </span>
              <span className="text-[9px] sm:text-[10px] font-bold bg-indigo-100 text-indigo-600 px-1.5 py-0.5 rounded-full uppercase tracking-widest">Beta</span>
            </Link>
          )}

          {/* Inline search with grouped autocomplete — hidden on landing
              (brand + hero own the input) and on /search (the page owns
              its own big input). */}
          {!hideHeaderSearch && <HeaderSearch />}

          {/* Desktop nav — Screener / Favourites / Compare / Aggregate.
              Shown on landing AND non-landing so the primary actions are
              always one tap away. Text-link style with dot separators. */}
          <nav className="hidden md:flex items-center gap-0 shrink-0 text-[13px] text-gray-600">
            {NAV_LINKS.map((item, idx) => (
              <React.Fragment key={item.href}>
                {idx > 0 && <span className="text-gray-300 select-none" aria-hidden>·</span>}
                <Link
                  href={item.href}
                  className={`px-3 py-2 rounded-md transition-colors ${
                    isActive(item.href)
                      ? "text-gray-900 font-medium"
                      : "hover:bg-gray-50 hover:text-gray-900"
                  }`}
                >
                  {item.label}
                </Link>
              </React.Fragment>
            ))}
          </nav>

          {/* Right side: feedback, notifications, auth.
              On landing, feedback + sign-in are rendered in page.tsx
              (under the search bar) — header keeps just bell + language. */}
          <div className="flex items-center gap-1.5">
            {!isLanding && (
              <div className="hidden md:flex items-center gap-1 mr-0.5">
                <FeedbackButtons />
              </div>
            )}

            {/* Notification bell */}
            {user && (
              <div className="hidden md:block relative">
                <button
                  onClick={() => {
                    setShowNotifs(!showNotifs);
                    if (notifCount > 0) {
                      markNotificationsRead().then(() => setNotifCount(0)).catch(() => {});
                    }
                  }}
                  className="relative p-2 rounded-md hover:bg-slate-50 transition-colors"
                >
                  <Bell className="w-4 h-4 text-slate-500" />
                  {notifCount > 0 && (
                    <span className="absolute top-1 right-1 bg-rose-500 text-white text-[8px] font-bold rounded-full w-3.5 h-3.5 flex items-center justify-center">
                      {notifCount > 9 ? "9+" : notifCount}
                    </span>
                  )}
                </button>
                {showNotifs && (
                  <div className="absolute right-0 mt-1 w-72 bg-white border rounded-xl shadow-xl shadow-slate-200/50 z-50 max-h-64 overflow-y-auto">
                    <div className="px-3 py-2.5 border-b text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      {t("nav.dataUpdates")}
                    </div>
                    {notifs.length === 0 ? (
                      <div className="px-3 py-5 text-xs text-slate-400 text-center">{t("nav.noNewUpdates")}</div>
                    ) : (
                      notifs.map((n, i) => (
                        <a
                          key={i}
                          href={`/company/${n.enterprise_number}`}
                          className="block px-3 py-2.5 hover:bg-slate-50 border-b border-slate-50 last:border-0 transition-colors"
                          onClick={() => setShowNotifs(false)}
                        >
                          <div className="text-xs font-medium text-slate-800 truncate">{n.name}</div>
                          <div className="text-[10px] text-slate-400">
                            New FY{n.fiscal_year} data loaded {n.loaded_at?.slice(0, 10)}
                          </div>
                        </a>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="hidden md:block">
              <LanguageSwitcher />
            </div>

            <div className="hidden md:block w-px h-5 bg-slate-200" />

            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger className="hidden md:flex items-center px-2 py-1.5 rounded-md hover:bg-slate-50 transition-colors">
                  <div className="w-7 h-7 rounded-full bg-indigo-600 text-white flex items-center justify-center text-[11px] font-bold">
                    {initials}
                  </div>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuItem onClick={() => router.push("/account")} className="cursor-pointer">
                    <User className="w-4 h-4 mr-2" />
                    {t("nav.accountSettings")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleSignOut} className="cursor-pointer">
                    <LogOut className="w-4 h-4 mr-2" />
                    {t("nav.signOut")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              /* Sign-in is visible on every page including landing AND
                 on mobile, per operator preference: "keep login on top
                 (not in hamburger)". The hamburger no longer carries
                 a Sign-in entry, so this button is the only path in. */
              <Link href="/login">
                <Button variant="outline" size="sm" className="inline-flex text-[12px] md:text-[13px] h-8 md:h-9 px-2.5 md:px-3">
                  {t("nav.signIn")}
                </Button>
              </Link>
            )}

            {/* Mobile hamburger — holds Language + Feedback on phone (those
                are md:flex-only in the header). Sign-in lives in the header
                bar on every viewport (per operator preference). Nav links
                live in the bottom dot-row on non-landing, /screener excepted. */}
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger>
                <span className="md:hidden inline-flex items-center justify-center rounded-md p-2.5 min-w-[44px] min-h-[44px] text-slate-600 hover:bg-slate-100">
                  <Menu className="h-5 w-5" />
                </span>
              </SheetTrigger>
              <SheetContent side="left" className="w-64">
                <SheetTitle className="flex items-center gap-2 text-base font-semibold text-slate-900">
                  <img src={logoPath} alt="Datasnoop" width={36} height={36} className="rounded-md bg-white/95" />
                  Datasnoop
                </SheetTitle>
                <div className="mt-6 flex flex-col gap-4">
                  {/* Sign in lives only in the top header per operator
                      preference; the hamburger keeps Account just for
                      signed-in users (Sign out). */}
                  {user && (
                    <div>
                      <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1 px-3">Account</div>
                      <button
                        onClick={() => { handleSignOut(); setOpen(false); }}
                        className="w-full px-3 py-2.5 rounded-md text-sm font-medium text-red-600 hover:bg-red-50 text-left"
                      >
                        {t("nav.signOut")}
                      </button>
                    </div>
                  )}

                  <div>
                    <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1 px-3">Language</div>
                    <div className="px-3">
                      <LanguageSwitcher />
                    </div>
                  </div>

                  <div>
                    <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1 px-3">Feedback</div>
                    <div className="px-3 flex flex-col items-start gap-1">
                      <FeedbackButtons />
                    </div>
                  </div>
                </div>
              </SheetContent>
            </Sheet>
          </div>
        </div>

        {/* Mobile dot-nav — visible only on mobile non-landing pages.
            Hidden on /screener because the screener owns the full mobile
            viewport (split-pane filters/results) and the dot-row collides
            with its top toolbar. */}
        {!isLanding && !pathname.startsWith("/screener") && (
          <div className="md:hidden border-t border-slate-100">
            <nav className="flex items-center justify-center gap-0 py-1 text-[13px] text-gray-600 overflow-x-auto">
              {NAV_LINKS.map((item, idx) => (
                <React.Fragment key={item.href}>
                  {idx > 0 && <span className="text-gray-300 select-none shrink-0" aria-hidden>·</span>}
                  <Link
                    href={item.href}
                    className={`px-3 py-2.5 min-h-[44px] inline-flex items-center rounded-md transition-colors shrink-0 ${
                      isActive(item.href)
                        ? "text-gray-900 font-medium"
                        : "hover:text-gray-900"
                    }`}
                  >
                    {item.label}
                  </Link>
                </React.Fragment>
              ))}
            </nav>
          </div>
        )}
      </div>
    </header>
  );
}
