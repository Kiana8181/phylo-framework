import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { apiBaseURL } from "@/lib/config"
import { getAccessToken } from "@/lib/auth/storage"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Post FormData with upload progress tracking.
 * URL should be relative (will be joined with API base URL).
 */
export function postFormWithProgress(url: string, fd: FormData, onProgress: (pct: number) => void) {
  return new Promise<any>((resolve, reject) => {
    // Build full URL from base + relative path
    const base = apiBaseURL();
    const fullUrl = url.startsWith("http") 
      ? url 
      : `${base.replace(/\/+$/, "")}/${url.replace(/^\/+/, "")}`;
    
    const xhr = new XMLHttpRequest();
    xhr.open("POST", fullUrl);
    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded * 100) / e.total));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { 
          const parsed = JSON.parse(xhr.responseText);
          // Handle envelope format from backend
          if (parsed.status === "success" && parsed.data) {
            resolve(parsed.data);
          } else {
            resolve(parsed);
          }
        }
        catch { resolve(xhr.responseText); }
      } else {
        reject(new Error(xhr.responseText || `HTTP ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error"));
    xhr.send(fd);
  });
}

export type AbortableUpload<T = any> = {
  promise: Promise<T>;
  abort: () => void;
};

/**
 * Upload a single file body (PUT) with progress tracking and cancellation.
 * URL should be relative (joined with the API base URL). Returns a promise
 * plus an abort() handle that cancels the in-flight browser request.
 */
export function uploadWithProgress<T = any>(
  url: string,
  body: Blob | File,
  onProgress: (pct: number) => void,
): AbortableUpload<T> {
  const base = apiBaseURL();
  const fullUrl = url.startsWith("http")
    ? url
    : `${base.replace(/\/+$/, "")}/${url.replace(/^\/+/, "")}`;

  const xhr = new XMLHttpRequest();
  let aborted = false;

  const promise = new Promise<T>((resolve, reject) => {
    xhr.open("PUT", fullUrl);
    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    const type = (body as File)?.type;
    if (type) xhr.setRequestHeader("Content-Type", type);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded * 100) / e.total));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const parsed = JSON.parse(xhr.responseText);
          if (parsed && parsed.status === "success" && parsed.data) {
            resolve(parsed.data as T);
          } else {
            resolve(parsed as T);
          }
        } catch {
          resolve(xhr.responseText as unknown as T);
        }
      } else {
        reject(new Error(xhr.responseText || `HTTP ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error"));
    xhr.onabort = () => {
      const err = new Error("Upload cancelled");
      (err as any).aborted = true;
      reject(err);
    };
    xhr.send(body);
  });

  return {
    promise,
    abort: () => {
      if (aborted) return;
      aborted = true;
      try {
        xhr.abort();
      } catch {
        /* no-op */
      }
    },
  };
}