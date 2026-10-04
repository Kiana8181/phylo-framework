import type { AxiosRequestConfig, AxiosResponse } from "axios";
import { http } from "./client";
import { isEnvelope } from "@phylo/contracts";

export enum Method {
  Get = "get",
  Post = "post",
  Put = "put",
  Patch = "patch",
  Delete = "delete",
}

export type ServiceHandlerParams<TBody = unknown> = {
  method: Method;
  url: string;
  data?: TBody;
  params?: Record<string, any>;
  config?: Omit<AxiosRequestConfig, "method" | "url" | "data" | "params">;
  hasFile?: boolean;
  allowDuplicateRequests?: boolean;
  onSuccess?: (data: any) => void;
  onFailure?: (error: any) => void;
  onFinal?: () => void;
};

const requestCache = new Map<string, true>();

export async function serviceHandler<TResp = any, TBody = unknown>({
  method,
  url,
  data,
  params,
  config,
  hasFile = false,
  allowDuplicateRequests = false,
  onSuccess,
  onFailure,
  onFinal,
}: ServiceHandlerParams<TBody>): Promise<TResp> {
  let isFD = typeof FormData !== "undefined" && data instanceof FormData;

  // 🔁 Only transform to FormData when caller passed a plain object + hasFile=true
  if (!isFD && data && hasFile) {
    const form = new FormData();
    Object.entries(data as Record<string, any>).forEach(([k, v]) => {
      if (v == null) return;
      if (Array.isArray(v)) v.forEach((item) => form.append(k, item as Blob));
      else form.append(k, v as Blob);
    });
    data = form as any;
    isFD = true;
  }

  // ❌ Do NOT set Content-Type for FormData; let axios/browser set boundaries
  if (isFD) {
    config = { ...(config ?? {}), headers: { ...(config?.headers ?? {}) } };
    if (config.headers && "Content-Type" in config.headers) {
      delete config.headers["Content-Type"];
    }
  }

  const key = `${method}-${url}-${JSON.stringify(params)}-${
    isFD ? "formdata" : JSON.stringify(data)
  }`;
  if (!allowDuplicateRequests && requestCache.has(key))
    return Promise.resolve(null as any);
  requestCache.set(key, true);

  try {
    const resp: AxiosResponse<any> = await http.request({
      method,
      url,
      data,
      params,
      ...config,
    });
    const raw = resp.data;

    if (isEnvelope(raw)) {
      if (raw.status === "success") {
        onSuccess?.(raw.data);
        return raw.data as TResp;
      }
      throw new Error(raw.message || "Request failed");
    }

    onSuccess?.(raw);
    return raw as TResp;
  } catch (e: any) {
    onFailure?.(e?.response?.data ?? e);
    throw e?.response?.data ?? e;
  } finally {
    requestCache.delete(key);
    onFinal?.();
  }
}
