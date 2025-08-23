import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import type { MethodInfo, MethodSpec } from "@/types/api";

export const MethodsApi = {
  list: () =>
    serviceHandler<MethodInfo[]>({ method: Method.Get, url: "/methods" }),
  spec: (id: string) =>
    serviceHandler<MethodSpec>({
      method: Method.Get,
      url: `/methods/${id}/spec`,
    }),
};
