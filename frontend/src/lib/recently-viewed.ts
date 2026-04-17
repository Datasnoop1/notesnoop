/**
 * Recently-viewed companies — tracked client-side in localStorage.
 *
 * Frontend-only: keeps the last 20 distinct company-profile visits, ordered
 * most-recent-first. Persisted to localStorage under a versioned key so a
 * shape change won't crash older clients. SSR-safe (no-ops when window is
 * undefined).
 */

const STORAGE_KEY = "datasnoop_recently_viewed_v1";
const MAX_ENTRIES = 20;

export interface RecentlyViewedEntry {
  cbe: string;
  name: string;
  city?: string | null;
  /** ms since epoch */
  visited_at: number;
}

function readAll(): RecentlyViewedEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is RecentlyViewedEntry =>
        typeof e === "object" &&
        e !== null &&
        typeof (e as RecentlyViewedEntry).cbe === "string" &&
        typeof (e as RecentlyViewedEntry).name === "string"
    );
  } catch {
    return [];
  }
}

function writeAll(entries: RecentlyViewedEntry[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
    // Notify subscribers in the same tab — `storage` event only fires across tabs.
    window.dispatchEvent(new Event("datasnoop:recently-viewed-changed"));
  } catch {
    // Quota exceeded or storage disabled — fail silently.
  }
}

export function getRecentlyViewed(): RecentlyViewedEntry[] {
  return readAll();
}

export function recordCompanyView(entry: Omit<RecentlyViewedEntry, "visited_at">): void {
  if (!entry.cbe || !entry.name) return;
  const all = readAll();
  // Drop any prior entry for this CBE so we move it to the top.
  const filtered = all.filter((e) => e.cbe !== entry.cbe);
  filtered.unshift({ ...entry, visited_at: Date.now() });
  writeAll(filtered.slice(0, MAX_ENTRIES));
}

export function clearRecentlyViewed(): void {
  writeAll([]);
}

export function removeRecentlyViewed(cbe: string): void {
  const all = readAll();
  writeAll(all.filter((e) => e.cbe !== cbe));
}
