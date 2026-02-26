import { postFormWithProgress } from "@/lib/utils";
import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import {
  API_ROUTES,
  type CreateRunResponse,
  type RunResult,
  type RunTreePayload,
  type RunTreesListResponse,
  type RunStatus,
  type RunSummary,
} from "@phylo/contracts";

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
    fd: FormData,
    opts?: { onProgress?: (p: number) => void }
  ): Promise<CreateRunResponse> {
    // For file uploads with progress, we still use the custom utility
    // since serviceHandler doesn't support progress tracking
    const url = API_ROUTES.createRun(methodId);
    const res = await postFormWithProgress(url, fd, opts?.onProgress ?? (() => {}));
    return res as CreateRunResponse; 
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
    return serviceHandler<RunTreePayload>({
      method: Method.Get,
      url: API_ROUTES.runTree(id, treeId),
    });
  },

  async sameDataset(runId: string): Promise<RunSummary[]> {
    return serviceHandler<RunSummary[]>({
      method: Method.Get,
      url: API_ROUTES.runSameDataset(runId),
    });
  },
};
