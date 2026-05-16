import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

Object.defineProperty(window.navigator, "serviceWorker", {
  value: { register: vi.fn().mockResolvedValue(undefined) },
  configurable: true,
});

Object.defineProperty(window.navigator, "clipboard", {
  value: { writeText: vi.fn().mockResolvedValue(undefined) },
  configurable: true,
});

Object.defineProperty(window.HTMLAnchorElement.prototype, "click", {
  value: vi.fn(),
  configurable: true,
});
