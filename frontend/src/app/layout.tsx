import type { Metadata } from "next";
import { Inter, DM_Sans } from "next/font/google";
import { Geist } from "next/font/google";
import Link from "next/link";
import Nav from "@/components/nav";
import AdBanner from "@/components/ad-banner";
import BrandSurvey from "@/components/brand-survey";
import CookieBanner from "@/components/cookie-banner";
import FontProvider from "@/components/font-provider";
import CopyProtection from "@/components/copy-protection";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans" });
const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export const metadata: Metadata = {
  title: "Datasnoop — Belgian Company Intelligence",
  description:
    "Screen Belgian companies by sector, revenue, EBITDA, and more. KBO registry + NBB annual accounts.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${dmSans.variable} ${geist.variable} h-full antialiased`}>
      <head>
        <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-1315269218347333" crossOrigin="anonymous" />
      </head>
      <body className="min-h-full flex flex-col bg-slate-50 font-sans">
        <FontProvider />
        <CopyProtection />
        <Nav />
        <main className="flex-1" data-protected>
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            {children}
          </div>
        </main>
        <AdBanner />
        <BrandSurvey />
        <CookieBanner />
        <footer className="border-t border-slate-200 bg-white py-4 mt-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-xs text-slate-400 space-y-1">
            <div>
              Data sources: KBO/BCE (Kruispuntbank van Ondernemingen) · NBB/BNB (Nationale Bank van België) · Belgisch Staatsblad
            </div>
            <div className="flex items-center justify-center gap-1.5">
              <Link href="/privacy" className="hover:text-slate-600 hover:underline">Privacy Policy</Link>
              <span>|</span>
              <Link href="/terms" className="hover:text-slate-600 hover:underline">Terms of Use</Link>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
