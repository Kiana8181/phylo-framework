import { http } from "@/lib/http/client";
import { apiBaseURL } from "@/lib/config";
import { API_ROUTES } from "@phylo/contracts";

export type AuthUser = { id: string; email: string; username: string };

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: AuthUser;
};

export type ForgotPasswordResponse = {
  message: string;
  reset_token?: string;
};

export const authApi = {
  async login(email: string, password: string): Promise<TokenResponse> {
    const { data } = await http.post<TokenResponse>(API_ROUTES.authLogin(), {
      email,
      password,
    });
    return data;
  },

  async register(
    email: string,
    username: string,
    password: string
  ): Promise<TokenResponse> {
    const { data } = await http.post<TokenResponse>(API_ROUTES.authRegister(), {
      email,
      username,
      password,
    });
    return data;
  },

  async forgotPassword(email: string): Promise<ForgotPasswordResponse> {
    const { data } = await http.post<ForgotPasswordResponse>(
      API_ROUTES.authForgotPassword(),
      { email }
    );
    return data;
  },

  async resetPassword(token: string, newPassword: string): Promise<{ message: string }> {
    const { data } = await http.post<{ message: string }>(
      API_ROUTES.authResetPassword(),
      { token, new_password: newPassword }
    );
    return data;
  },

  async me(): Promise<AuthUser> {
    const { data } = await http.get<AuthUser>(API_ROUTES.authMe());
    return data;
  },

  async logout(): Promise<void> {
    try {
      await http.post(API_ROUTES.authLogout());
    } catch {
      // ignore
    }
  },

  async getGoogleAuthUrl(): Promise<{ auth_url: string }> {
    const { data } = await http.get<{ auth_url: string }>(API_ROUTES.authGoogle());
    return data;
  },

  async loginWithGoogleCode(code: string): Promise<TokenResponse> {
    const { data } = await http.post<TokenResponse>(API_ROUTES.authGoogle(), {
      code,
    });
    return data;
  },

  /** Used by the axios interceptor to refresh tokens. Uses fetch to avoid interceptor loop. */
  async refresh(refreshToken: string): Promise<TokenResponse> {
    const base = apiBaseURL();
    const url = `${base.replace(/\/+$/, "")}${API_ROUTES.authRefresh()}`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      const text = await res.text();
      let msg = text;
      try {
        const j = JSON.parse(text);
        msg = j.detail || j.message || text;
      } catch {}
      throw new Error(msg);
    }
    return res.json();
  },
};
