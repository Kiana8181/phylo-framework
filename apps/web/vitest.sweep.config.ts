// One-off config for the Phase 3.2 Sequence-Trace sweep.
//
// The sweep itself lives with the evaluation artifacts
// (output/review-2026/phase3-trace-sweep/trace-sweep.test.ts) so its script and
// results sit together. It has to run from this workspace, though, so that
// `vitest` and the `@/` alias resolve exactly as they do for the app's own
// tests — the sweep's whole point is to exercise the real trace modules.
//
//   npx vitest run --config vitest.sweep.config.ts     (from apps/web)
import { defineConfig } from "vitest/config";
import path from "node:path";

const SWEEP = path.resolve(
  __dirname,
  "../../../output/review-2026/phase3-trace-sweep/trace-sweep.test.ts",
);

export default defineConfig({
  test: { include: [SWEEP], testTimeout: 120_000 },
  resolve: { alias: { "@": path.resolve(__dirname, ".") } },
});
