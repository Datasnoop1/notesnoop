import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "People Search",
  description: "Search Belgian company administrators, directors, and shareholders by name. Find all corporate roles and mandates for any individual.",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
