"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";

import en from "@/i18n/en.json";
import nl from "@/i18n/nl.json";
import fr from "@/i18n/fr.json";

export type Locale = "en" | "nl" | "fr";

const STORAGE_KEY = "datasnoop_locale";
const DEFAULT_LOCALE: Locale = "en";

type TranslationMap = Record<string, unknown>;

const translations: Record<Locale, TranslationMap> = { en, nl, fr };

/**
 * Look up a dot-separated key in a nested object.
 * e.g. t("nav.screener") -> translations[locale].nav.screener
 */
function resolve(obj: TranslationMap, path: string): string {
  const parts = path.split(".");
  let current: unknown = obj;
  for (const part of parts) {
    if (current == null || typeof current !== "object") return path;
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === "string" ? current : path;
}

interface LanguageContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue>({
  locale: DEFAULT_LOCALE,
  setLocale: () => {},
  t: (key) => key,
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  const [mounted, setMounted] = useState(false);

  // Read persisted locale on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Locale | null;
      if (saved && translations[saved]) {
        setLocaleState(saved);
      }
    } catch {
      // localStorage unavailable (SSR or private browsing)
    }
    setMounted(true);
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // ignore
    }
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>): string => {
      let value = resolve(translations[locale], key);
      // Fallback to English if key missing in current locale
      if (value === key && locale !== "en") {
        value = resolve(translations.en, key);
      }
      // Interpolate {varName} placeholders
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          value = value.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
        }
      }
      return value;
    },
    [locale]
  );

  // Avoid hydration mismatch: render children only after reading localStorage
  if (!mounted) {
    return (
      <LanguageContext.Provider
        value={{ locale: DEFAULT_LOCALE, setLocale, t: (key) => resolve(translations.en, key) }}
      >
        {children}
      </LanguageContext.Provider>
    );
  }

  return (
    <LanguageContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useTranslation() {
  return useContext(LanguageContext);
}
