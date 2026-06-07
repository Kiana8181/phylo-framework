"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertCircle, ChevronDown, ChevronRight } from "lucide-react";
import { formatRunDuration } from "@/lib/runDuration";
import { useCancelRun } from "@/features/runs/hooks";
import { notify } from "@/lib/notify";
import RunStageFlowchart from "./RunStageFlowchart";
import { humanizeStage } from "@phylo/contracts";

const MAX_INLINE_ERROR = 200;

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
  const [detailsOpen, setDetailsOpen] = useState(false);
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
  const httpStatus = (statusError as any)?.response?.status;
  const apiErrorMessage =
    httpStatus === 403
      ? "You don't have access to this run. It may have been started in a different session."
      : httpStatus === 404
      ? "Run not found."
      : isStatusError
      ? (statusError as Error)?.message || "Could not load status."
      : null;

  const runErrorMessage = status === "ERROR" ? message : null;
  const showExpandableError = runErrorMessage && runErrorMessage.length > MAX_INLINE_ERROR;
  const shortRunError =
    runErrorMessage && runErrorMessage.length > MAX_INLINE_ERROR
      ? runErrorMessage.slice(0, MAX_INLINE_ERROR).trim() + "…"
      : runErrorMessage;

  const badge = getStatusBadge(status, isStatusError);
  const label = getStatusLabel(status, isStatusError);
  const durationLabel = formatRunDuration(startedAt, finishedAt);
  const displayStage =
    status === "RUNNING" && stage === "QUEUED"
      ? "Running method"
      : humanizeStage(stage) || (status ?? "PENDING");

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-sm min-w-0">
          Run ID: <span className="font-mono truncate">{runId}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded border shrink-0 ${badge}`}>
            {label}
          </span>
          {durationLabel && !isStatusError && (
            <span className="text-xs px-2 py-0.5 rounded border shrink-0 bg-muted text-muted-foreground">
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
        <div className="flex items-start gap-2 rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 p-3 text-sm text-red-800 dark:text-red-200">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <span className="break-words">{apiErrorMessage}</span>
        </div>
      )}

      {!isStatusError && status === "ERROR" && runErrorMessage && (
        <div className="rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 overflow-hidden">
          <div className="p-3 text-sm text-red-800 dark:text-red-200">
            {!showExpandableError && <span className="break-words whitespace-pre-wrap">{runErrorMessage}</span>}
            {showExpandableError && (
              <>
                <span className="break-words whitespace-pre-wrap">{shortRunError}</span>
                <button
                  type="button"
                  onClick={() => setDetailsOpen((o) => !o)}
                  className="mt-2 flex items-center gap-1 text-xs font-medium text-red-600 dark:text-red-300 hover:underline cursor-pointer"
                >
                  {detailsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                  {detailsOpen ? "Hide full error" : "Show full error details"}
                </button>
                {detailsOpen && (
                  <pre className="mt-2 p-2 rounded bg-red-100/50 dark:bg-red-900/20 text-xs whitespace-pre-wrap break-words overflow-auto max-h-64 border border-red-200/50 dark:border-red-800/50">
                    {runErrorMessage}
                  </pre>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {!isStatusError && status !== "ERROR" && (
        <div className="text-sm">
          <span className="font-medium">{displayStage}</span>
          {Number.isFinite(progress) ? (
            <span className="text-muted-foreground"> ({progress}%)</span>
          ) : null}
          {(stageMessage || message) ? (
            <span className="text-muted-foreground">
              {" "}
              — {stageMessage || message}
            </span>
          ) : null}
        </div>
      )}

      {!isStatusError && (
        <div className="h-2 w-full bg-muted rounded overflow-hidden">
          <div
            className="h-full rounded bg-primary transition-[width]"
            style={{ width: `${progress ?? 0}%` }}
          />
        </div>
      )}

      {!isStatusError && (
        <RunStageFlowchart
          methodId={methodId}
          status={status}
          stage={stage}
          progress={progress}
          stageMessage={stageMessage}
        />
      )}
    </Card>
  );
}
