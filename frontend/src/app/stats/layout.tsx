import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sector Statistics",
  description: "Belgian company sector benchmarks: median revenue, EBITDA margins, FTE, leverage ratios, and distribution charts across 170K+ companies.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
