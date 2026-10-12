/** What the API says about how long a run's results are kept. */
export type RetentionFields = {
  expires_at?: string | null;
  results_expired?: boolean;
  results_expired_at?: string | null;
};

export type RetentionState =
  | { kind: "none" }
  /** Still there. `daysLeft` is whole days, rounded down; `soon` inside the last week. */
  | { kind: "kept"; until: string; daysLeft: number; soon: boolean; due: boolean }
  /** Removed. `on` is the date it happened (or was due), when known. */
  | { kind: "expired"; on: string | null };

/** From this many days before the date on, the notice is highlighted. */
export const EXPIRY_WARNING_DAYS = 7;

const DAY_MS = 24 * 60 * 60 * 1000;

/** YYYY-MM-DD in UTC: the same date the notification email and the API's messages use. */
export function retentionDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const time = Date.parse(iso);
  return Number.isNaN(time) ? null : new Date(time).toISOString().slice(0, 10);
}

export function retentionState(run: RetentionFields | null | undefined, now: number = Date.now()): RetentionState {
  if (!run) return { kind: "none" };
  if (run.results_expired) {
    return { kind: "expired", on: retentionDate(run.results_expired_at) ?? retentionDate(run.expires_at) };
  }
  const until = retentionDate(run.expires_at);
  if (!until) return { kind: "none" };
  const left = Date.parse(run.expires_at as string) - now;
  const daysLeft = Math.max(0, Math.floor(left / DAY_MS));
  return { kind: "kept", until, daysLeft, soon: daysLeft < EXPIRY_WARNING_DAYS, due: left <= 0 };
}

/** "58 days left", "1 day left", "less than a day left". */
export function daysLeftLabel(daysLeft: number): string {
  if (daysLeft <= 0) return "less than a day left";
  return `${daysLeft} day${daysLeft === 1 ? "" : "s"} left`;
}

/** The code the API answers with (HTTP 410) for anything that belonged to expired results. */
export const RESULT_EXPIRED_CODE = "RESULT_EXPIRED";

export function isResultExpiredError(error: unknown): boolean {
  return (error as { data?: { code?: unknown } } | null)?.data?.code === RESULT_EXPIRED_CODE;
}

/** The code the API answers with (HTTP 413) for a file over the upload limit. */
export const UPLOAD_TOO_LARGE_CODE = "UPLOAD_TOO_LARGE";

export function isUploadTooLargeError(error: unknown): boolean {
  return (error as { data?: { code?: unknown } } | null)?.data?.code === UPLOAD_TOO_LARGE_CODE;
}
