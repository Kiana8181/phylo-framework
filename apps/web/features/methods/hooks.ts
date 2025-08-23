import { useGet } from "@/lib/http/hooks";
import { MethodsApi } from "./api";
import type { MethodInfo, MethodSpec } from "@/types/api";

export const useMethods = () => useGet<MethodInfo[]>(["methods"], "/methods");

export const useMethodSpec = (id?: string) =>
  useGet<MethodSpec>(["spec", id], id ? `/methods/${id}/spec` : "", undefined, {
    enabled: !!id,
  });
