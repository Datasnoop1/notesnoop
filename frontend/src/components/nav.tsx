"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { Menu, LogOut, User, Bell, Search, Building, UserSearch, ChevronDown } from "lucide-react";
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
import { getNotifications, markNotificationsRead } from "@/lib/api";
import type { FavNotification } from "@/lib/api";
import type { User as SupabaseUser } from "@supabase/supabase-js";

const NAV_LINKS = [
  { label: "Screener", href: "/screener" },
  { label: "Favourites", href: "/favourites" },
  { label: "Compare", href: "/compare" },
  { label: "Aggregate", href: "/aggregate" },
];

const SEARCH_ITEMS = [
  { label: "Company", href: "/company", desc: "Search by name or CBE number", icon: Building },
  { label: "People", href: "/people", desc: "Find administrators & shareholders", icon: UserSearch },
];

const MOBILE_NAV = [
  { label: "Screener", href: "/screener" },
  { label: "Search", href: "/search" },
  { label: "Favourites", href: "/favourites" },
  { label: "Compare", href: "/compare" },
  { label: "Aggregate", href: "/aggregate" },
];

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<SupabaseUser | null>(null);
  const [notifCount, setNotifCount] = useState(0);
  const [notifs, setNotifs] = useState<FavNotification[]>([]);
  const [showNotifs, setShowNotifs] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);

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

  // Close search dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
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

  const searchActive = isActive("/company") || isActive("/people");
  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "?";

  return (
    <header className="sticky top-0 z-50 bg-white/95 backdrop-blur-sm border-b border-slate-200/80">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand */}
          <Link href="/" className="flex items-center gap-2.5 group">
            <img src="/logo.svg" alt="Data Peak" width={28} height={28} className="shrink-0 group-hover:scale-105 transition-transform" />
            <span className="text-base font-semibold text-slate-900 tracking-tight">
              Data Peak
            </span>
            <span className="text-[7px] font-bold bg-indigo-100 text-indigo-600 px-1.5 py-0.5 rounded-full uppercase tracking-widest">Beta</span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-0.5">
            {/* Screener */}
            <Link
              href="/screener"
              className={`px-3.5 py-2 text-[13px] font-medium transition-all rounded-md ${
                isActive("/screener")
                  ? "text-indigo-600 bg-indigo-50"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
              }`}
            >
              Screener
            </Link>

            {/* Search */}
            <Link
              href="/search"
              className={`flex items-center gap-1.5 px-3.5 py-2 text-[13px] font-medium transition-all rounded-md ${
                isActive("/search") || isActive("/company") || isActive("/people")
                  ? "text-indigo-600 bg-indigo-50"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
              }`}
            >
              <Search className="w-3.5 h-3.5" />
              Search
            </Link>

            {/* Remaining nav links */}
            {NAV_LINKS.slice(1).map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`px-3.5 py-2 text-[13px] font-medium transition-all rounded-md ${
                  isActive(item.href)
                    ? "text-indigo-600 bg-indigo-50"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>

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
                      Data Updates
                    </div>
                    {notifs.length === 0 ? (
                      <div className="px-3 py-5 text-xs text-slate-400 text-center">No new updates</div>
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

            <div className="hidden md:block w-px h-5 bg-slate-200" />

            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger className="hidden md:flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-slate-50 transition-colors">
                  <div className="w-7 h-7 rounded-full bg-indigo-600 text-white flex items-center justify-center text-[11px] font-bold">
                    {initials}
                  </div>
                  <span className="text-[13px] text-slate-600 max-w-[130px] truncate">
                    {user.email}
                  </span>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuItem onClick={() => router.push("/account")} className="cursor-pointer">
                    <User className="w-4 h-4 mr-2" />
                    Account settings
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleSignOut} className="cursor-pointer">
                    <LogOut className="w-4 h-4 mr-2" />
                    Sign out
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <Link href="/login">
                <Button variant="outline" size="sm" className="hidden md:inline-flex text-[13px]">
                  Sign in
                </Button>
              </Link>
            )}

            {/* Mobile hamburger */}
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger>
                <span className="md:hidden inline-flex items-center justify-center rounded-md p-2 text-slate-600 hover:bg-slate-100">
                  <Menu className="h-5 w-5" />
                </span>
              </SheetTrigger>
              <SheetContent side="left" className="w-64">
                <SheetTitle className="flex items-center gap-2 text-base font-semibold text-slate-900">
                  <img src="/logo.svg" alt="Data Peak" width={22} height={22} />
                  Data Peak
                </SheetTitle>
                <nav className="mt-6 flex flex-col gap-1">
                  {MOBILE_NAV.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setOpen(false)}
                      className={`px-3 py-2.5 rounded-md text-sm font-medium ${
                        isActive(item.href)
                          ? "bg-indigo-50 text-indigo-600"
                          : "text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      {item.label}
                    </Link>
                  ))}
                  {user ? (
                    <button
                      onClick={() => { handleSignOut(); setOpen(false); }}
                      className="px-3 py-2.5 rounded-md text-sm font-medium text-red-600 hover:bg-red-50 text-left mt-4"
                    >
                      Sign out
                    </button>
                  ) : (
                    <Link
                      href="/login"
                      onClick={() => setOpen(false)}
                      className="px-3 py-2.5 rounded-md text-sm font-medium text-indigo-600 hover:bg-indigo-50 mt-4"
                    >
                      Sign in
                    </Link>
                  )}
                </nav>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </div>
    </header>
  );
}
