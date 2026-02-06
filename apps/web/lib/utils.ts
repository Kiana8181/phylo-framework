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