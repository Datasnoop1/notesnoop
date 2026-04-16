import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "User Guide",
  description: "Complete guide to using DataSnoop for Belgian company intelligence, deal screening, and financial analysis.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
