import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import type { CreateRunResponse, RunResult, RunStatus } from "@/types/api";

export const RunsApi = {
  create: (
    methodId: string,
    form: FormData | { params: string; file?: File | File[] }
  ) =>
    serviceHandler<CreateRunResponse, any>({
      method: Method.Post,
      url: `/runs`,
      params: { method: methodId },
      data: form instanceof FormData ? form : (form as any),
      hasFile: true,
    }),

  status: (id: string) =>
    serviceHandler<RunStatus>({
      method: Method.Get,
      url: `/runs/${id}/status`,
    }),
  result: (id: string) =>
    serviceHandler<RunResult>({
      method: Method.Get,
      url: `/runs/${id}/result`,
    }),
};
