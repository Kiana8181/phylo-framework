"use client";

import { Card } from "@/components/ui/card";

export default function RunProgress({
  runId,
  status,
  progress,
  message,
}: {
  runId: string;
  status?: string;
  progress: number;
  message?: string;
}) {
  const badge =
    status === "DONE"
      ? "bg-green-100 text-green-700 border-green-200"
      : status === "ERROR"
      ? "bg-red-100 text-red-700 border-red-200"
      : "bg-amber-100 text-amber-700 border-amber-200";

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-sm">
          Run ID: <span className="font-mono">{runId}</span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded border ${badge}`}>
          {status ?? "PENDING"}
        </span>
      </div>

      <div className="text-sm">
        {status ?? "PENDING"}
        {Number.isFinite(progress) ? ` (${progress}%)` : ""}
        {message ? ` — ${message}` : ""}
      </div>

      <div className="h-2 w-full bg-muted rounded overflow-hidden">
        <div
          className="h-full rounded bg-gradient-to-r from-blue-500 to-indigo-500 transition-[width]"
          style={{ width: `${progress ?? 0}%` }}
        />
      </div>
    </Card>
  );
}
