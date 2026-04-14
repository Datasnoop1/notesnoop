"use client";

import { useState, useEffect } from "react";

const FONTS = [
  { id: "inter", label: "Inter", css: "var(--font-inter)" },
  { id: "dm-sans", label: "DM Sans", css: "var(--font-dm-sans)" },
  { id: "geist", label: "Geist", css: "var(--font-geist)" },
];

export default function FontSwitcher() {
  const [active, setActive] = useState("inter");

  useEffect(() => {
    const saved = localStorage.getItem("datapeak_font");
    if (saved) {
      setActive(saved);
      applyFont(saved);
    }
  }, []);

  function applyFont(fontId: string) {
    const font = FONTS.find((f) => f.id === fontId);
    if (!font) return;
    document.body.style.fontFamily = `${font.css}, system-ui, sans-serif`;
    localStorage.setItem("datapeak_font", fontId);
    setActive(fontId);
  }

  return (
    <div className="fixed bottom-4 left-4 z-50 bg-white border border-slate-200 rounded-lg shadow-lg p-2 flex items-center gap-1">
      <span className="text-[10px] text-slate-400 mr-1 uppercase tracking-wider">Font:</span>
      {FONTS.map((f) => (
        <button
          key={f.id}
          onClick={() => applyFont(f.id)}
          className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
            active === f.id
              ? "bg-indigo-600 text-white"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          {f.label}
        </button>
      ))}
    </div>
  );
}
