import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      reporter: ["text-summary", "html", "lcov", "json-summary"],
      reportsDirectory: "../../coverage/contracts",
      thresholds: { lines: 100, functions: 100, branches: 100, statements: 100 },
    },
    include: ["tests/**/*.test.ts"],
  },
});
