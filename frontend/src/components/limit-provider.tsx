"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";
import { LIMIT_EXCEEDED_EVENT, type LimitExceededDetail } from "@/lib/api";

export interface LimitInfo {
  tier: "guest" | "registered";
  limitType: string;
  limit: number;
  used: number;
}

interface LimitContextValue {
  /** Current limit info (if popup should be shown) */
  limitInfo: LimitInfo | null;
  /** Show the limit popup with the given info */
  showLimit: (info: LimitInfo) => void;
  /** Close the limit popup */
  clearLimit: () => void;
}

const LimitContext = createContext<LimitContextValue>({
  limitInfo: null,
  showLimit: () => {},
  clearLimit: () => {},
});

export function LimitProvider({ children }: { children: ReactNode }) {
  const [limitInfo, setLimitInfo] = useState<LimitInfo | null>(null);

  const showLimit = useCallback((info: LimitInfo) => {
    setLimitInfo(info);
  }, []);

  const clearLimit = useCallback(() => {
    setLimitInfo(null);
  }, []);

  // Listen for limit-exceeded events dispatched by apiFetch
  useEffect(() => {
    function handleLimitExceeded(e: Event) {
      const detail = (e as CustomEvent<LimitExceededDetail>).detail;
      setLimitInfo({
        tier: detail.tier,
        limitType: detail.limitType,
        limit: detail.limit,
        used: detail.used,
      });
    }
    window.addEventListener(LIMIT_EXCEEDED_EVENT, handleLimitExceeded);
    return () => {
      window.removeEventListener(LIMIT_EXCEEDED_EVENT, handleLimitExceeded);
    };
  }, []);

  return (
    <LimitContext.Provider value={{ limitInfo, showLimit, clearLimit }}>
      {children}
    </LimitContext.Provider>
  );
}

export function useLimit() {
  return useContext(LimitContext);
}
