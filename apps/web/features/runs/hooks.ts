import { useQuery, useMutation } from "@tanstack/react-query";
import { RunsApi } from "./api";
import type { RunStatus, RunResult, CreateRunResponse } from "@phylo/contracts";
import { notify } from "@/lib/notify";
import { useEffect, useRef } from "react";

export function useCreateRun() {
  return useMutation<
    CreateRunResponse,
    any,
    { methodId: string; formData: FormData }
  >({
    mutationFn: ({ methodId, formData }) => RunsApi.create(methodId, formData),
    onSuccess: () => notify.success("Run created"),
    onError: (e: any) => notify.error("Failed to create run", e?.message),
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
    refetchInterval: (ctx) => {
      const s = ctx.state.data?.status;
      return s === "DONE" || s === "ERROR" ? false : 1200;
    },
  });

  // Toast only when status CHANGES (per run)
  useEffect(() => {
    const s = q.data?.status;
    if (!s || s === lastRef.current) return;

    const toastId = runId ? `run-${runId}-${s}` : undefined;

    if (s === "ERROR") {
      notify.error("Run failed", q.data?.message || "Unknown error", {
        id: toastId,
      });
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
