import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RunsApi, type RunListFilters } from "./api";
import type {
  RunStatus,
  RunResult,
  CreateRunResponse,
  RunSummary,
  DashboardRunsResponse,
  RunQuotaResponse,
} from "@phylo/contracts";
import { notify } from "@/lib/notify";
import { useEffect, useRef } from "react";
import { blockingResetAt, runLimitCode, runLimitTitle } from "./quota";

export const RUN_QUOTA_QUERY_KEY = ["runQuota"] as const;

type CreateRunVars = {
  methodId: string;
  params?: Record<string, unknown>;
  fileId?: string | null;
};

function truncateForToast(msg: string, max = 100): string {
  if (!msg || msg.length <= max) return msg;
  return msg.slice(0, max).trim() + "…";
}

export function useCreateRun() {
  const queryClient = useQueryClient();
  return useMutation<CreateRunResponse, any, CreateRunVars>({
    mutationFn: ({ methodId, params, fileId }) =>
      RunsApi.create(methodId, { params, file_id: fileId }),
    onSuccess: () => notify.success("Run created"),
    onError: (e: any) => {
      // A limit is not a malfunction: say which one, in the server's own words.
      const limit = runLimitCode(e);
      if (limit) notify.error(runLimitTitle(limit), e?.message);
      else notify.error("Failed to create run", truncateForToast(e?.message ?? "Unknown error"));
    },
    // Either way the allowance may have changed.
    onSettled: () => queryClient.invalidateQueries({ queryKey: RUN_QUOTA_QUERY_KEY }),
  });
}

export function useCancelRun() {
  const queryClient = useQueryClient();
  return useMutation<RunStatus, any, string>({
    mutationFn: (runId: string) => RunsApi.cancel(runId),
    // Cancelling a run that had not started gives its allowance back.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RUN_QUOTA_QUERY_KEY }),
    onError: (e: any) =>
      notify.error("Failed to cancel run", truncateForToast(e?.message ?? "Unknown error")),
  });
}

/** Longest the quota is left unchecked while nothing prompts a refresh. */
const QUOTA_REFRESH_MS = 60_000;

/**
 * The user's standing against the limits on creating runs. Refreshed after a
 * run is created or cancelled, when the window regains focus, once a minute,
 * and at the moment a reached limit is due to lift.
 */
export function useRunQuota(enabled = true) {
  return useQuery<RunQuotaResponse>({
    queryKey: RUN_QUOTA_QUERY_KEY,
    queryFn: () => RunsApi.quota(),
    enabled,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const data = query.state.data;
      const resetAt = blockingResetAt(data);
      if (!data || !resetAt) return QUOTA_REFRESH_MS;
      const wait = (data.retry_after_seconds ?? 0) * 1000 + 1000;
      return Math.min(QUOTA_REFRESH_MS, Math.max(1000, wait));
    },
  });
}

/** Live run-queue dashboard. Polls every ~2.5s while there is an active or queued run. */
export function useDashboardRuns(enabled = true) {
  return useQuery<DashboardRunsResponse>({
    queryKey: ["dashboardRuns"],
    queryFn: () => RunsApi.dashboard(),
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2500;
      const hasActive = !!data.active;
      const hasQueue = (data.queue?.length ?? 0) > 0;
      return hasActive || hasQueue ? 2500 : false;
    },
  });
}

/** Cancel a QUEUED run (promoted turn or personal-queue item); refreshes the dashboard. */
export function useCancelQueuedRun() {
  const queryClient = useQueryClient();
  return useMutation<RunStatus, any, string>({
    mutationFn: (runId: string) => RunsApi.cancelQueued(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboardRuns"] });
      queryClient.invalidateQueries({ queryKey: RUN_QUOTA_QUERY_KEY });
    },
    onError: (e: any) =>
      notify.error("Failed to cancel run", truncateForToast(e?.message ?? "Unknown error")),
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
      // Stage-based status: poll every 10s for active runs (no fake progress).
      return s === "DONE" || s === "ERROR" || s === "CANCELLED" ? false : 10000;
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

export function useRunsList(opts?: {
  skip?: number;
  limit?: number;
  filters?: RunListFilters;
}) {
  return useQuery<RunSummary[]>({
    queryKey: [
      "runsList",
      opts?.skip ?? 0,
      opts?.limit ?? 100,
      JSON.stringify(opts?.filters ?? {}),
    ],
    queryFn: () => RunsApi.list(opts),
  });
}
