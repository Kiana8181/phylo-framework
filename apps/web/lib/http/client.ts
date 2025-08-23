import axios from "axios";
import { getSession, signOut } from "next-auth/react"; // optional
import { apiBaseURL } from "@/lib/config";
import { notify } from "@/lib/notify";

export const http = axios.create({
  baseURL: apiBaseURL(),
  timeout: 60_000,
  withCredentials: true,
  headers: { Accept: "application/json" },
});

// http.interceptors.request.use(async (config) => {
//   try {
//     const session = await getSession().catch(() => null);
//     if (session?.accessToken) {
//       config.headers = config.headers ?? {};
//       (config.headers as any)[
//         "Authorization"
//       ] = `Bearer ${session.accessToken}`;
//     }
//   } catch {}
//   return config;
// });

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status;
    const data = err?.response?.data as any;

    // Handle common shapes: FastAPI {detail}, our envelope {message}, generic {error}
    const msg =
      data?.message ??
      (Array.isArray(data?.detail) ? data.detail[0]?.msg : data?.detail) ??
      data?.error ??
      err?.message ??
      "Unexpected error";

    notify.error("Request failed", `${status ?? ""} ${msg}`.trim());

    if (status === 401) {
      // only if you’re using next-auth
      signOut({ callbackUrl: "/" });
    }
    return Promise.reject(err);
  }
);
