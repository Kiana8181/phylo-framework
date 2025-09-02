import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import { API_ROUTES, type MethodInfo, type MethodSpec } from "@phylo/contracts";

export const MethodsApi = {
  list: () =>
    serviceHandler<MethodInfo[]>({ method: Method.Get, url: API_ROUTES.methods() }),
  spec: (id: string) =>
    serviceHandler<MethodSpec>({
      method: Method.Get,
      url: API_ROUTES.methodSpec(id),
    }),
};
