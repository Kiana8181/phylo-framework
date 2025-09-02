import { useGet } from "@/lib/http/hooks";
import { MethodsApi } from "./api";
import { API_ROUTES, type MethodInfo, type MethodSpec } from "@phylo/contracts";

export const useMethods = () => useGet<MethodInfo[]>(["methods"], API_ROUTES.methods());

export const useMethodSpec = (id?: string) =>
  useGet<MethodSpec>(["spec", id], id ? API_ROUTES.methodSpec(id) : "", undefined, {
    enabled: !!id,
  });
