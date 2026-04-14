"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { Menu, LogOut, User, Bug, Lightbulb } from "lucide-react";
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
import type { User as SupabaseUser } from "@supabase/supabase-js";

const NAV_ITEMS = [
  { label: "Home", href: "/" },
  { label: "Screener", href: "/screener" },
  { label: "Company", href: "/company" },
  { label: "Compare", href: "/compare" },
  { label: "Stats", href: "/stats" },
  { label: "People", href: "/people" },
  { label: "Favourites", href: "/favourites" },
];

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<SupabaseUser | null>(null);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => setUser(data.user));

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => setUser(session?.user ?? null)
    );
    return () => subscription.unsubscribe();
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

  return (
    <header className="sticky top-0 z-50 bg-white border-b border-slate-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          {/* Brand */}
          <Link href="/" className="flex items-center gap-2">
            <Image src="/logo.svg" alt="Data Peak" width={28} height={28} className="shrink-0" />
            <div className="flex flex-col justify-center">
              <span className="text-lg font-bold text-indigo-600 leading-tight">
                Data Peak
                <span className="ml-1.5 text-[9px] font-semibold bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full uppercase tracking-wider align-top">Beta</span>
              </span>
              <span className="text-[10px] uppercase tracking-wider text-slate-400 leading-tight">
                Belgian Company Intelligence
              </span>
            </div>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-1">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`px-3 py-2 text-sm font-medium transition-colors border-b-2 ${
                  isActive(item.href)
                    ? "text-indigo-600 border-indigo-600"
                    : "text-slate-600 border-transparent hover:text-slate-900 hover:border-slate-300"
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          {/* Feedback + auth */}
          <div className="flex items-center gap-2">
            <div className="hidden md:flex items-center gap-1.5 mr-1">
              <FeedbackButtons />
            </div>
            <div className="hidden md:block w-px h-5 bg-slate-200 mr-1" />
            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger className="hidden md:flex items-center gap-2 px-2 py-1 rounded-md hover:bg-slate-100 transition-colors">
                  <div className="w-7 h-7 rounded-full bg-indigo-600 text-white flex items-center justify-center text-xs font-bold">
                    {initials}
                  </div>
                  <span className="text-sm text-slate-600 max-w-[140px] truncate">
                    {user.email}
                  </span>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
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
                <Button variant="outline" size="sm" className="hidden md:inline-flex">
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
                <SheetTitle className="flex items-center gap-2 text-lg font-bold text-indigo-600">
                  <Image src="/logo.svg" alt="Data Peak" width={24} height={24} />
                  Data Peak
                </SheetTitle>
                <nav className="mt-6 flex flex-col gap-1">
                  {NAV_ITEMS.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setOpen(false)}
                      className={`px-3 py-2 rounded-md text-sm font-medium ${
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
                      className="px-3 py-2 rounded-md text-sm font-medium text-red-600 hover:bg-red-50 text-left mt-4"
                    >
                      Sign out
                    </button>
                  ) : (
                    <Link
                      href="/login"
                      onClick={() => setOpen(false)}
                      className="px-3 py-2 rounded-md text-sm font-medium text-indigo-600 hover:bg-indigo-50 mt-4"
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
