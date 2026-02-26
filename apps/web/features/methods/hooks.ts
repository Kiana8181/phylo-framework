import { useGet } from "@/lib/http/hooks";
import { API_ROUTES, type MethodInfo, type MethodSpec } from "@phylo/contracts";
import { useMemo } from "react";
import { toContractSpec, type ContractSpec } from "@/features/runs/params";

export const useMethods = () => useGet<MethodInfo[]>(["methods"], API_ROUTES.methods());

export const useMethodSpec = (id?: string) =>
  useGet<MethodSpec>(["spec", id], id ? API_ROUTES.methodSpec(id) : "", undefined, {
    enabled: !!id,
  });

export const useMethodSpecByMethodKey = (methodKey?: string) => useMethodSpec(methodKey);

export function useContractSpec(methodKey?: string): {
  methodSpec?: MethodSpec;
  contractSpec: ContractSpec | null;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
} {
  const query = useMethodSpecByMethodKey(methodKey);
  const contractSpec = useMemo(() => {
    if (!methodKey) return null;
    return toContractSpec(methodKey, query.data);
  }, [methodKey, query.data]);

  return {
    methodSpec: query.data,
    contractSpec,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
  };
}
