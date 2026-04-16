import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Search Companies & People",
  description: "Search Belgian companies by name, CBE number, or keyword. Find administrators and shareholders across 170K+ registered enterprises.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
