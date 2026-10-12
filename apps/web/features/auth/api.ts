import { http } from "@/lib/http/client";
import { apiBaseURL } from "@/lib/config";
import { API_ROUTES } from "@phylo/contracts";
import { solveCaptcha } from "./captcha";

export type AuthUser = {
  id: string;
  email: string;
  username: string;
  email_verified?: boolean;
  verification_required?: boolean;
};

/** Sign-up answer while email verification is required: no session yet, a link was emailed. */
export type RegistrationPending = { verification_required: true; message: string };

export function isRegistrationPending(value: unknown): value is RegistrationPending {
  return typeof value === "object" && value !== null && (value as RegistrationPending).verification_required === true;
}

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
  // The three public forms carry the answer to a proof-of-work challenge
  // (features/auth/captcha.ts). It is fetched and solved here, so every caller
  // gets it right; when the server does not ask for one, nothing is sent.
  async login(email: string, password: string): Promise<TokenResponse> {
    const captcha = await solveCaptcha();
    const { data } = await http.post<TokenResponse>(API_ROUTES.authLogin(), {
      email,
      password,
      captcha,
    });
    return data;
  },

  /** Either a session (verification not required) or "a link was emailed". */
  async register(
    email: string,
    username: string,
    password: string
  ): Promise<TokenResponse | RegistrationPending> {
    const captcha = await solveCaptcha();
    const { data } = await http.post<TokenResponse | RegistrationPending>(API_ROUTES.authRegister(), {
      email,
      username,
      password,
      captcha,
    });
    return data;
  },

  async forgotPassword(email: string): Promise<ForgotPasswordResponse> {
    const captcha = await solveCaptcha();
    const { data } = await http.post<ForgotPasswordResponse>(
      API_ROUTES.authForgotPassword(),
      { email, captcha }
    );
    return data;
  },

  /** Confirm an email address with the token from the emailed link; signs the account in. */
  async verifyEmail(token: string): Promise<TokenResponse> {
    const { data } = await http.post<TokenResponse>(API_ROUTES.authVerifyEmail(), { token });
    return data;
  },

  /** Ask for a new confirmation link for the signed-in account. */
  async resendVerification(): Promise<{ email_verified: boolean; message: string }> {
    const { data } = await http.post<{ email_verified: boolean; message: string }>(
      API_ROUTES.authResendVerification()
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

  /** The URL to send the browser to, and the `state` to keep and send back with the code. */
  async getGoogleAuthUrl(): Promise<{ auth_url: string; state: string }> {
    const { data } = await http.get<{ auth_url: string; state: string }>(API_ROUTES.authGoogle());
    return data;
  },

  async loginWithGoogleCode(code: string, state: string): Promise<TokenResponse> {
    const { data } = await http.post<TokenResponse>(API_ROUTES.authGoogle(), {
      code,
      state,
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
