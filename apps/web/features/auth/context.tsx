"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  getStoredUser,
  setTokens,
  clearTokens,
  type StoredUser,
} from "@/lib/auth/storage";
import { authApi, isRegistrationPending } from "./api";

type AuthContextValue = {
  user: StoredUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /** Resolves to `{ pending: true }` when a confirmation link was emailed and
   *  the account is not signed in yet. */
  register: (email: string, username: string, password: string) => Promise<{ pending: boolean; message?: string }>;
  /** Ask the server again who the user is (e.g. after confirming the email address). */
  refreshUser: () => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: StoredUser | null) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<StoredUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const setUser = useCallback((u: StoredUser | null) => {
    setUserState(u);
  }, []);

  useEffect(() => {
    const stored = getStoredUser();
    const token = typeof window !== "undefined" ? localStorage.getItem("phylo_access_token") : null;
    if (!token) {
      setUserState(null);
      setIsLoading(false);
      return;
    }
    if (stored) {
      setUserState(stored);
    }
    authApi
      .me()
      .then((me) => {
        const fresh = {
          id: me.id,
          email: me.email,
          username: me.username,
          email_verified: me.email_verified,
          verification_required: me.verification_required,
        };
        setUserState(fresh);
      })
      .catch(() => {
        clearTokens();
        setUserState(null);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    setTokens(res.access_token, res.refresh_token, res.user);
    setUserState(res.user);
  }, []);

  const register = useCallback(
    async (email: string, username: string, password: string) => {
      const res = await authApi.register(email, username, password);
      if (isRegistrationPending(res)) {
        return { pending: true, message: res.message };
      }
      setTokens(res.access_token, res.refresh_token, res.user);
      setUserState(res.user);
      return { pending: false };
    },
    []
  );

  const refreshUser = useCallback(async () => {
    const me = await authApi.me();
    setUserState({
      id: me.id,
      email: me.email,
      username: me.username,
      email_verified: me.email_verified,
      verification_required: me.verification_required,
    });
  }, []);

  const logout = useCallback(async () => {
    await authApi.logout();
    clearTokens();
    setUserState(null);
    if (typeof window !== "undefined") {
      window.location.href = "/auth";
    }
  }, []);

  const value: AuthContextValue = {
    user,
    isAuthenticated: !!user,
    isLoading,
    login,
    register,
    refreshUser,
    logout,
    setUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
