import { createHash } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/http/client", () => ({ http: { get, post } }));
vi.mock("@/lib/config", () => ({ apiBaseURL: () => "http://api.test" }));

import { solveCaptcha } from "../captcha";
import { authApi, isRegistrationPending } from "../api";

const CHALLENGE = { enabled: true, algorithm: "sha256-leading-zero-bits", challenge: "payload.signature", difficulty: 8, expires_at: "2030-01-01T00:00:00+00:00" };

function zeroBits(text: string): number {
  let bits = 0;
  for (const byte of createHash("sha256").update(text).digest()) {
    if (byte === 0) { bits += 8; continue; }
    return bits + Math.clz32(byte) - 24;
  }
  return bits;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  post.mockResolvedValue({ data: { access_token: "a", refresh_token: "r", token_type: "bearer", user: { id: "1", email: "e", username: "u" } } });
});

describe("solveCaptcha", () => {
  it("returns nothing when the server does not ask for a check", async () => {
    get.mockResolvedValue({ data: { enabled: false } });
    expect(await solveCaptcha()).toBeUndefined();
  });

  it("answers the server's challenge", async () => {
    get.mockResolvedValue({ data: CHALLENGE });
    const solution = await solveCaptcha();
    expect(get).toHaveBeenCalledWith("/auth/challenge");
    expect(solution?.challenge).toBe("payload.signature");
    expect(zeroBits(`payload.signature:${solution?.counter}`)).toBeGreaterThanOrEqual(8);
  });
});

describe("the public forms send the answer with the request", () => {
  it.each([
    ["login", () => authApi.login("a@b.example", "pw"), "/auth/login"],
    ["register", () => authApi.register("a@b.example", "ada", "pw"), "/auth/register"],
    ["forgot password", () => authApi.forgotPassword("a@b.example"), "/auth/forgot-password"],
  ])("%s", async (_name, call, path) => {
    get.mockResolvedValue({ data: CHALLENGE });
    await call();
    const [url, body] = post.mock.calls[0];
    expect(url).toBe(path);
    expect(body.captcha.challenge).toBe("payload.signature");
    expect(zeroBits(`payload.signature:${body.captcha.counter}`)).toBeGreaterThanOrEqual(8);
    // A fresh challenge per submission: an answer works once.
    await call();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("sends no answer when the check is switched off", async () => {
    get.mockResolvedValue({ data: { enabled: false } });
    await authApi.login("a@b.example", "pw");
    expect(post.mock.calls[0][1].captcha).toBeUndefined();
  });
});

describe("sign-up answers", () => {
  it("tells a session from 'a link was emailed'", async () => {
    get.mockResolvedValue({ data: { enabled: false } });
    post.mockResolvedValueOnce({ data: { verification_required: true, message: "check your email" } });
    const pending = await authApi.register("a@b.example", "ada", "pw");
    expect(isRegistrationPending(pending)).toBe(true);
    const session = await authApi.register("a@b.example", "ada", "pw");
    expect(isRegistrationPending(session)).toBe(false);
    expect(isRegistrationPending(null)).toBe(false);
  });

  it("sends the Google state back with the code", async () => {
    await authApi.loginWithGoogleCode("code-1", "state-1");
    expect(post).toHaveBeenCalledWith("/auth/google", { code: "code-1", state: "state-1" });
  });
});
