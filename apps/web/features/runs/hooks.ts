import { useQuery, useMutation } from "@tanstack/react-query";
import { RunsApi } from "./api";
import type { RunStatus, RunResult, CreateRunResponse, RunSummary } from "@phylo/contracts";
import { notify } from "@/lib/notify";
import { useEffect, useRef } from "react";

type CreateRunVars = {
  methodId: string;
  formData: FormData;
  onProgress?: (p: number) => void;
};

function truncateForToast(msg: string, max = 100): string {
  if (!msg || msg.length <= max) return msg;
  return msg.slice(0, max).trim() + "…";
}

export function useCreateRun() {
  return useMutation<CreateRunResponse, any, CreateRunVars>({
    mutationFn: ({ methodId, formData, onProgress }) =>
      RunsApi.create(methodId, formData, { onProgress }),
    onSuccess: () => notify.success("Run created"),
    onError: (e: any) =>
      notify.error("Failed to create run", truncateForToast(e?.message ?? "Unknown error")),
  });
}

export function useRunStatus(runId?: string) {
  const lastRef = useRef<RunStatus["status"] | null>(null);

  // IMPORTANT: reset when a NEW run starts
  useEffect(() => {
    lastRef.current = null;
  }, [runId]);

  const q = useQuery<RunStatus>({
    queryKey: ["runStatus", runId],
    queryFn: () => RunsApi.status(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const { state } = query;
      if (state.status === "error" && state.error) {
        const status = (state.error as any)?.response?.status;
        if (status === 403 || status === 404) return false;
      }
      const s = state.data?.status;
      return s === "DONE" || s === "ERROR" || s === "CANCELLED" ? false : 1200;
    },
    retry: (failureCount, error: any) => {
      const status = error?.response?.status;
      if (status === 403 || status === 404) return false;
      return failureCount < 2;
    },
  });

  // Toast only when status CHANGES (per run)
  useEffect(() => {
    const s = q.data?.status;
    if (!s || s === lastRef.current) return;

    const toastId = runId ? `run-${runId}-${s}` : undefined;

    if (s === "ERROR") {
      const rawMsg = q.data?.message || "Unknown error";
      const shortMsg = rawMsg.length > 120 ? rawMsg.slice(0, 120).trim() + "…" : rawMsg;
      notify.error(
        "Run failed",
        rawMsg.length > 120 ? "See run card below for full error details." : shortMsg,
        { id: toastId }
      );
    } else if (s === "CANCELLED") {
      notify.error("Run cancelled", q.data?.message || "The run was cancelled.", { id: toastId });
    } else if (s === "DONE") {
      notify.success("Run finished", undefined, { id: toastId });
    }
    lastRef.current = s;
  }, [q.data, runId]);

  return q;
}

export function useRunResult(runId?: string, enabled = false) {
  return useQuery<RunResult>({
    queryKey: ["runResult", runId],
    queryFn: () => RunsApi.result(runId!),
    enabled,
  });
}

export function useRunsList(opts?: { skip?: number; limit?: number }) {
  return useQuery<RunSummary[]>({
    queryKey: ["runsList", opts?.skip ?? 0, opts?.limit ?? 100],
    queryFn: () => RunsApi.list(opts),
  });
}
