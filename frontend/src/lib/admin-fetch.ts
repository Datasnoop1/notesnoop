"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { createClient } from "@/lib/supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export class AdminApiError extends Error {
  status: number;
  detail?: string;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
    this.detail = detail;
  }
}

export async function adminFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const supabase = createClient();
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;

  if (!token) {
    throw new AdminApiError("Not authenticated", 401);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });

  if (!response.ok) {
    let detail: string | undefined;

    try {
      const payload = await response.clone().json();
      if (typeof payload?.detail === "string") detail = payload.detail;
      else if (typeof payload?.error === "string") detail = payload.error;
    } catch {
      try {
        const text = await response.clone().text();
        detail = text || undefined;
      } catch {
        detail = undefined;
      }
    }

    const message =
      detail ||
      (response.status === 403
        ? "Admin access required"
        : response.status === 401
          ? "Not authenticated"
          : `API ${response.status}`);

    throw new AdminApiError(message, response.status, detail);
  }

  return response.json() as Promise<T>;
}

export function isAuthError(error: unknown): error is AdminApiError {
  return (
    error instanceof AdminApiError &&
    (error.status === 401 || error.status === 403)
  );
}

export function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-BE");
}

export function formatPercent(
  value: number | null | undefined,
  digits = 1,
): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

export function formatCurrency(
  value: number | null | undefined,
  options?: {
    currency?: string;
    locale?: string;
    minimumFractionDigits?: number;
    maximumFractionDigits?: number;
  },
): string {
  if (value == null || Number.isNaN(value)) return "—";

  const {
    currency = "EUR",
    locale = "nl-BE",
    minimumFractionDigits,
    maximumFractionDigits = 2,
  } = options || {};

  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits,
    maximumFractionDigits,
  }).format(value);
}

export function toBelgianDateTime(
  timestamp: string | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  if (!timestamp) return "—";

  try {
    return new Date(timestamp).toLocaleString("en-BE", {
      timeZone: "Europe/Brussels",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      ...options,
    });
  } catch {
    return timestamp;
  }
}

export function toBelgianDate(
  timestamp: string | null | undefined,
): string {
  if (!timestamp) return "—";

  try {
    return new Date(timestamp).toLocaleDateString("en-BE", {
      timeZone: "Europe/Brussels",
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return timestamp;
  }
}

export function toBelgianTimeOnly(
  timestamp: string | null | undefined,
): string {
  if (!timestamp) return "—";

  try {
    return new Date(timestamp).toLocaleTimeString("en-BE", {
      timeZone: "Europe/Brussels",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return timestamp;
  }
}

type ResourceStatus =
  | "idle"
  | "loading"
  | "ready"
  | "refreshing"
  | "error";

interface UseAdminResourceOptions<T> {
  enabled: boolean;
  fetcher: () => Promise<T>;
  intervalMs?: number;
  initialData?: T | null;
}

interface UseAdminResourceResult<T> {
  data: T | null;
  setData: Dispatch<SetStateAction<T | null>>;
  error: AdminApiError | null;
  status: ResourceStatus;
  isLoading: boolean;
  isRefreshing: boolean;
  hasLoaded: boolean;
  refresh: () => Promise<void>;
}

export function useAdminResource<T>({
  enabled,
  fetcher,
  intervalMs,
  initialData = null,
}: UseAdminResourceOptions<T>): UseAdminResourceResult<T> {
  const [data, setData] = useState<T | null>(initialData);
  const [error, setError] = useState<AdminApiError | null>(null);
  const [status, setStatus] = useState<ResourceStatus>(
    initialData == null ? "idle" : "ready",
  );
  const [hasLoaded, setHasLoaded] = useState(initialData != null);
  const mountedRef = useRef(true);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const runFetch = useCallback(async () => {
    if (!enabled) return;

    setError(null);
    setStatus(hasLoaded ? "refreshing" : "loading");

    try {
      const next = await fetcherRef.current();
      if (!mountedRef.current) return;
      setData(next);
      setHasLoaded(true);
      setStatus("ready");
    } catch (error) {
      if (!mountedRef.current) return;
      setError(
        error instanceof AdminApiError
          ? error
          : new AdminApiError(
              error instanceof Error ? error.message : "Unexpected error",
              0,
            ),
      );
      setStatus("error");
    }
  }, [enabled, hasLoaded]);

  useEffect(() => {
    if (enabled && !hasLoaded) {
      const timeoutId = window.setTimeout(() => {
        void runFetch();
      }, 0);

      return () => {
        window.clearTimeout(timeoutId);
      };
    }
  }, [enabled, hasLoaded, runFetch]);

  useEffect(() => {
    if (!enabled || !intervalMs || !hasLoaded) return;

    const intervalId = window.setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      void runFetch();
    }, intervalMs);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [enabled, intervalMs, hasLoaded, runFetch]);

  const refresh = useCallback(async () => {
    await runFetch();
  }, [runFetch]);

  return {
    data,
    setData,
    error,
    status,
    isLoading: status === "loading" || (status === "idle" && !hasLoaded),
    isRefreshing: status === "refreshing",
    hasLoaded,
    refresh,
  };
}
