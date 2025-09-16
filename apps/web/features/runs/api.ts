import { postFormWithProgress } from "@/lib/utils";
import {
  API_ROUTES,
  type CreateRunResponse,
  type RunResult,
  type RunStatus,
} from "@phylo/contracts";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const abs = (p: string) => `${API_BASE.replace(/\/+$/,"")}/${p.replace(/^\/+/,"")}`;

export const RunsApi = {
  async create(
    methodId: string,
    fd: FormData,
    opts?: { onProgress?: (p: number) => void }
  ): Promise<CreateRunResponse> {
    const url = abs(API_ROUTES.createRun(methodId));
    const res = await postFormWithProgress(url, fd, opts?.onProgress ?? (() => {}));
    return res as CreateRunResponse; 
  },

  async status(id: string): Promise<RunStatus> {
    const r = await fetch(abs(API_ROUTES.runStatus(id)));
    if (!r.ok) throw new Error(await r.text());
    return (await r.json()) as RunStatus;
  },

  async result(id: string): Promise<RunResult> {
    const r = await fetch(abs(API_ROUTES.runResult(id)));
    if (!r.ok) throw new Error(await r.text());
    return (await r.json()) as RunResult;
  },
};
