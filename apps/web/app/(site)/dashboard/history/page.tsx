"use client";

import Link from "next/link";
import { useRunsList } from "@/features/runs/hooks";
import { formatRunDuration } from "@/lib/runDuration";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ExternalLink, Loader2, ChevronLeft, ChevronRight, Copy, GitCompare } from "lucide-react";
import { useState } from "react";
import { notify } from "@/lib/notify";

const PAGE_SIZE = 10;

function formatDate(iso: string | null) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function formatDatasetLabel(datasetName?: string | null, datasetFiles?: string[] | null) {
  if (datasetName && datasetName.trim()) return datasetName;
  if (datasetFiles && datasetFiles.length > 0) return datasetFiles.join(", ");
  return "—";
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    PENDING: "bg-muted text-muted-foreground",
    QUEUED: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
    RUNNING: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
    DONE: "bg-green-500/15 text-green-600 dark:text-green-400",
    ERROR: "bg-destructive/15 text-destructive",
  };
  const cls = map[status] ?? "bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {status}
    </span>
  );
}

export default function RunHistoryPage() {
  const [page, setPage] = useState(0);
  const skip = page * PAGE_SIZE;
  const { data: runs, isLoading, error } = useRunsList({ skip, limit: PAGE_SIZE });

  const hasMore = runs != null && runs.length === PAGE_SIZE;
  const hasPrev = page > 0;

  return (
    <main className="mx-auto max-w-5xl w-full p-4 sm:p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Run history
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          View and manage your past runs.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Runs</CardTitle>
          <CardDescription>Your runs, newest first.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          )}
          {error && (
            <p className="text-destructive text-sm py-4">
              Failed to load runs. Please try again.
            </p>
          )}
          {!isLoading && !error && (!runs || runs.length === 0) && (
            <p className="text-muted-foreground text-sm py-8 text-center">
              No runs yet. Start a run from the Run model page.
            </p>
          )}
          {!isLoading && !error && runs && runs.length > 0 && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-3 px-2 font-medium">Run ID</th>
                      <th className="text-left py-3 px-2 font-medium">Method</th>
                      <th className="text-left py-3 px-2 font-medium">Dataset</th>
                      <th className="text-left py-3 px-2 font-medium">Status</th>
                      <th className="text-left py-3 px-2 font-medium">Duration</th>
                      <th className="text-left py-3 px-2 font-medium">Created</th>
                      <th className="text-right py-3 px-2 font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => {
                      const datasetLabel = formatDatasetLabel(run.dataset_name, run.dataset_files);
                      const durationLabel = formatRunDuration(run.started_at, run.finished_at);
                      return (
                        <tr key={run.id} className="border-b last:border-0">
                          <td className="py-3 px-2 font-mono text-xs">
                            <div className="flex items-center gap-1 max-w-[14rem]">
                              <span className="truncate" title={run.id}>
                                {run.id}
                              </span>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 shrink-0"
                                onClick={() => {
                                  navigator.clipboard.writeText(run.id).then(
                                    () => notify.success("Run ID copied"),
                                    () => notify.error("Copy failed")
                                  );
                                }}
                                title="Copy Run ID"
                                aria-label="Copy Run ID"
                              >
                                <Copy className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </td>
                          <td className="py-3 px-2">{run.method_id}</td>
                          <td className="py-3 px-2 text-muted-foreground">
                            <span
                              className="inline-block max-w-[16rem] truncate align-bottom"
                              title={datasetLabel}
                            >
                              {datasetLabel}
                            </span>
                          </td>
                          <td className="py-3 px-2">
                            {statusBadge(run.status)}
                            {run.progress != null && run.status === "RUNNING" && (
                              <span className="ml-2 text-muted-foreground">
                                {run.progress}%
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-2 text-muted-foreground">
                            {durationLabel ?? "—"}
                          </td>
                          <td className="py-3 px-2 text-muted-foreground">
                            {formatDate(run.created_at)}
                          </td>
                          <td className="py-3 px-2 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Link href={`/dashboard?runId=${run.id}`}>
                                <Button variant="ghost" size="sm" className="gap-1">
                                  View details
                                  <ExternalLink className="h-3 w-3" />
                                </Button>
                              </Link>
                              {run.status === "DONE" && (
                                <Link href={`/dashboard/comparison?baseRunId=${encodeURIComponent(run.id)}`}>
                                  <Button variant="ghost" size="sm" className="gap-1" title="Open Sequence Trace with other runs on the same dataset">
                                    <GitCompare className="h-3 w-3" />
                                    Sequence Trace
                                  </Button>
                                </Link>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {(hasPrev || hasMore) && (
                <div className="flex items-center justify-between gap-4 pt-4 mt-4 border-t">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={!hasPrev}
                    className="gap-1"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    Previous
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    Page {page + 1}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={!hasMore}
                    className="gap-1"
                  >
                    Next
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
