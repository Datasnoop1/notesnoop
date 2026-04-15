"use client";

import { useState, useEffect } from "react";
import { Type } from "lucide-react";

const FONTS = [
  { id: "inter", label: "Inter", desc: "Clean, widely used" },
  { id: "dm-sans", label: "DM Sans", desc: "Modern, friendly" },
  { id: "geist", label: "Geist", desc: "Premium, Swiss design" },
];

const FONT_MAP: Record<string, string> = {
  inter: "var(--font-inter)",
  "dm-sans": "var(--font-dm-sans)",
  geist: "var(--font-geist)",
};

export default function FontSwitcher() {
  const [active, setActive] = useState("geist");

  useEffect(() => {
    const saved = localStorage.getItem("datasnoop_font") || "geist";
    setActive(saved);
  }, []);

  function applyFont(fontId: string) {
    const css = FONT_MAP[fontId] || FONT_MAP.geist;
    document.body.style.fontFamily = `${css}, system-ui, sans-serif`;
    localStorage.setItem("datasnoop_font", fontId);
    setActive(fontId);
  }

  return (
    <div>
      <h2 className="font-semibold text-slate-900 mb-3 flex items-center gap-2">
        <Type className="h-4 w-4" /> Font Preference
      </h2>
      <div className="grid grid-cols-3 gap-2">
        {FONTS.map((f) => (
          <button
            key={f.id}
            onClick={() => applyFont(f.id)}
            className={`rounded-lg border p-3 text-left transition-all ${
              active === f.id
                ? "border-indigo-500 bg-indigo-50 ring-1 ring-indigo-500"
                : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
            }`}
          >
            <div className="text-sm font-semibold text-slate-900">{f.label}</div>
            <div className="text-[10px] text-slate-400 mt-0.5">{f.desc}</div>
          </button>
        ))}
      </div>
      <p className="text-[10px] text-slate-400 mt-2">Font preference is saved to your browser.</p>
    </div>
  );
}
