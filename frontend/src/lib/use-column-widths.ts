/**
 * useColumnWidths — drag-to-resize table column widths persisted to
 * localStorage so the user's layout survives reloads.
 *
 * Pair the returned widths with a `<colgroup>`/`<col>` block on a
 * `table-layout: fixed` table; pair `startResize(key)` with a small
 * `cursor-col-resize` handle absolutely positioned at the right edge
 * of each `<th>`.
 */
import { useCallback, useEffect, useRef, useState } from "react";

const MIN_WIDTH = 60;
const MAX_WIDTH = 600;

export function useColumnWidths(
  storageKey: string,
  defaults: Record<string, number>
): {
  widths: Record<string, number>;
  startResize: (key: string) => (e: React.MouseEvent) => void;
  reset: () => void;
} {
  const [widths, setWidths] = useState<Record<string, number>>(defaults);
  const widthsRef = useRef(widths);
  widthsRef.current = widths;

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === "object") {
        const sanitized: Record<string, number> = { ...defaults };
        for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
          if (typeof v === "number" && v >= MIN_WIDTH && v <= MAX_WIDTH) {
            sanitized[k] = v;
          }
        }
        setWidths(sanitized);
      }
    } catch {
      /* ignore corrupt storage */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  const persist = useCallback(
    (next: Record<string, number>) => {
      if (typeof window === "undefined") return;
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        /* quota or disabled — non-fatal */
      }
    },
    [storageKey]
  );

  const startResize = useCallback(
    (key: string) =>
      (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        const startX = e.clientX;
        const startWidth = widthsRef.current[key] ?? defaults[key] ?? 120;
        const onMove = (ev: MouseEvent) => {
          const diff = ev.clientX - startX;
          const next = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, startWidth + diff));
          setWidths((w) => {
            if (w[key] === next) return w;
            return { ...w, [key]: next };
          });
        };
        const onUp = () => {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          document.body.style.cursor = "";
          document.body.style.userSelect = "";
          persist(widthsRef.current);
        };
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      },
    [defaults, persist]
  );

  const reset = useCallback(() => {
    setWidths(defaults);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.removeItem(storageKey);
      } catch {
        /* ignore */
      }
    }
  }, [defaults, storageKey]);

  return { widths, startResize, reset };
}
