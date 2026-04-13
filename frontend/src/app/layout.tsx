import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Nav from "@/components/nav";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "LeadPeek — Belgian Company Intelligence",
  description:
    "Screen Belgian companies by sector, revenue, EBITDA, and more. KBO registry + NBB annual accounts.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-slate-50 font-sans">
        <Nav />
        <main className="flex-1">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
            {children}
          </div>
        </main>
        <footer className="border-t border-slate-200 bg-white py-4 mt-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-xs text-slate-400">
            Data sources: KBO/BCE (Kruispuntbank van Ondernemingen) · NBB/BNB (Nationale Bank van België) · Belgisch Staatsblad
          </div>
        </footer>
      </body>
    </html>
  );
}
