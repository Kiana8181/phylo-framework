import { describe, expect, it } from "vitest";
import type { RunQuotaResponse } from "@phylo/contracts";
import {
  blockingResetAt,
  formatCountdown,
  quotaUsageLabel,
  runLimitCode,
  runLimitTitle,
  secondsUntilReset,
} from "../quota";

const window_ = (over: Partial<RunQuotaResponse["hourly"]> = {}): RunQuotaResponse["hourly"] => ({
  limit: 5, used: 0, remaining: 5, window_seconds: 3600, reset_at: null, retry_after_seconds: null, ...over,
});

export const quota = (over: Partial<RunQuotaResponse> = {}): RunQuotaResponse => ({
  can_submit: true,
  blocked_by: null,
  message: null,
  retry_after_seconds: null,
  hourly: window_(),
  submissions: window_({ limit: 30, remaining: 30 }),
  queue: { max_queued: 5, queued_count: 0, unfinished: 0, can_add: true },
  server_time: "2026-01-01T12:00:00+00:00",
  ...over,
});

describe("run limit errors", () => {
  it.each(["RUN_QUOTA_EXCEEDED", "RUN_SUBMISSION_LIMIT_EXCEEDED", "QUEUE_FULL"] as const)(
    "recognises %s from the API error body", (code) => {
      expect(runLimitCode({ status: "error", message: "x", data: { code } })).toBe(code);
      expect(runLimitTitle(code)).toMatch(/limit|queue|submissions/i);
    });
  it.each([null, undefined, new Error("network"), { data: null }, { data: { code: "DATASET_DELETED" } }, { data: { code: 429 } }])(
    "does not mistake another failure for a limit (%j)", (error) => {
      expect(runLimitCode(error)).toBeNull();
    });
});

describe("countdown", () => {
  it.each([[0, "0:00"], [7, "0:07"], [247, "4:07"], [3599, "59:59"], [3600, "1:00:00"], [3725, "1:02:05"], [-5, "0:00"]])(
    "formats %d seconds as %s", (seconds, text) => {
      expect(formatCountdown(seconds)).toBe(text);
    });

  it("counts down to the reset time and never below zero", () => {
    const serverNow = "2026-01-01T12:00:00+00:00";
    const reset = "2026-01-01T12:10:00+00:00";
    const fetched = Date.parse(serverNow);
    expect(secondsUntilReset(reset, serverNow, fetched, fetched)).toBe(600);
    expect(secondsUntilReset(reset, serverNow, fetched, fetched + 61_500)).toBe(539);
    expect(secondsUntilReset(reset, serverNow, fetched, fetched + 3_600_000)).toBe(0);
    expect(secondsUntilReset(null, serverNow, fetched, fetched)).toBe(0);
    expect(secondsUntilReset("not a date", serverNow, fetched, fetched)).toBe(0);
  });

  it("uses the server's clock, so a wrong browser clock does not change the wait", () => {
    const serverNow = "2026-01-01T12:00:00+00:00";
    const reset = "2026-01-01T12:10:00+00:00";
    const twoHoursFast = Date.parse(serverNow) + 2 * 3_600_000;       // browser clock is 2 h ahead
    expect(secondsUntilReset(reset, serverNow, twoHoursFast, twoHoursFast)).toBe(600);
    expect(secondsUntilReset(reset, serverNow, twoHoursFast, twoHoursFast + 30_000)).toBe(570);
    const dayBehind = Date.parse(serverNow) - 86_400_000;
    expect(secondsUntilReset(reset, serverNow, dayBehind, dayBehind)).toBe(600);
    // Without a server time the browser clock is all there is.
    expect(secondsUntilReset(reset, null, 0, Date.parse(serverNow))).toBe(600);
  });
});

describe("quota summary", () => {
  it("describes the hourly allowance, or nothing when there is no hourly limit", () => {
    expect(quotaUsageLabel(quota({ hourly: window_({ used: 3, remaining: 2 }) }))).toBe("3 of 5 runs used this hour");
    expect(quotaUsageLabel(quota({ hourly: window_({ limit: null, remaining: null }) }))).toBeNull();
    expect(quotaUsageLabel(null)).toBeNull();
  });

  it("knows which limit ends the block, and that a full queue has no reset time", () => {
    const at = "2026-01-01T12:10:00+00:00";
    expect(blockingResetAt(quota())).toBeNull();
    expect(blockingResetAt(quota({ can_submit: false, blocked_by: "RUN_QUOTA_EXCEEDED", hourly: window_({ reset_at: at }) }))).toBe(at);
    expect(blockingResetAt(quota({
      can_submit: false, blocked_by: "RUN_SUBMISSION_LIMIT_EXCEEDED",
      submissions: window_({ reset_at: at }), hourly: window_({ reset_at: "2026-01-01T12:01:00+00:00" }),
    }))).toBe(at);
    expect(blockingResetAt(quota({ can_submit: false, blocked_by: "QUEUE_FULL" }))).toBeNull();
    expect(blockingResetAt(undefined)).toBeNull();
  });
});
