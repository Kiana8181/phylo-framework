// Client-side path helpers for the orchestrator API
// Base URL stays in env (NEXT_PUBLIC_API_BASE_URL).

export const API_ROUTES = {
  methods: () => `/methods`,
  methodSpec: (methodId: string) => `/methods/${encodeURIComponent(methodId)}/spec`,
  createRun: (methodId: string) => `/runs?method=${encodeURIComponent(methodId)}`,
  runStatus: (runId: string) => `/runs/${encodeURIComponent(runId)}/status`,
  runResult: (runId: string) => `/runs/${encodeURIComponent(runId)}/result`,
} as const;

/**
 * Helper to join baseURL + path without double slashes.
 */
export function withBase(base: string, path: string) {
  const a = base.replace(/\/+$/, "");
  const b = path.replace(/^\/+/, "");
  return `${a}/${b}`;
}
