// Client-side path helpers for the orchestrator API
// Base URL stays in env (NEXT_PUBLIC_API_BASE_URL).

export const API_ROUTES = {
  methods: () => `/methods`,
  methodSpec: (methodId: string) => `/methods/${encodeURIComponent(methodId)}/spec`,
  createRun: (methodId: string) => `/runs?method=${encodeURIComponent(methodId)}`,
  runsList: () => `/runs`,
  runCurrent: () => `/runs/current`,
  runDashboard: () => `/runs/dashboard`,
  runQuota: () => `/runs/quota`,
  runStatus: (runId: string) => `/runs/${encodeURIComponent(runId)}/status`,
  runResult: (runId: string) => `/runs/${encodeURIComponent(runId)}/result`,
  runCancel: (runId: string) => `/runs/${encodeURIComponent(runId)}/cancel`,
  runCancelQueued: (runId: string) =>
    `/runs/${encodeURIComponent(runId)}/cancel-queued`,
  runTrees: (runId: string) => `/runs/${encodeURIComponent(runId)}/trees`,
  runTree: (runId: string, treeId: string) =>
    `/runs/${encodeURIComponent(runId)}/trees/${encodeURIComponent(treeId)}`,
  runSameDataset: (runId: string) =>
    `/runs/${encodeURIComponent(runId)}/same-dataset`,
  runArtifacts: (runId: string) => `/runs/${encodeURIComponent(runId)}/artifacts`,
  artifactDownload: (artifactId: string) =>
    `/artifacts/${encodeURIComponent(artifactId)}/download`,
  artifactPreview: (artifactId: string) =>
    `/artifacts/${encodeURIComponent(artifactId)}/preview`,
  filesList: () => `/files`,
  filesDelete: (id: string) => `/files/${encodeURIComponent(id)}`,
  datasetDelete: (id: string) => `/datasets/${encodeURIComponent(id)}`,
  datasetDownload: (id: string) => `/datasets/${encodeURIComponent(id)}/download`,
  datasetFastaIdStyle: (id: string) => `/datasets/${encodeURIComponent(id)}/fasta-id-style`,
  uploadInit: () => `/uploads/init`,
  uploadContent: (uploadId: string) => `/uploads/${encodeURIComponent(uploadId)}/content`,
  uploadCancel: (uploadId: string) => `/uploads/${encodeURIComponent(uploadId)}`,
  authLogin: () => `/auth/login`,
  authRegister: () => `/auth/register`,
  authForgotPassword: () => `/auth/forgot-password`,
  authResetPassword: () => `/auth/reset-password`,
  authRefresh: () => `/auth/refresh`,
  authMe: () => `/auth/me`,
  authLogout: () => `/auth/logout`,
  authGoogle: () => `/auth/google`,
} as const;

/**
 * Helper to join baseURL + path without double slashes.
 */
export function withBase(base: string, path: string) {
  const a = base.replace(/\/+$/, "");
  const b = path.replace(/^\/+/, "");
  return `${a}/${b}`;
}
