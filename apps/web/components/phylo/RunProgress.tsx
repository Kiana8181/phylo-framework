"use client";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { SpinnerIllustration } from "@/components/ui/spinner-illustration";
import { AlertCircle } from "lucide-react";
import { formatRunDuration } from "@/lib/runDuration";
import { useCancelRun } from "@/features/runs/hooks";
import { notify } from "@/lib/notify";
import RunStageFlowchart from "./RunStageFlowchart";
import { humanizeStage } from "@phylo/contracts";

const ACTIVE_STATUSES = new Set(["PENDING", "QUEUED", "RUNNING"]);

function getStatusBadge(status?: string, isError?: boolean) {
  if (isError) return "bg-red-100 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-300 dark:border-red-800";
  if (status === "DONE") return "bg-green-100 text-green-700 border-green-200 dark:bg-green-950/50 dark:text-green-300 dark:border-green-800";
  if (status === "ERROR") return "bg-red-100 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-300 dark:border-red-800";
  return "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800";
}

function getStatusLabel(status?: string, isError?: boolean) {
  if (isError) return "Status unavailable";
  return status ?? "PENDING";
}

export default function RunProgress({
  runId,
  status,
  progress,
  message,
  stage,
  stageMessage,
  cancelRequested,
  methodId,
  startedAt,
  finishedAt,
  statusError,
  onDismiss,
}: {
  runId: string;
  status?: string;
  progress: number;
  message?: string;
  stage?: string | null;
  stageMessage?: string | null;
  cancelRequested?: boolean;
  methodId?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  statusError?: unknown;
  onDismiss?: () => void;
}) {
  const cancelRun = useCancelRun();
  const isCancelling = stage === "CANCELLING" || !!cancelRequested;
  const canStop = !!status && ACTIVE_STATUSES.has(status) && !isCancelling;

  async function handleStop() {
    try {
      await cancelRun.mutateAsync(runId);
      notify.success("Cancelling run…");
    } catch {
      /* error toast handled in hook */
    }
  }

  const isStatusError = !!statusError;
  const httpStatus = (statusError as { response?: { status?: number } })?.response?.status;
  const apiErrorMessage =
    httpStatus === 403
      ? "You don't have access to this run. It may have been started in a different session."
      : httpStatus === 404
      ? "Run not found."
      : isStatusError
      ? (statusError as Error)?.message || "Could not load status."
      : null;

  const badge = getStatusBadge(status, isStatusError);
  const label = getStatusLabel(status, isStatusError);
  const durationLabel = formatRunDuration(startedAt, finishedAt);
  const isActive = !!status && ACTIVE_STATUSES.has(status);
  const displayStage =
    status === "RUNNING" && stage === "QUEUED"
      ? "Running method"
      : humanizeStage(stage) || (status ?? "PENDING");

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 text-sm">
          Run ID: <span className="truncate font-mono">{runId}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`shrink-0 rounded border px-2 py-0.5 text-xs ${badge}`}>{label}</span>
          {durationLabel && !isStatusError && (
            <span className="shrink-0 rounded border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              Duration: {durationLabel}
            </span>
          )}
          {!isStatusError && (canStop || isCancelling) && (
            <Button
              variant="destructive"
              size="sm"
              onClick={handleStop}
              disabled={!canStop || cancelRun.isPending}
              className="shrink-0"
            >
              {isCancelling ? "Cancelling…" : "Stop run"}
            </Button>
          )}
          {onDismiss && (
            <Button variant="ghost" size="sm" onClick={onDismiss} className="shrink-0">
              Dismiss
            </Button>
          )}
        </div>
      </div>

      {isStatusError && apiErrorMessage && (
        <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-200">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="break-words">{apiErrorMessage}</span>
        </div>
      )}

      {!isStatusError && (
        <>
          <div className="flex items-center gap-3">
            {isActive && <SpinnerIllustration className="size-9 shrink-0 text-primary" />}
            <div className="min-w-0 text-sm">
              <p>
                Currently: <span className="font-medium">{displayStage}</span>
                {Number.isFinite(progress) ? (
                  <span className="text-muted-foreground"> ({progress}%)</span>
                ) : null}
              </p>
              {isActive ? (
                <p className="text-xs text-muted-foreground">
                  {stageMessage || message
                    ? `${stageMessage || message} — `
                    : ""}
                  please be patient while your run completes.
                </p>
              ) : (
                (stageMessage || message) && (
                  <p className="text-xs text-muted-foreground">{stageMessage || message}</p>
                )
              )}
            </div>
          </div>

          <div className="relative h-2 w-full overflow-hidden rounded bg-muted">
            <div
              className="h-full rounded bg-primary transition-[width]"
              style={{ width: `${progress ?? 0}%` }}
            />
            {isActive && (
              <div className="phylo-shimmer absolute inset-y-0 left-0 w-1/3 -translate-x-full bg-gradient-to-r from-transparent via-primary/40 to-transparent" />
            )}
          </div>

          <RunStageFlowchart
            methodId={methodId}
            status={status}
            stage={stage}
            progress={progress}
            stageMessage={stageMessage}
          />
        </>
      )}
    </Card>
  );
}
