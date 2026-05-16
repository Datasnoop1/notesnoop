import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    testTimeout: 20000,
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      include: ["src/components/**/*.{ts,tsx}"],
      exclude: ["src/test/**"],
      thresholds: {
        statements: 60,
        branches: 45,
        functions: 55,
        lines: 60,
      },
    },
  },
});
