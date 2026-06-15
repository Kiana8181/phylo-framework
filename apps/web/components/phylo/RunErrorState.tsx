"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import errorSvg from "@/assets/error.svg";
import type { RunLogEntry } from "@phylo/contracts";

const MAX_INLINE_ERROR = 280;

export default function RunErrorState({
  runId,
  status,
  methodLabel,
  datasetLabel,
  errorCode,
  errorMessage,
  logs,
  paramsSlot,
  onDismiss,
}: {
  runId: string;
  status?: string;
  methodLabel: string;
  datasetLabel: string;
  errorCode?: string | null;
  errorMessage?: string | null;
  logs?: RunLogEntry[];
  /** Parameters section (the dashboard passes its RunParamsDropdown). */
  paramsSlot?: ReactNode;
  onDismiss?: () => void;
}) {
  const [showFull, setShowFull] = useState(false);
  const message = (errorMessage ?? "").trim();
  const isLong = message.length > MAX_INLINE_ERROR;
  const shortMessage = isLong ? `${message.slice(0, MAX_INLINE_ERROR).trim()}…` : message;
  const hasLogs = Array.isArray(logs) && logs.length > 0;

  return (
    <Card className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-col items-center gap-3 text-center sm:flex-row sm:items-center sm:gap-5 sm:text-left">
        <object
          type="image/svg+xml"
          data={errorSvg.src}
          aria-hidden="true"
          className="size-28 shrink-0"
        />
        <div className="min-w-0 space-y-1">
          <h2 className="text-xl font-semibold">
            {status === "CANCELLED" ? "Run cancelled" : "Run failed"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {status === "CANCELLED"
              ? "This run was cancelled. Start another run to return to the wizard."
              : "This run ended with an error. The details and logs below can help diagnose it."}
          </p>
        </div>
        {onDismiss && (
          <Button className="sm:ml-auto" onClick={onDismiss}>
            Start another run
          </Button>
        )}
      </div>

      {message && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {errorCode && <span className="mr-1 font-semibold">[{errorCode}]</span>}
          <span className="break-words whitespace-pre-wrap">
            {showFull || !isLong ? message : shortMessage}
          </span>
          {isLong && (
            <button
              type="button"
              onClick={() => setShowFull((o) => !o)}
              className="mt-2 flex items-center gap-1 text-xs font-medium hover:underline"
            >
              {showFull ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              {showFull ? "Hide full error" : "Show full error details"}
            </button>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Run ID</p>
          <p className="break-all font-mono text-xs">{runId}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Method</p>
          <p className="text-sm">{methodLabel}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Dataset</p>
          <p className="break-words text-sm">{datasetLabel}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Status</p>
          <p className="text-sm">{status ?? "ERROR"}</p>
        </div>
      </div>

      {paramsSlot}

      {hasLogs && (
        <details className="rounded border bg-card/50 p-3">
          <summary className="cursor-pointer text-sm font-medium">Show model logs</summary>
          <div className="mt-2 max-h-64 space-y-3 overflow-y-auto font-mono text-xs">
            {logs!.map((log, index) => (
              <div key={`err-log-${index}`} className="border-b pb-2 last:border-0 last:pb-0">
                <div className="flex justify-between gap-2 text-[11px]">
                  <span className="font-semibold">{log.step || `Step ${index + 1}`}</span>
                  {typeof log.ok === "boolean" && (
                    <span className={log.ok ? "text-emerald-500" : "text-red-500"}>
                      {log.ok ? "OK" : "FAIL"}
                    </span>
                  )}
                </div>
                {log.cmd && (
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    <span className="font-semibold">cmd: </span>
                    <code className="break-all">{log.cmd}</code>
                  </div>
                )}
                {log.out && <pre className="mt-1 whitespace-pre-wrap">{log.out}</pre>}
              </div>
            ))}
          </div>
        </details>
      )}
    </Card>
  );
}
