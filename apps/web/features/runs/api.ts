import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import { http } from "@/lib/http/client";
import {
  API_ROUTES,
  type CreateRunResponse,
  type RunArtifactsResponse,
  type RunResult,
  type RunTreePayload,
  type RunTreesListResponse,
  type RunStatus,
  type RunSummary,
} from "@phylo/contracts";

/**
 * Fetch artifact bytes through the authenticated API and return an object URL.
 * Used for previews (<img src>) and downloads — no base64, streamed via backend.
 * Caller must URL.revokeObjectURL(url) when done.
 */
export async function fetchArtifactObjectUrl(apiPath: string): Promise<string> {
  const res = await http.get(apiPath, { responseType: "blob" });
  return URL.createObjectURL(res.data as Blob);
}

export type CurrentRunResponse = {
  run_id: string | null;
  status?: string | null;
  progress?: number | null;
  message?: string | null;
  method_id?: string | null;
  params?: Record<string, unknown> | null;
  dataset_name?: string | null;
  dataset_files?: string[] | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export const RunsApi = {
  async getCurrentRun(): Promise<CurrentRunResponse> {
    return serviceHandler<CurrentRunResponse>({
      method: Method.Get,
      url: API_ROUTES.runCurrent(),
    });
  },

  async list(opts?: { skip?: number; limit?: number }): Promise<RunSummary[]> {
    return serviceHandler<RunSummary[]>({
      method: Method.Get,
      url: API_ROUTES.runsList(),
      params: { skip: opts?.skip ?? 0, limit: opts?.limit ?? 100 },
    });
  },

  async create(
    methodId: string,
    body: { params?: Record<string, unknown>; file_id?: string | null }
  ): Promise<CreateRunResponse> {
    // Uploads are decoupled: run creation only references an already-uploaded
    // file_id and returns quickly with a run_id.
    return serviceHandler<CreateRunResponse>({
      method: Method.Post,
      url: API_ROUTES.createRun(methodId),
      data: { params: body.params ?? {}, file_id: body.file_id ?? null },
    });
  },

  async cancel(id: string): Promise<RunStatus> {
    return serviceHandler<RunStatus>({
      method: Method.Post,
      url: API_ROUTES.runCancel(id),
      allowDuplicateRequests: true,
    });
  },

  async status(id: string): Promise<RunStatus> {
    return serviceHandler<RunStatus>({
      method: Method.Get,
      url: API_ROUTES.runStatus(id),
    });
  },

  async result(id: string): Promise<RunResult> {
    return serviceHandler<RunResult>({
      method: Method.Get,
      url: API_ROUTES.runResult(id),
    });
  },

  async trees(id: string): Promise<RunTreesListResponse> {
    return serviceHandler<RunTreesListResponse>({
      method: Method.Get,
      url: API_ROUTES.runTrees(id),
    });
  },

  async tree(id: string, treeId: string): Promise<RunTreePayload> {
    // allowDuplicateRequests: without it, an in-flight duplicate (e.g. from
    // React effect double-invoke) resolves to `null` via the dedup cache,
    // which TreesCarousel would cache as the tree payload and re-fetch
    // forever (new `treeCache` reference each time -> effect re-runs ->
    // "Maximum update depth exceeded").
    return serviceHandler<RunTreePayload>({
      method: Method.Get,
      url: API_ROUTES.runTree(id, treeId),
      allowDuplicateRequests: true,
    });
  },

  async sameDataset(runId: string): Promise<RunSummary[]> {
    return serviceHandler<RunSummary[]>({
      method: Method.Get,
      url: API_ROUTES.runSameDataset(runId),
    });
  },

  async artifacts(id: string): Promise<RunArtifactsResponse> {
    // allowDuplicateRequests prevents the dedup-cache from returning `null`
    // when React strict-mode double-mounts the section before the first
    // request resolves.
    return serviceHandler<RunArtifactsResponse>({
      method: Method.Get,
      url: API_ROUTES.runArtifacts(id),
      allowDuplicateRequests: true,
    });
  },
};
