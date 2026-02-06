const AUTH_ACCESS = "phylo_access_token";
const AUTH_REFRESH = "phylo_refresh_token";
const AUTH_USER = "phylo_user";

export type StoredUser = { id: string; email: string; username: string };

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_ACCESS);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_REFRESH);
}

export function getStoredUser(): StoredUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(AUTH_USER);
    if (!raw) return null;
    return JSON.parse(raw) as StoredUser;
  } catch {
    return null;
  }
}

export function setTokens(
  accessToken: string,
  refreshToken: string,
  user?: StoredUser
): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(AUTH_ACCESS, accessToken);
  localStorage.setItem(AUTH_REFRESH, refreshToken);
  if (user) localStorage.setItem(AUTH_USER, JSON.stringify(user));
}

export function clearTokens(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(AUTH_ACCESS);
  localStorage.removeItem(AUTH_REFRESH);
  localStorage.removeItem(AUTH_USER);
}
