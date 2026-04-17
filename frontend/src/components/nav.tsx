"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React, { useState, useEffect } from "react";
import { Menu, LogOut, User, Bell, Search } from "lucide-react";
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

  const MOBILE_NAV = [
    { label: t("nav.favourites"), href: "/favourites" },
    { label: t("nav.compare"), href: "/compare" },
    { label: t("nav.aggregate"), href: "/aggregate" },
    { label: t("nav.screener"), href: "/screener" },
  ];

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
  const [headerQuery, setHeaderQuery] = useState("");

  function handleHeaderSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = headerQuery.trim();
    if (q.length < 2) return;
    router.push(`/search?q=${encodeURIComponent(q)}`);
    setHeaderQuery("");
  }

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
              <span className="text-[7px] font-bold bg-indigo-100 text-indigo-600 px-1.5 py-0.5 rounded-full uppercase tracking-widest">Beta</span>
            </Link>
          )}

          {/* Inline search — hidden on landing and on /search (each owns its own input) */}
          {!hideHeaderSearch && (
            <form onSubmit={handleHeaderSearch} className="flex-1 mx-3 sm:mx-4 md:mx-6 max-w-md">
              <div className="group relative flex items-center rounded-full border border-gray-200 bg-white hover:border-gray-300 focus-within:border-gray-400 focus-within:shadow-[0_1px_6px_rgba(32,33,36,0.1)] transition-all">
                <Search className="absolute left-3 w-3.5 h-3.5 text-gray-400 pointer-events-none" aria-hidden />
                <input
                  type="text"
                  value={headerQuery}
                  onChange={(e) => setHeaderQuery(e.target.value)}
                  placeholder="Search"
                  aria-label="Search companies or persons"
                  className="w-full h-9 pl-9 pr-3 text-[13px] rounded-full bg-transparent focus:outline-none placeholder:text-gray-400 text-gray-900"
                  enterKeyHint="search"
                  autoCapitalize="off"
                  autoCorrect="off"
                />
              </div>
            </form>
          )}

          {/* Desktop nav — hidden on landing (links live under the search there).
              Text-link style with dot separators, matching the landing secondary-actions row. */}
          {!isLanding && (
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
          )}

          {/* Right side: feedback, notifications, auth */}
          <div className="flex items-center gap-1.5">
            <div className="hidden md:flex items-center gap-1 mr-0.5">
              <FeedbackButtons />
            </div>

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
              <Link href="/login">
                <Button variant="outline" size="sm" className="hidden md:inline-flex text-[13px]">
                  {t("nav.signIn")}
                </Button>
              </Link>
            )}

            {/* Mobile hamburger — hidden on landing (nav lives under the hero there,
                and the hero has no need for account controls above the fold) */}
            {!isLanding && (
              <Sheet open={open} onOpenChange={setOpen}>
                <SheetTrigger>
                  <span className="md:hidden inline-flex items-center justify-center rounded-md p-2 text-slate-600 hover:bg-slate-100">
                    <Menu className="h-5 w-5" />
                  </span>
                </SheetTrigger>
                <SheetContent side="left" className="w-64">
                  <SheetTitle className="flex items-center gap-2 text-base font-semibold text-slate-900">
                    <img src={logoPath} alt="Datasnoop" width={36} height={36} className="rounded-md bg-white/95" />
                    Datasnoop
                  </SheetTitle>
                  <nav className="mt-6 flex flex-col gap-1">
                    {/* Nav links are now in a dot-separated row below the header on
                        mobile non-landing pages, so we don't duplicate them here. */}
                    {user ? (
                      <button
                        onClick={() => { handleSignOut(); setOpen(false); }}
                        className="px-3 py-2.5 rounded-md text-sm font-medium text-red-600 hover:bg-red-50 text-left"
                      >
                        {t("nav.signOut")}
                      </button>
                    ) : (
                      <Link
                        href="/login"
                        onClick={() => setOpen(false)}
                        className="px-3 py-2.5 rounded-md text-sm font-medium text-indigo-600 hover:bg-indigo-50"
                      >
                        {t("nav.signIn")}
                      </Link>
                    )}
                  </nav>
                </SheetContent>
              </Sheet>
            )}
          </div>
        </div>

        {/* Mobile dot-nav — visible only on mobile non-landing pages, so the nav
            is still one tap away without opening the hamburger */}
        {!isLanding && (
          <div className="md:hidden border-t border-slate-100">
            <nav className="flex items-center justify-center gap-0 py-1.5 text-[12px] text-gray-600 overflow-x-auto">
              {NAV_LINKS.map((item, idx) => (
                <React.Fragment key={item.href}>
                  {idx > 0 && <span className="text-gray-300 select-none shrink-0" aria-hidden>·</span>}
                  <Link
                    href={item.href}
                    className={`px-2.5 py-1 rounded-md transition-colors shrink-0 ${
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
