import axios, { type InternalAxiosRequestConfig } from "axios";
import { apiBaseURL } from "@/lib/config";
import { notify } from "@/lib/notify";
import { getAccessToken, getRefreshToken, setTokens, clearTokens } from "@/lib/auth/storage";
import { authApi } from "@/features/auth/api";
import { getApiErrorMessage, isAuthRequestUrl } from "@/lib/http/errors";

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
    const msg = getApiErrorMessage(err, "Request failed");
    const isAuthEndpoint = isAuthRequestUrl(config?.url);

    if (status === 401 && config && !config._retry) {
      const refreshToken = getRefreshToken();
      const isRefreshEndpoint = config.url?.includes("/auth/refresh");

      if (!isRefreshEndpoint && !isAuthEndpoint && refreshToken) {
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

    if (!isAuthEndpoint) {
      notify.error("Request failed", msg);
    }
    return Promise.reject(err);
  }
);
