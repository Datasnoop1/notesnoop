"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React, { useState, useEffect, useRef } from "react";
import { Menu, LogOut, User, Bell, Search } from "lucide-react";
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
import { useUser as useClerkUser, useClerk } from "@clerk/nextjs";

const USE_CLERK = process.env.NEXT_PUBLIC_USE_CLERK === "true";
import FeedbackButtons from "@/components/feedback-buttons";
import LanguageSwitcher from "@/components/language-switcher";
import { useTranslation } from "@/components/language-provider";
import { getNotifications, markNotificationsRead } from "@/lib/api";
import type { FavNotification } from "@/lib/api";
import type { User as SupabaseUser } from "@supabase/supabase-js";

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<SupabaseUser | null>(null);
  const [notifCount, setNotifCount] = useState(0);
  const [notifs, setNotifs] = useState<FavNotification[]>([]);
  const [showNotifs, setShowNotifs] = useState(false);
  const notifContainerRef = useRef<HTMLDivElement | null>(null);
  const notifContainerMobileRef = useRef<HTMLDivElement | null>(null);
  const logoPath = "/logos/datasnoop-brand.png";

  const NAV_LINKS = [
    { label: t("nav.favourites"), href: "/favourites" },
    { label: t("nav.compare"), href: "/compare" },
    { label: t("nav.aggregate"), href: "/aggregate" },
    { label: t("nav.screener"), href: "/screener" },
  ];

  // Clerk path: useUser hook always called (it's safe — only resolves when
  // ClerkProvider is in the tree, which it is when USE_CLERK=true). When
  // USE_CLERK=false, ClerkProvider isn't in the tree and useClerkUser still
  // returns the unauthenticated default; we ignore it and rely on Supabase.
  const clerkUserHook = useClerkUser();
  const clerkSignOut = useClerk().signOut;

  useEffect(() => {
    if (USE_CLERK) {
      // Mirror Clerk user → SupabaseUser-shaped object so the rest of the
      // component (which expects { email }) keeps working unchanged.
      const cu = clerkUserHook.user;
      if (clerkUserHook.isLoaded && cu) {
        const email = cu.primaryEmailAddress?.emailAddress
          ?? cu.emailAddresses?.[0]?.emailAddress
          ?? "";
        setUser({ id: cu.id, email } as unknown as SupabaseUser);
      } else if (clerkUserHook.isLoaded) {
        setUser(null);
      }
      return; // skip Supabase wiring entirely
    }
    const supabase = createClient();
    supabase.auth.getUser()
      .then(({ data }) => setUser(data.user))
      .catch(() => setUser(null));

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
  }, [clerkUserHook.isLoaded, clerkUserHook.user]);

  useEffect(() => {
    if (!user) { setNotifCount(0); setNotifs([]); return; }
    getNotifications()
      .then((data) => { setNotifCount(data.count); setNotifs(data.notifications); })
      .catch(() => {});
  }, [user]);

  // Close notifications dropdown on outside click or Escape.
  // Both mobile and desktop bells stay mounted (Tailwind's md:hidden /
  // hidden md:block toggles `display`, not the DOM tree), so we track
  // whichever node is visible by checking BOTH refs. Without this, the
  // click-outside test would fail on whichever viewport the second-
  // assigned ref doesn't represent.
  useEffect(() => {
    if (!showNotifs) return;
    const isInside = (target: Node) =>
      (notifContainerRef.current?.contains(target) ?? false) ||
      (notifContainerMobileRef.current?.contains(target) ?? false);
    const onMouseDown = (e: MouseEvent) => {
      if (!isInside(e.target as Node)) setShowNotifs(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowNotifs(false);
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [showNotifs]);

  async function handleSignOut() {
    if (USE_CLERK) {
      await clerkSignOut({ redirectUrl: "/login" });
      setUser(null);
      return;
    }
    const supabase = createClient();
    await supabase.auth.signOut();
    setUser(null);
    router.replace("/login");
  }

  function isActive(href: string) {
    if (href === "/search") return pathname === "/search";
    return pathname.startsWith(href);
  }

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "?";
  const isLanding = pathname === "/";
  const hideHeaderSearch = isLanding || pathname === "/search";

  return (
    <header className="sticky top-0 z-50 glass-chrome border-b border-[#E2E8F2] ds-safe-top">
      <div className="max-w-[1200px] mx-auto px-3 sm:px-6 lg:px-8 ds-safe-px">
        <div className="flex items-center gap-3 sm:gap-6 h-[64px] md:h-[80px]">

          {/* Brand — full wordmark + telescope dog mark. PNG is tightly
             cropped (994x279 — no whitespace), so a modest header box
             gives a strongly-visible mark. Mobile shrinks the mark so it
             leaves room for the search shortcut + hamburger on a 360px
             screen. */}
          <Link href="/" className="flex items-center gap-1.5 sm:gap-2 shrink-0 group min-w-0">
            <img
              src={logoPath}
              alt="DataSnoop"
              onError={(e) => { (e.currentTarget as HTMLImageElement).src = "/logos/dog-telescope-clean.jpeg"; }}
              className="h-10 sm:h-[58px] w-auto shrink-0 group-hover:opacity-90 transition-opacity"
              loading="eager"
              decoding="async"
            />
            <span className="hidden sm:inline-block text-[9px] font-bold bg-[#EAF5FF] text-[#1687E8] px-1.5 py-0.5 rounded-full uppercase tracking-widest">Beta</span>
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
                    ? "text-[#1687E8] bg-[#EAF5FF]"
                    : "text-[#5F6B85] hover:text-[#08132B] hover:bg-[#F3F6FB]"
                }`}
              >
                {item.label}
                {isActive(item.href) && (
                  <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-[#1687E8] rounded-full" />
                )}
              </Link>
            ))}
          </nav>

          {/* Right side */}
          <div className="flex items-center gap-1 sm:gap-2 ml-auto shrink-0">

            {/* Mobile search shortcut — visible everywhere except the
                /search page itself (where the page already has a big
                input bar). Tappable target meets WCAG 44px. */}
            {pathname !== "/search" && (
              <Link
                href="/search"
                aria-label={t("search.placeholder") || "Search"}
                className="md:hidden inline-flex items-center justify-center rounded-lg w-11 h-11 text-[#5F6B85] hover:bg-[#F3F6FB] active:bg-[#EAF5FF]"
              >
                <Search className="h-5 w-5" />
              </Link>
            )}

            {/* Mobile notification bell — surfaces the same dropdown
                that desktop users see. Notifications were previously
                hidden on phones, hiding fresh-data signals from PE
                analysts who triage on mobile. */}
            {user && (
              <div className="md:hidden relative" ref={notifContainerMobileRef}>
                <button
                  onClick={() => {
                    setShowNotifs(!showNotifs);
                    if (notifCount > 0) {
                      markNotificationsRead().then(() => setNotifCount(0)).catch(() => {});
                    }
                  }}
                  aria-label={t("nav.dataUpdates") || "Updates"}
                  className="relative inline-flex items-center justify-center rounded-lg w-11 h-11 text-[#5F6B85] hover:bg-[#F3F6FB] active:bg-[#EAF5FF]"
                >
                  <Bell className="h-5 w-5" />
                  {notifCount > 0 && (
                    <span className="absolute top-1.5 right-1.5 bg-rose-500 text-white text-[8px] font-bold rounded-full w-3.5 h-3.5 flex items-center justify-center">
                      {notifCount > 9 ? "9+" : notifCount}
                    </span>
                  )}
                </button>
                {showNotifs && (
                  <div className="absolute right-0 mt-2 w-[min(calc(100vw-1rem),20rem)] bg-white border border-[#E2E8F2] rounded-xl shadow-lg z-50 max-h-[60vh] overflow-y-auto">
                    <div className="px-3 py-2.5 border-b border-[#E2E8F2] text-[11px] font-semibold text-[#5F6B85] uppercase tracking-wider">
                      {t("nav.dataUpdates")}
                    </div>
                    {notifs.length === 0 ? (
                      <div className="px-3 py-5 text-xs text-[#8791A6] text-center">{t("nav.noNewUpdates")}</div>
                    ) : (
                      notifs.map((n, i) => (
                        <a
                          key={i}
                          href={`/company/${n.enterprise_number}`}
                          className="block px-3 py-3 hover:bg-[#F7F9FC] active:bg-[#EAF5FF] border-b border-[#E2E8F2] last:border-0 transition-colors"
                          onClick={() => setShowNotifs(false)}
                        >
                          <div className="text-[13px] font-medium text-[#08132B] truncate">{n.name}</div>
                          <div className="text-[11px] text-[#8791A6]">
                            New FY{n.fiscal_year} data loaded {n.loaded_at?.slice(0, 10)}
                          </div>
                        </a>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Notification bell — desktop */}
            {user && (
              <div ref={notifContainerRef} className="hidden md:block relative">
                <button
                  onClick={() => {
                    setShowNotifs(!showNotifs);
                    if (notifCount > 0) {
                      markNotificationsRead().then(() => setNotifCount(0)).catch(() => {});
                    }
                  }}
                  className="relative p-2 rounded-lg text-[#5F6B85] hover:text-[#08132B] hover:bg-[#F3F6FB] transition-colors"
                >
                  <Bell className="w-4 h-4" />
                  {notifCount > 0 && (
                    <span className="absolute top-1 right-1 bg-rose-500 text-white text-[8px] font-bold rounded-full w-3.5 h-3.5 flex items-center justify-center">
                      {notifCount > 9 ? "9+" : notifCount}
                    </span>
                  )}
                </button>
                {showNotifs && (
                  <div className="absolute right-0 mt-2 w-72 bg-white border border-[#E2E8F2] rounded-xl shadow-lg z-50 max-h-64 overflow-y-auto">
                    <div className="px-3 py-2.5 border-b border-[#E2E8F2] text-[11px] font-semibold text-[#5F6B85] uppercase tracking-wider">
                      {t("nav.dataUpdates")}
                    </div>
                    {notifs.length === 0 ? (
                      <div className="px-3 py-5 text-xs text-[#8791A6] text-center">{t("nav.noNewUpdates")}</div>
                    ) : (
                      notifs.map((n, i) => (
                        <a
                          key={i}
                          href={`/company/${n.enterprise_number}`}
                          className="block px-3 py-2.5 hover:bg-[#F7F9FC] border-b border-[#E2E8F2] last:border-0 transition-colors"
                          onClick={() => setShowNotifs(false)}
                        >
                          <div className="text-xs font-medium text-[#08132B] truncate">{n.name}</div>
                          <div className="text-[10px] text-[#8791A6]">
                            New FY{n.fiscal_year} data loaded {n.loaded_at?.slice(0, 10)}
                          </div>
                        </a>
                      ))
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Feedback (mail + donate) — shown on every page including landing */}
            <div className="hidden md:flex items-center gap-1">
              <FeedbackButtons />
            </div>

            <div className="hidden md:block">
              <LanguageSwitcher />
            </div>

            <div className="hidden md:block w-px h-5 bg-[#E2E8F2]" />

            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger className="hidden md:flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-[#F3F6FB] transition-colors">
                  <div className="w-7 h-7 rounded-full bg-[#1687E8] text-white flex items-center justify-center text-[11px] font-bold">
                    {initials}
                  </div>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48 border-[#E2E8F2]">
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
                <Button variant="outline" size="sm" className="inline-flex text-[12px] md:text-[13px] h-8 md:h-9 px-2.5 md:px-3 border-[#E2E8F2] text-[#08132B] hover:bg-[#F3F6FB]">
                  {t("nav.signIn")}
                </Button>
              </Link>
            )}

            {/* Mobile hamburger */}
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger>
                <span className="md:hidden inline-flex items-center justify-center rounded-lg p-2 min-w-[44px] min-h-[44px] text-[#5F6B85] hover:bg-[#F3F6FB] active:bg-[#EAF5FF]">
                  <Menu className="h-5 w-5" />
                </span>
              </SheetTrigger>
              <SheetContent side="left" className="w-[88vw] max-w-xs sm:w-80 border-[#E2E8F2] p-5 ds-safe-top ds-safe-bottom">
                <SheetTitle className="flex items-center gap-2 text-[15px] font-semibold">
                  <img
                    src={logoPath}
                    alt="DataSnoop"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).src = "/logos/dog-telescope-clean.jpeg"; }}
                    className="h-7 w-auto"
                  />
                </SheetTitle>
                <div className="mt-6 flex flex-col gap-1">
                  {NAV_LINKS.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setOpen(false)}
                      className={`flex items-center px-3 py-2.5 rounded-lg text-[14px] font-medium transition-colors ${
                        isActive(item.href)
                          ? "text-[#1687E8] bg-[#EAF5FF]"
                          : "text-[#5F6B85] hover:text-[#08132B] hover:bg-[#F3F6FB]"
                      }`}
                    >
                      {item.label}
                    </Link>
                  ))}

                  <div className="border-t border-[#E2E8F2] mt-3 pt-3">
                    <div className="px-3 mb-2 text-[10px] font-bold text-[#8791A6] uppercase tracking-wider">Language</div>
                    <div className="px-3">
                      <LanguageSwitcher />
                    </div>
                  </div>

                  <div className="pt-2">
                    <div className="px-3 mb-2 text-[10px] font-bold text-[#8791A6] uppercase tracking-wider">Feedback</div>
                    <div className="px-3 flex flex-col items-start gap-1">
                      <FeedbackButtons />
                    </div>
                  </div>

                  {user && (
                    <div className="border-t border-[#E2E8F2] mt-3 pt-3 space-y-1">
                      <button
                        onClick={() => { router.push("/account"); setOpen(false); }}
                        className="w-full flex items-center px-3 py-3 rounded-lg text-[14px] font-medium text-[#5F6B85] hover:text-[#08132B] hover:bg-[#F3F6FB] active:bg-[#EAF5FF]"
                      >
                        <User className="w-4 h-4 mr-2 text-[#5F6B85]" />
                        {t("nav.accountSettings")}
                      </button>
                      <button
                        onClick={() => { handleSignOut(); setOpen(false); }}
                        className="w-full flex items-center px-3 py-3 rounded-lg text-[14px] font-medium text-rose-600 hover:bg-rose-50 active:bg-rose-100"
                      >
                        <LogOut className="w-4 h-4 mr-2" />
                        {t("nav.signOut")}
                      </button>
                    </div>
                  )}

                  {!user && (
                    <div className="border-t border-[#E2E8F2] mt-3 pt-3 px-3">
                      <Link href="/login" onClick={() => setOpen(false)}>
                        <Button variant="outline" className="w-full text-[13px] border-[#E2E8F2]">{t("nav.signIn")}</Button>
                      </Link>
                    </div>
                  )}
                </div>
              </SheetContent>
            </Sheet>
          </div>
        </div>

        {/* Mobile dot-nav — visible on every page except the landing
            page (which has its own large nav cards). Previously hidden
            on /screener too, which forced users into the hamburger
            menu. The screener has its own filter sidebar so a slim
            secondary nav row is fine. */}
        {!isLanding && (
          <div className="md:hidden border-t border-[#E2E8F2]">
            <nav className="flex items-center gap-0 py-0.5 text-[13px] overflow-x-auto md:scrollbar-none -mx-1 px-1">
              {NAV_LINKS.slice(0, 4).map((item, idx) => (
                <React.Fragment key={item.href}>
                  {idx > 0 && <span className="text-[#E2E8F2] select-none shrink-0" aria-hidden>·</span>}
                  <Link
                    href={item.href}
                    className={`px-3 py-2.5 min-h-[44px] inline-flex items-center rounded-lg transition-colors shrink-0 font-medium ${
                      isActive(item.href)
                        ? "text-[#1687E8]"
                        : "text-[#5F6B85] hover:text-[#08132B] active:text-[#1687E8]"
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
