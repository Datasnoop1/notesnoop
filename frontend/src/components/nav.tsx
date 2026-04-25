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
    if (href === "/search") return pathname === "/search";
    return pathname.startsWith(href);
  }

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "?";
  const isLanding = pathname === "/";
  const hideHeaderSearch = isLanding || pathname === "/search";

  return (
    <header className="sticky top-0 z-50 glass-chrome border-b border-[#E3EAF4]">
      <div className="max-w-[1280px] mx-auto px-4 sm:px-6">
        <div className="flex items-center h-[60px] gap-6">

          {/* Brand — shown on every page including landing */}
          <Link href="/" className="flex items-center gap-2.5 shrink-0 group">
            <img src={logoPath} alt="Datasnoop" width={36} height={36} className="shrink-0 group-hover:scale-105 transition-transform rounded-md bg-white/95" />
            <span className="text-[15px] font-semibold tracking-tight">
              <span className="text-[#07142F]">data</span>
              <span className="text-[#0B5CFF]">snoop</span>
            </span>
            <span className="text-[9px] font-bold bg-[#EEF3FF] text-[#0B5CFF] px-1.5 py-0.5 rounded-full uppercase tracking-widest">Beta</span>
          </Link>

          {/* Center: inline search (non-landing, non-search pages) */}
          {!hideHeaderSearch && (
            <div className="flex-1 min-w-0 max-w-sm hidden md:block">
              <HeaderSearch />
            </div>
          )}

          {/* Desktop nav links */}
          <nav className={`hidden md:flex items-center gap-1 ${hideHeaderSearch ? "flex-1 justify-center" : ""}`}>
            {NAV_LINKS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`relative px-3 py-1.5 text-[13.5px] font-medium rounded-lg transition-colors ${
                  isActive(item.href)
                    ? "text-[#0B5CFF] bg-[#EEF3FF]"
                    : "text-[#5F6B85] hover:text-[#07142F] hover:bg-[#F3F7FF]"
                }`}
              >
                {item.label}
                {isActive(item.href) && (
                  <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-[#0B5CFF] rounded-full" />
                )}
              </Link>
            ))}
          </nav>

          {/* Right side */}
          <div className="flex items-center gap-2 ml-auto shrink-0">

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
                  className="relative p-2 rounded-lg text-[#5F6B85] hover:text-[#07142F] hover:bg-[#F3F7FF] transition-colors"
                >
                  <Bell className="w-4 h-4" />
                  {notifCount > 0 && (
                    <span className="absolute top-1 right-1 bg-rose-500 text-white text-[8px] font-bold rounded-full w-3.5 h-3.5 flex items-center justify-center">
                      {notifCount > 9 ? "9+" : notifCount}
                    </span>
                  )}
                </button>
                {showNotifs && (
                  <div className="absolute right-0 mt-2 w-72 bg-white border border-[#E3EAF4] rounded-xl shadow-lg z-50 max-h-64 overflow-y-auto">
                    <div className="px-3 py-2.5 border-b border-[#E3EAF4] text-[11px] font-semibold text-[#5F6B85] uppercase tracking-wider">
                      {t("nav.dataUpdates")}
                    </div>
                    {notifs.length === 0 ? (
                      <div className="px-3 py-5 text-xs text-[#7B8498] text-center">{t("nav.noNewUpdates")}</div>
                    ) : (
                      notifs.map((n, i) => (
                        <a
                          key={i}
                          href={`/company/${n.enterprise_number}`}
                          className="block px-3 py-2.5 hover:bg-[#F8FAFD] border-b border-[#E3EAF4] last:border-0 transition-colors"
                          onClick={() => setShowNotifs(false)}
                        >
                          <div className="text-xs font-medium text-[#07142F] truncate">{n.name}</div>
                          <div className="text-[10px] text-[#7B8498]">
                            New FY{n.fiscal_year} data loaded {n.loaded_at?.slice(0, 10)}
                          </div>
                        </a>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Language + feedback (hidden on landing) */}
            {!isLanding && (
              <div className="hidden md:flex items-center gap-1">
                <FeedbackButtons />
              </div>
            )}

            <div className="hidden md:block">
              <LanguageSwitcher />
            </div>

            <div className="hidden md:block w-px h-5 bg-[#E3EAF4]" />

            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger className="hidden md:flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-[#F3F7FF] transition-colors">
                  <div className="w-7 h-7 rounded-full bg-[#0B5CFF] text-white flex items-center justify-center text-[11px] font-bold">
                    {initials}
                  </div>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48 border-[#E3EAF4]">
                  <DropdownMenuItem onClick={() => router.push("/account")} className="cursor-pointer text-[13px]">
                    <User className="w-4 h-4 mr-2 text-[#5F6B85]" />
                    {t("nav.accountSettings")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleSignOut} className="cursor-pointer text-[13px]">
                    <LogOut className="w-4 h-4 mr-2 text-[#5F6B85]" />
                    {t("nav.signOut")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <Link href="/login">
                <Button variant="outline" size="sm" className="inline-flex text-[12px] md:text-[13px] h-8 md:h-9 px-2.5 md:px-3 border-[#E3EAF4] text-[#07142F] hover:bg-[#F3F7FF]">
                  {t("nav.signIn")}
                </Button>
              </Link>
            )}

            {/* Mobile hamburger */}
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger>
                <span className="md:hidden inline-flex items-center justify-center rounded-lg p-2 min-w-[44px] min-h-[44px] text-[#5F6B85] hover:bg-[#F3F7FF]">
                  <Menu className="h-5 w-5" />
                </span>
              </SheetTrigger>
              <SheetContent side="left" className="w-72 border-[#E3EAF4]">
                <SheetTitle className="flex items-center gap-2 text-[15px] font-semibold">
                  <img src={logoPath} alt="Datasnoop" width={32} height={32} className="rounded-md bg-white/95" />
                  <span><span className="text-[#07142F]">data</span><span className="text-[#0B5CFF]">snoop</span></span>
                </SheetTitle>
                <div className="mt-6 flex flex-col gap-1">
                  {NAV_LINKS.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setOpen(false)}
                      className={`flex items-center px-3 py-2.5 rounded-lg text-[14px] font-medium transition-colors ${
                        isActive(item.href)
                          ? "text-[#0B5CFF] bg-[#EEF3FF]"
                          : "text-[#5F6B85] hover:text-[#07142F] hover:bg-[#F3F7FF]"
                      }`}
                    >
                      {item.label}
                    </Link>
                  ))}

                  <div className="border-t border-[#E3EAF4] mt-3 pt-3">
                    <div className="px-3 mb-2 text-[10px] font-bold text-[#7B8498] uppercase tracking-wider">Language</div>
                    <div className="px-3">
                      <LanguageSwitcher />
                    </div>
                  </div>

                  <div className="pt-2">
                    <div className="px-3 mb-2 text-[10px] font-bold text-[#7B8498] uppercase tracking-wider">Feedback</div>
                    <div className="px-3 flex flex-col items-start gap-1">
                      <FeedbackButtons />
                    </div>
                  </div>

                  {user && (
                    <div className="border-t border-[#E3EAF4] mt-3 pt-3">
                      <button
                        onClick={() => { handleSignOut(); setOpen(false); }}
                        className="w-full flex items-center px-3 py-2.5 rounded-lg text-sm font-medium text-rose-600 hover:bg-rose-50"
                      >
                        <LogOut className="w-4 h-4 mr-2" />
                        {t("nav.signOut")}
                      </button>
                    </div>
                  )}

                  {!user && (
                    <div className="border-t border-[#E3EAF4] mt-3 pt-3 px-3">
                      <Link href="/login" onClick={() => setOpen(false)}>
                        <Button variant="outline" className="w-full text-[13px] border-[#E3EAF4]">{t("nav.signIn")}</Button>
                      </Link>
                    </div>
                  )}
                </div>
              </SheetContent>
            </Sheet>
          </div>
        </div>

        {/* Mobile dot-nav — visible only on non-landing, non-screener pages */}
        {!isLanding && !pathname.startsWith("/screener") && (
          <div className="md:hidden border-t border-[#E3EAF4]">
            <nav className="flex items-center gap-0 py-1 text-[13px] overflow-x-auto scrollbar-none">
              {NAV_LINKS.slice(0, 4).map((item, idx) => (
                <React.Fragment key={item.href}>
                  {idx > 0 && <span className="text-[#E3EAF4] select-none shrink-0" aria-hidden>·</span>}
                  <Link
                    href={item.href}
                    className={`px-3 py-2.5 min-h-[44px] inline-flex items-center rounded-lg transition-colors shrink-0 font-medium ${
                      isActive(item.href)
                        ? "text-[#0B5CFF]"
                        : "text-[#5F6B85] hover:text-[#07142F]"
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
