import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Company Screener",
  description: "Filter 170K+ Belgian companies by revenue, EBITDA, margins, FTE, sector, and growth rates. Export to CSV. Save filter presets.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
