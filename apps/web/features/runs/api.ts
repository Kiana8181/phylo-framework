import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import { API_ROUTES, type CreateRunResponse, type RunResult, type RunStatus } from "@phylo/contracts";

export const RunsApi = {
  create: (
    methodId: string,
    form: FormData | { params: string; file?: File | File[] }
  ) =>
    serviceHandler<CreateRunResponse, any>({
      method: Method.Post,
      url: API_ROUTES.createRun(methodId),
      params: { method: methodId },
      data: form instanceof FormData ? form : (form as any),
      hasFile: true,
    }),

  status: (id: string) =>
    serviceHandler<RunStatus>({
      method: Method.Get,
      url: API_ROUTES.runStatus(id),
    }),
  result: (id: string) =>
    serviceHandler<RunResult>({
      method: Method.Get,
      url: API_ROUTES.runResult(id),
    }),
};
