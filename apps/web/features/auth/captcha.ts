import { http } from "@/lib/http/client";
import { solveChallenge } from "@/lib/pow";
import { API_ROUTES } from "@phylo/contracts";

/** What GET /auth/challenge returns. */
export type CaptchaChallenge =
  | { enabled: false }
  | { enabled: true; algorithm: string; challenge: string; difficulty: number; expires_at: string };

/** What a protected form sends along. */
export type CaptchaSolution = { challenge: string; counter: number };

/**
 * Get a challenge and solve it. Returns `undefined` when the server does not
 * ask for one. The search runs in the browser and takes a fraction of a
 * second at the default difficulty; no third party is involved.
 */
export async function solveCaptcha(signal?: AbortSignal): Promise<CaptchaSolution | undefined> {
  const { data } = await http.get<CaptchaChallenge>(API_ROUTES.authChallenge());
  if (!data?.enabled) return undefined;
  const counter = await solveChallenge(data.challenge, data.difficulty, { signal });
  return { challenge: data.challenge, counter };
}
