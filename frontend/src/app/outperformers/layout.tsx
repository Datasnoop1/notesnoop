import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Outperformers (experimental)",
  description: "Experimental view: Belgian companies bucketed by revenue growth, margin level, and margin growth.",
  robots: { index: false, follow: false },
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
