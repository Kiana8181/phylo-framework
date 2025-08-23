import {
  useQuery,
  useMutation,
  UseQueryOptions,
  UseMutationOptions,
} from "@tanstack/react-query";
import { Method, serviceHandler, ServiceHandlerParams } from "./serviceHandler";

export function useGet<TData = any>(
  key: any[],
  url: string,
  params?: Record<string, any>,
  options?: Omit<UseQueryOptions<TData>, "queryKey" | "queryFn">
) {
  return useQuery<TData>({
    queryKey: key,
    queryFn: () => serviceHandler<TData>({ method: Method.Get, url, params }),
    ...options,
  });
}

export function usePost<TData = any, TBody = any>(
  url: string,
  opts?: Omit<UseMutationOptions<TData, any, TBody>, "mutationFn"> &
    Pick<ServiceHandlerParams<TBody>, "hasFile">
) {
  return useMutation<TData, any, TBody>({
    mutationFn: (body: TBody) =>
      serviceHandler<TData, TBody>({
        method: Method.Post,
        url,
        data: body,
        hasFile: opts?.hasFile,
      }),
    ...opts,
  });
}
