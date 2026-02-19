import axios, { type InternalAxiosRequestConfig } from "axios";
import { apiBaseURL } from "@/lib/config";
import { notify } from "@/lib/notify";
import { getAccessToken, getRefreshToken, setTokens, clearTokens } from "@/lib/auth/storage";
import { authApi } from "@/features/auth/api";

export const http = axios.create({
  baseURL: apiBaseURL(),
  timeout: 60_000,
  withCredentials: true,
  headers: { Accept: "application/json" },
});

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
}> = [];

function processQueue(error: unknown = null, token: string | null = null) {
  failedQueue.forEach((p) => (error ? p.reject(error) : p.resolve(token)));
  failedQueue = [];
}

http.interceptors.response.use(
  (res) => res,
  async (err) => {
    const status = err?.response?.status;
    const config = err?.config;
    const data = err?.response?.data as any;

    const msg =
      data?.message ??
      (Array.isArray(data?.detail) ? data.detail[0]?.msg : data?.detail) ??
      data?.error ??
      err?.message ??
      "Request failed";

    if (status === 401 && config && !config._retry) {
      const refreshToken = getRefreshToken();
      const isAuthEndpoint =
        config.url?.includes("/auth/refresh") || config.url?.includes("/auth/login") || config.url?.includes("/auth/register");

      if (!isAuthEndpoint && refreshToken) {
        if (isRefreshing) {
          return new Promise((resolve, reject) => {
            failedQueue.push({ resolve, reject });
          }).then(() => http(config));
        }
        config._retry = true;
        isRefreshing = true;
        try {
          const res = await authApi.refresh(refreshToken);
          setTokens(res.access_token, res.refresh_token, res.user);
          processQueue(null, res.access_token);
          config.headers.Authorization = `Bearer ${res.access_token}`;
          return http(config);
        } catch (refreshErr) {
          processQueue(refreshErr, null);
          clearTokens();
          if (typeof window !== "undefined") {
            notify.error("Session expired", "Please log in again.");
            window.location.href = "/auth";
          }
          return Promise.reject(refreshErr);
        } finally {
          isRefreshing = false;
        }
      }

      clearTokens();
      if (typeof window !== "undefined" && !isAuthEndpoint) {
        window.location.href = "/auth";
      }
      return Promise.reject(err);
    }

    notify.error("Request failed", `${status ?? ""} ${msg}`.trim());
    return Promise.reject(err);
  }
);
