"use client";

import { useEffect } from "react";

export function ServiceWorkerRegistration() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const isLocalhost = ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
    if (!window.isSecureContext && !isLocalhost) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Installability should never block capture.
    });
  }, []);

  return null;
}
