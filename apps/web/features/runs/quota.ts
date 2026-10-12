import type { RunLimitCode, RunQuotaResponse } from "@phylo/contracts";

/** Codes the API uses when it refuses to create a run because of a limit. */
export const RUN_LIMIT_CODES: readonly RunLimitCode[] = [
  "RUN_QUOTA_EXCEEDED",
  "RUN_SUBMISSION_LIMIT_EXCEEDED",
  "QUEUE_FULL",
];

/** The limit code carried by a failed create-run request, if that is why it failed. */
export function runLimitCode(error: unknown): RunLimitCode | null {
  const code = (error as { data?: { code?: unknown } } | null)?.data?.code;
  return RUN_LIMIT_CODES.includes(code as RunLimitCode) ? (code as RunLimitCode) : null;
}

export function runLimitTitle(code: RunLimitCode): string {
  if (code === "QUEUE_FULL") return "Your run queue is full";
  if (code === "RUN_SUBMISSION_LIMIT_EXCEEDED") return "Too many submissions this hour";
  return "Hourly run limit reached";
}

/**
 * Whole seconds left until `resetAt`, never negative. The server's clock is the
 * reference: `serverNow`/`clientNowAtFetch` remove any difference between it
 * and the browser's clock, so a wrong local clock cannot shorten the wait.
 */
export function secondsUntilReset(
  resetAt: string | null | undefined,
  serverNow: string | null | undefined,
  clientNowAtFetch: number,
  clientNow: number,
): number {
  if (!resetAt) return 0;
  const reset = Date.parse(resetAt);
  if (Number.isNaN(reset)) return 0;
  const server = serverNow ? Date.parse(serverNow) : NaN;
  const offset = Number.isNaN(server) ? 0 : server - clientNowAtFetch;
  return Math.max(0, Math.ceil((reset - (clientNow + offset)) / 1000));
}

/** "4:07", "59:59", "1:00:00". */
export function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const two = (n: number) => String(n).padStart(2, "0");
  return hours > 0 ? `${hours}:${two(minutes)}:${two(seconds)}` : `${minutes}:${two(seconds)}`;
}

/** One-line summary of the hourly allowance, or null when there is no hourly limit. */
export function quotaUsageLabel(quota: RunQuotaResponse | null | undefined): string | null {
  const hourly = quota?.hourly;
  if (!hourly || hourly.limit == null) return null;
  return `${hourly.used} of ${hourly.limit} runs used this hour`;
}

/** The limit whose reset time ends the current block (null for a full queue). */
export function blockingResetAt(quota: RunQuotaResponse | null | undefined): string | null {
  if (!quota || quota.can_submit) return null;
  if (quota.blocked_by === "RUN_QUOTA_EXCEEDED") return quota.hourly.reset_at;
  if (quota.blocked_by === "RUN_SUBMISSION_LIMIT_EXCEEDED") return quota.submissions.reset_at;
  return null;
}
