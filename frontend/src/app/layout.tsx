import type { Metadata, Viewport } from "next";
import { Inter, DM_Sans } from "next/font/google";
import { Geist } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import Nav from "@/components/nav";
import AdBanner from "@/components/ad-banner";
import BrandSurvey from "@/components/brand-survey";
import CookieBanner from "@/components/cookie-banner";
import FontProvider from "@/components/font-provider";
import CopyProtection from "@/components/copy-protection";
import { LanguageProvider } from "@/components/language-provider";
import { LimitProvider } from "@/components/limit-provider";
import LimitPopup from "@/components/limit-popup";
import FooterTranslated from "@/components/footer-translated";
import StagingGate from "@/components/staging-gate";
import "./globals.css";

// Phase 5: ClerkProvider always renders so Clerk hooks called by descendants
// (login page, nav) don't violate Rules of Hooks regardless of the
// USE_CLERK gate. The actual auth-path switch lives in those descendants.

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans" });
const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export const metadata: Metadata = {
  title: {
    default: "Datasnoop — Free Belgian company search, KBO lookup and NBB annual accounts",
    template: "%s | Datasnoop",
  },
  description:
    "Free Belgian company search across 170,000+ companies. Look up KBO/BCE enterprise numbers, read NBB annual accounts, and follow Belgian Official Gazette publications — all in one fast workspace. For accountants, lawyers, journalists, M&A advisors, sales teams, and anyone who needs to know who they're dealing with.",
  metadataBase: new URL("https://datasnoop.be"),
  openGraph: {
    title: "Datasnoop — Free Belgian company search, KBO lookup and NBB annual accounts",
    description:
      "Free Belgian company search. KBO registry, NBB annual accounts, and the Official Gazette in one workspace — for the people who actually use it.",
    url: "https://datasnoop.be",
    siteName: "Datasnoop",
    locale: "en_BE",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Datasnoop — Belgian company search, free",
    description:
      "KBO lookup, NBB annual accounts, and the Official Gazette in one workspace.",
  },
  robots: {
    index: true,
    follow: true,
  },
  alternates: {
    canonical: "https://datasnoop.be",
  },
};

/**
 * Mobile viewport configuration.
 *
 * - `width: device-width, initial-scale: 1` — standard responsive baseline.
 * - `maximumScale: 5` — allow accessibility zoom (don't trap users at 1x).
 * - `viewportFit: "cover"` — let safe-area-inset-* env vars work on iOS
 *   notched devices, so we can pad sticky bars away from the home indicator.
 * - `themeColor` — sets the iOS Safari status-bar tint and Android browser
 *   chrome to match the page top, so the chrome blends with the design
 *   instead of showing a default white/black slab.
 * - `interactiveWidget: "resizes-content"` — when the iOS keyboard opens,
 *   resize the layout viewport instead of overlaying it; otherwise sticky
 *   footers and bottom-sheet modals get hidden behind the keyboard.
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F7F9FC" },
    { media: "(prefers-color-scheme: dark)", color: "#0B1020" },
  ],
  colorScheme: "light",
  interactiveWidget: "resizes-content",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const tree = (
    <html lang="en" className={`${inter.variable} ${dmSans.variable} ${geist.variable} h-full antialiased`}>
      <head>
        {/* AdSense script loaded via AdBanner component — no duplicate here */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "WebSite",
              name: "DataSnoop",
              url: "https://datasnoop.be",
              description: "Company intelligence platform combining KBO registry data with NBB annual accounts for PE deal sourcing and screening.",
              potentialAction: {
                "@type": "SearchAction",
                target: "https://datasnoop.be/search?q={search_term_string}",
                "query-input": "required name=search_term_string",
              },
            }),
          }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "Organization",
              name: "DataSnoop",
              url: "https://datasnoop.be",
              description: "Company intelligence for PE deal sourcing",
              sameAs: [],
            }),
          }}
        />
      </head>
      <body className="min-h-full flex flex-col bg-background font-sans touch-manipulation overscroll-x-none">
        <LanguageProvider>
          <LimitProvider>
            <StagingGate>
              <FontProvider />
              <CopyProtection />
              <Nav />
              <main className="flex-1" data-protected>
                <div className="w-full max-w-[1536px] mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6 ds-safe-bottom">
                  {children}
                </div>
              </main>
              <div className="no-print">
                <AdBanner />
                <BrandSurvey />
                <CookieBanner />
                <FooterTranslated />
              </div>
              <LimitPopup />
            </StagingGate>
          </LimitProvider>
        </LanguageProvider>
      </body>
    </html>
  );

  // Phase 5: ClerkProvider must always be in the React tree so any descendant
  // that conditionally calls Clerk hooks (e.g. components/nav.tsx with
  // useClerkUser) doesn't violate Rules of Hooks. When USE_CLERK=false the
  // provider sits dormant — it doesn't render anything that affects the
  // Supabase-path UI, but its context is available so Clerk hooks resolve to
  // "not signed in" instead of throwing.
  //
  // The publishable key needs to be present at build time even when
  // USE_CLERK=false (build-time NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY); a
  // placeholder pk_test_xxx value is sufficient — Clerk only initializes
  // network calls when an actual sign-in/up flow runs.
  return <ClerkProvider>{tree}</ClerkProvider>;
}
