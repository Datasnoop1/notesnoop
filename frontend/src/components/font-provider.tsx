"use client";

import { useEffect } from "react";

const FONT_MAP: Record<string, string> = {
  inter: "var(--font-inter)",
  "dm-sans": "var(--font-dm-sans)",
  geist: "var(--font-geist)",
};

export default function FontProvider() {
  useEffect(() => {
    const saved = localStorage.getItem("datasnoop_font") || "geist";
    const css = FONT_MAP[saved] || FONT_MAP.geist;
    document.body.style.fontFamily = `${css}, system-ui, sans-serif`;
  }, []);

  return null;
}
