"use client";

import { useEffect, useRef, useState } from "react";
import { Clock } from "lucide-react";
import type { RunQuotaResponse } from "@phylo/contracts";
import {
  blockingResetAt,
  formatCountdown,
  quotaUsageLabel,
  runLimitTitle,
  secondsUntilReset,
} from "@/features/runs/quota";

/**
 * Tells the user where they stand against the limits on creating runs.
 *
 * While a run can be submitted this is one quiet line ("3 of 5 runs used this
 * hour"). When a limit is reached it becomes a notice with the server's
 * explanation and, for the time-based limits, a countdown to the moment the
 * next run becomes possible. `onReset` fires once when that moment arrives so
 * the caller can ask the server again.
 */
export default function RunQuotaNotice({
  quota,
  fetchedAt,
  onReset,
  className,
}: {
  quota: RunQuotaResponse | null | undefined;
  /** When `quota` was received (ms since epoch), e.g. react-query's dataUpdatedAt. */
  fetchedAt: number;
  onReset?: () => void;
  className?: string;
}) {
  const resetAt = blockingResetAt(quota);
  const [now, setNow] = useState(() => Date.now());
  const firedFor = useRef<string | null>(null);

  useEffect(() => {
    if (!resetAt) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [resetAt]);

  const secondsLeft = secondsUntilReset(resetAt, quota?.server_time, fetchedAt, now);

  useEffect(() => {
    if (resetAt && secondsLeft === 0 && firedFor.current !== resetAt) {
      firedFor.current = resetAt;
      onReset?.();
    }
  }, [resetAt, secondsLeft, onReset]);

  if (!quota) return null;

  if (quota.can_submit) {
    const usage = quotaUsageLabel(quota);
    if (!usage) return null;
    return (
      <p className={`text-xs text-muted-foreground ${className ?? ""}`} data-testid="run-quota-usage">
        {usage}
      </p>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="run-quota-blocked"
      className={`flex gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200 ${className ?? ""}`}
    >
      <Clock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 space-y-1">
        <p className="font-medium">{quota.blocked_by ? runLimitTitle(quota.blocked_by) : "Runs are limited"}</p>
        {quota.message && <p>{quota.message}</p>}
        {resetAt && (
          <p>
            {secondsLeft > 0 ? (
              <>
                You can start another run in{" "}
                <span className="font-mono font-semibold tabular-nums" data-testid="run-quota-countdown">
                  {formatCountdown(secondsLeft)}
                </span>
                .
              </>
            ) : (
              "Checking whether you can start a run again…"
            )}
          </p>
        )}
      </div>
    </div>
  );
}
