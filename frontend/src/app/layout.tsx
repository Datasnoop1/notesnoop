import type { Metadata } from "next";
import { Inter, DM_Sans } from "next/font/google";
import { Geist } from "next/font/google";
import Nav from "@/components/nav";
import GlobalSearchBar from "@/components/global-search-bar";
import AdBanner from "@/components/ad-banner";
import BrandSurvey from "@/components/brand-survey";
import CookieBanner from "@/components/cookie-banner";
import FontProvider from "@/components/font-provider";
import CopyProtection from "@/components/copy-protection";
import { LanguageProvider } from "@/components/language-provider";
import { LimitProvider } from "@/components/limit-provider";
import LimitPopup from "@/components/limit-popup";
import FooterTranslated from "@/components/footer-translated";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans" });
const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export const metadata: Metadata = {
  title: {
    default: "DataSnoop — Belgian Company Intelligence",
    template: "%s | DataSnoop",
  },
  description:
    "Screen 170K+ Belgian companies by sector, revenue, EBITDA, margins, and more. Combines KBO registry data with NBB annual accounts for PE deal sourcing and screening.",
  metadataBase: new URL("https://datasnoop.be"),
  openGraph: {
    title: "DataSnoop — Belgian Company Intelligence",
    description: "Screen 170K+ Belgian companies by financials, sector, and structure. Built for PE deal sourcing.",
    url: "https://datasnoop.be",
    siteName: "DataSnoop",
    locale: "en_BE",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "DataSnoop — Belgian Company Intelligence",
    description: "Screen 170K+ Belgian companies by financials, sector, and structure.",
  },
  robots: {
    index: true,
    follow: true,
  },
  alternates: {
    canonical: "https://datasnoop.be",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
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
              description: "Belgian company intelligence platform combining KBO registry data with NBB annual accounts for PE deal sourcing and screening.",
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
              description: "Belgian company intelligence for PE deal sourcing",
              sameAs: [],
            }),
          }}
        />
      </head>
      <body className="min-h-full flex flex-col bg-white font-sans">
        <LanguageProvider>
          <LimitProvider>
            <FontProvider />
            <CopyProtection />
            <Nav />
            <GlobalSearchBar />
            <main className="flex-1" data-protected>
              <div className="w-full max-w-[1536px] mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6">
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
          </LimitProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
