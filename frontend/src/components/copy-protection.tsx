"use client";

import { useEffect } from "react";

/**
 * Lightweight copy/scrape protection for production.
 * - Disables right-click context menu on financial data
 * - Blocks common dev tools shortcuts (Ctrl+U, Ctrl+Shift+I/J/C, F12)
 * - Prevents drag on financial tables
 * - Console warning
 */
export default function CopyProtection() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;

    // Block right-click on data tables
    function handleContextMenu(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (target.closest("table") || target.closest("[data-protected]")) {
        e.preventDefault();
      }
    }

    // Block dev tools shortcuts
    function handleKeyDown(e: KeyboardEvent) {
      // F12
      if (e.key === "F12") {
        e.preventDefault();
        return;
      }
      // Ctrl+U (view source)
      if (e.ctrlKey && e.key === "u") {
        e.preventDefault();
        return;
      }
      // Ctrl+Shift+I/J/C (dev tools)
      if (e.ctrlKey && e.shiftKey && ["I", "i", "J", "j", "C", "c"].includes(e.key)) {
        e.preventDefault();
        return;
      }
      // Ctrl+S (save page)
      if (e.ctrlKey && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        return;
      }
    }

    // Block drag on tables
    function handleDragStart(e: DragEvent) {
      const target = e.target as HTMLElement;
      if (target.closest("table") || target.closest("[data-protected]")) {
        e.preventDefault();
      }
    }

    document.addEventListener("contextmenu", handleContextMenu);
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("dragstart", handleDragStart);

    // Console warning
    console.log(
      "%cDatasnoop — Protected Content",
      "color: #4f46e5; font-size: 16px; font-weight: bold;"
    );
    console.log(
      "%cUnauthorized scraping, copying, or redistribution of data from this platform is prohibited under our Terms of Use.",
      "color: #64748b; font-size: 12px;"
    );

    return () => {
      document.removeEventListener("contextmenu", handleContextMenu);
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("dragstart", handleDragStart);
    };
  }, []);

  return null;
}
