"use client";

import ResultsView from "@/components/phylo/results/ResultsView";
import RunErrorState from "@/components/phylo/RunErrorState";
import RunProgress from "@/components/phylo/RunProgress";
import RunWizard from "@/components/phylo/wizard/RunWizard";
import RunParamsPanel from "@/components/runs/RunParamsPanel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Loading } from "@/components/ui/loading";
import { SpinnerIllustration } from "@/components/ui/spinner-illustration";
import {
  SAMPLE_FILENAME,
  SAMPLE_HREF,
  SAMPLE_MIME,
  TRY_SAMPLE_KEY,
  type TrySampleIntent,
} from "@/features/docs/sample";
import { FilesApi } from "@/features/files/api";
import { FILES_LIST_QUERY_KEY } from "@/features/files/hooks";
import { useContractSpec, useMethods } from "@/features/methods/hooks";
import { RunsApi } from "@/features/runs/api";
import { useCancelQueuedRun, useDashboardRuns, useRunResult, useRunStatus } from "@/features/runs/hooks";
import { useUploadSession } from "@/features/uploads/hooks";
import { notify } from "@/lib/notify";
import { formatRunDuration } from "@/lib/runDuration";
import { type MethodInfo, type RunSummary } from "@phylo/contracts";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GitCompare, Plus, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

/** One-shot handoff of wizard defaults from the read-only results surface back to
 * the live dashboard's "Add run" wizard ("use as defaults for next run"). */
const WIZARD_DEFAULTS_KEY = "phylo_wizard_defaults";

type WizardDefaults = {
  methodId: string;
  params: Record<string, unknown>;
  fileId?: string | null;
  /** Banner copy explaining where the pre-filled values came from. */
  note?: string;
};

const RERUN_NOTE = "Settings carried over from a previous run — tweak anything, or start from scratch.";
const TRY_SAMPLE_NOTE =
  "Loaded from the Try it yourself example — tweak anything, or start from scratch.";

function _datasetLabel(datasetName?: string | null, datasetFiles?: string[] | null): string {
  if (datasetName && datasetName.trim()) return datasetName;
  if (datasetFiles && datasetFiles.length > 0) return datasetFiles.join(", ");
  return "Dataset unavailable";
}

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function useMethodsById() {
  const { data: methods } = useMethods();
  return useMemo(() => {
    const map = new Map<string, MethodInfo>();
    (methods ?? []).forEach((method) => map.set(method.id, method));
    return map;
  }, [methods]);
}

// --------------------------------------------------------------------------- //
// Read-only results surface — entered ONLY via ?runId= (History "View" or the
// completion toast's action). Never auto-restored.
// --------------------------------------------------------------------------- //
function RunResultsSurface({ runId, onBack }: { runId: string; onBack: () => void }) {
  const methodsById = useMethodsById();

  const { data: status, isError: statusError, error: statusErr } = useRunStatus(runId);
  const currentStatus = status?.status;
  const isDone = currentStatus === "DONE";
  const isFailed = currentStatus === "ERROR" || currentStatus === "CANCELLED";
  const isActive = currentStatus === "RUNNING" || currentStatus === "QUEUED" || currentStatus === "PENDING";

  const resultEnabled = isDone || isFailed;
  const { data: result } = useRunResult(runId, resultEnabled);

  const { data: sameDatasetRuns } = useQuery({
    queryKey: ["runSameDataset", runId],
    queryFn: () => RunsApi.sameDataset(runId),
    enabled: isDone,
  });

  const runMethodKey = status?.method_id ?? result?.method_id ?? null;
  const { contractSpec: runContractSpec } = useContractSpec(runMethodKey ?? undefined);

  const modelLabel = runMethodKey
    ? (methodsById.get(runMethodKey)?.name ?? runContractSpec?.methodLabel ?? runMethodKey)
    : "—";

  const runDatasetName = result?.dataset_name ?? status?.dataset_name ?? null;
  const runDatasetFiles = result?.dataset_files ?? status?.dataset_files ?? [];
  const runDatasetLabel = _datasetLabel(runDatasetName, runDatasetFiles);
  const runParams = (result?.params ?? status?.params ?? {}) as Record<string, unknown>;

  const runStartedAt = status?.started_at ?? result?.started_at ?? null;
  const runFinishedAt = status?.finished_at ?? result?.finished_at ?? null;
  const runDurationLabel = formatRunDuration(runStartedAt, runFinishedAt);
  const resultErrorMessage = typeof result?.error === "string" ? result.error : result?.error?.error;
  const resultErrorLogs =
    result?.logs && result.logs.length > 0
      ? result.logs
      : result?.error !== null && typeof result?.error === "object"
        ? result.error.logs
        : undefined;
  // "Use as defaults for next run" hands the config back to the live dashboard's
  // Add-run wizard via a one-shot sessionStorage handoff, then navigates home.
  const handleUseAsDefaults = () => {
    if (!runMethodKey) return;
    try {
      const payload: WizardDefaults = {
        methodId: runMethodKey,
        params: runParams,
        fileId: status?.input_file_id ?? result?.input_file_id ?? null,
      };
      sessionStorage.setItem(WIZARD_DEFAULTS_KEY, JSON.stringify(payload));
    } catch {
      /* ignore storage errors — the wizard just opens without defaults */
    }
    onBack();
  };

  return (
    <main className="mx-auto max-w-6xl w-full p-4 sm:p-6 space-y-6 sm:space-y-8">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl truncate">Run results</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Viewing run <span className="font-mono">{shortId(runId)}</span>.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onBack}>
          Back to dashboard
        </Button>
      </header>

      {isActive && (
        <RunProgress
          runId={runId}
          status={status?.status}
          progress={status?.progress ?? 0}
          message={status?.message}
          stage={status?.stage}
          stageMessage={status?.stage_message}
          cancelRequested={status?.cancel_requested}
          methodId={runMethodKey}
          startedAt={status?.started_at}
          finishedAt={status?.finished_at}
          statusError={statusError ? statusErr : undefined}
        />
      )}

      {isFailed && (
        <RunErrorState
          runId={runId}
          status={status?.status}
          methodLabel={modelLabel}
          datasetLabel={runDatasetLabel}
          errorCode={status?.error?.code}
          errorMessage={status?.error?.message ?? status?.message ?? resultErrorMessage}
          logs={resultErrorLogs}
          paramsSlot={
            runMethodKey ? (
              <RunParamsPanel
                methodKey={runMethodKey}
                runId={runId}
                runParams={runParams}
                contractSpec={runContractSpec}
                datasetName={runDatasetName}
                datasetFiles={runDatasetFiles}
                onUseAsDefaults={handleUseAsDefaults}
              />
            ) : undefined
          }
        />
      )}

      {result && isDone && (
        <section className="space-y-6">
          <Card className="p-4 space-y-4">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <h2 className="text-xl font-semibold">Run Summary</h2>
                <p className="text-sm text-muted-foreground">
                  Run details and resolved parameters for this result.
                </p>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {runDurationLabel && (
                  <span className="inline-flex items-center rounded-full border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                    Time spent: {runDurationLabel}
                  </span>
                )}
                <Link href={`/dashboard/comparison?baseRunId=${encodeURIComponent(runId)}`}>
                  <Button variant="outline" size="sm" className="gap-1.5">
                    <GitCompare className="h-4 w-4" />
                    Sequence Trace
                  </Button>
                </Link>
                <Button variant="default" size="sm" onClick={onBack}>
                  Start another run
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div>
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Run ID</p>
                <p className="text-xs font-mono break-all">{runId}</p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Method</p>
                <p className="text-sm">{modelLabel}</p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Dataset</p>
                <p className="text-sm break-words">{runDatasetLabel}</p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Same datasets</p>
                <p className="text-sm">
                  {sameDatasetRuns?.length ?? 0} run{(sameDatasetRuns?.length ?? 0) === 1 ? "" : "s"}
                </p>
              </div>
            </div>

            {runMethodKey && (
              <RunParamsPanel
                methodKey={runMethodKey}
                runId={runId}
                runParams={runParams}
                contractSpec={runContractSpec}
                datasetName={runDatasetName}
                datasetFiles={runDatasetFiles}
                onUseAsDefaults={handleUseAsDefaults}
              />
            )}
          </Card>

          {result?.dataset?.is_deleted && (
            <div className="rounded border p-3 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200 text-sm">
              The input dataset <span className="font-medium">{result.dataset.original_filename}</span> has
              been deleted. This run&apos;s results are preserved, but to run it again you must re-upload the
              file.
            </div>
          )}

          <ResultsView runId={runId} methodId={runMethodKey} result={result} />
        </section>
      )}
    </main>
  );
}

// --------------------------------------------------------------------------- //
// Queue list item
// --------------------------------------------------------------------------- //
function QueueRow({
  run,
  methodLabel,
  onCancel,
  cancelling,
}: {
  run: RunSummary;
  methodLabel: string;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const datasetLabel = _datasetLabel(run.dataset_name, run.dataset_files);
  const created = run.created_at ? new Date(run.created_at).toLocaleString() : "—";
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border p-3">
      <div className="min-w-0">
        <p className="text-sm font-medium truncate">{methodLabel}</p>
        <p className="text-xs text-muted-foreground truncate">
          {datasetLabel} · queued {created}
        </p>
      </div>
      <Button
        variant="ghost"
        size="sm"
        className="shrink-0 gap-1 text-muted-foreground hover:text-foreground"
        onClick={onCancel}
        disabled={cancelling}
      >
        <X className="h-4 w-4" />
        Remove
      </Button>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Live dashboard surface — form-or-list. Never renders inline results.
// --------------------------------------------------------------------------- //
function LiveDashboard({ onViewResults }: { onViewResults: (runId: string) => void }) {
  const { data: methods } = useMethods();
  const methodsById = useMethodsById();
  const queryClient = useQueryClient();
  const { data } = useDashboardRuns();
  const cancelQueued = useCancelQueuedRun();

  const [showAddRun, setShowAddRun] = useState(false);
  const [wizardDefaults, setWizardDefaults] = useState<WizardDefaults | null>(null);
  const [preparingSample, setPreparingSample] = useState(false);
  const uploadSession = useUploadSession();

  // Pick up wizard defaults handed off from the results surface (one-shot).
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(WIZARD_DEFAULTS_KEY);
      if (raw) {
        sessionStorage.removeItem(WIZARD_DEFAULTS_KEY);
        const handoff = JSON.parse(raw) as WizardDefaults;
        setWizardDefaults({ ...handoff, note: RERUN_NOTE });
        setShowAddRun(true);
      }
    } catch {
      /* ignore */
    }
  }, []);

  // Resolve a "Try it yourself" click from the docs (one-shot). The docs button
  // only records which method and parameters to use; here we make sure the
  // example dataset is uploaded (reusing it if the reader already has it) and
  // open the wizard on it.
  const trySampleRef = useRef(false);
  const uploadSample = uploadSession.upload;
  useEffect(() => {
    if (trySampleRef.current) return;

    let intent: TrySampleIntent | null = null;
    try {
      const raw = sessionStorage.getItem(TRY_SAMPLE_KEY);
      if (raw) {
        sessionStorage.removeItem(TRY_SAMPLE_KEY);
        intent = JSON.parse(raw) as TrySampleIntent;
      }
    } catch {
      /* ignore */
    }
    if (!intent) return;

    trySampleRef.current = true;
    const { methodId, params } = intent;
    setPreparingSample(true);

    void (async () => {
      try {
        const list = await FilesApi.list({ limit: 100 });
        let fileId = list.files.find((f) => f.original_filename === SAMPLE_FILENAME)?.id ?? null;

        if (!fileId) {
          const res = await fetch(SAMPLE_HREF);
          if (!res.ok) throw new Error(`Example dataset unavailable (HTTP ${res.status}).`);
          const file = new File([await res.blob()], SAMPLE_FILENAME, { type: SAMPLE_MIME });
          fileId = (await uploadSample(file)).file_id;
          queryClient.invalidateQueries({ queryKey: FILES_LIST_QUERY_KEY });
        }

        setWizardDefaults({ methodId, params, fileId, note: TRY_SAMPLE_NOTE });
      } catch (e: unknown) {
        notify.error(
          "Could not load the example",
          (e as Error)?.message ?? "The example dataset could not be prepared.",
        );
      } finally {
        setPreparingSample(false);
        setShowAddRun(true);
      }
    })();
  }, [uploadSample, queryClient]);

  // Completion detection: a finished run drops out of /runs/dashboard (non-terminal
  // only). Diff tracked ids against the previous poll, fetch each dropped run's final
  // status once, and toast. Dedupe with a Set so overlapping polls never double-fire.
  const trackedIdsRef = useRef<Set<string>>(new Set());
  const toastedIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!data) return;
    const currentIds = new Set<string>();
    if (data.active?.run_id) currentIds.add(data.active.run_id);
    for (const q of data.queue) currentIds.add(q.id);

    const dropped: string[] = [];
    trackedIdsRef.current.forEach((id) => {
      if (!currentIds.has(id)) dropped.push(id);
    });
    trackedIdsRef.current = currentIds;

    for (const id of dropped) {
      if (toastedIdsRef.current.has(id)) continue;
      toastedIdsRef.current.add(id);
      void RunsApi.status(id)
        .then((st) => {
          if (st.status === "DONE") {
            notify.success(`Run ${shortId(id)} finished`, "Your results are ready to view.", {
              action: { label: "View results", onClick: () => onViewResults(id) },
            });
          } else if (st.status === "ERROR") {
            notify.error(`Run ${shortId(id)} failed`, "Open it to see the error details.", {
              action: { label: "View details", onClick: () => onViewResults(id) },
            });
          }
          // CANCELLED: no toast — the user cancelled it intentionally.
        })
        .catch(() => {
          // Allow a later poll to retry the terminal-status fetch.
          toastedIdsRef.current.delete(id);
        });
    }
  }, [data, onViewResults]);

  const active = data?.active ?? null;
  const queue = data?.queue ?? [];
  const canAdd = data?.limits?.can_add ?? true;
  const queuedCount = data?.limits?.queued_count ?? queue.length;
  const maxQueued = data?.limits?.max_queued ?? 5;
  const hasAnything = !!active || queue.length > 0;

  // RunWizard captures its initial* props once, on mount. When "use as defaults"
  // defaults arrive asynchronously (sessionStorage handoff, read in the effect
  // above), a keyed remount forces the wizard to re-capture them.
  const wizardKey = wizardDefaults
    ? `wiz-${wizardDefaults.methodId}-${wizardDefaults.fileId ?? "none"}`
    : "wiz-blank";

  const closeWizard = () => {
    setShowAddRun(false);
    setWizardDefaults(null);
    queryClient.invalidateQueries({ queryKey: ["dashboardRuns"] });
  };

  const header = (
    <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl truncate">Phylo Runner</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Select a method, set parameters, upload your data, and generate trees.
        </p>
      </div>
    </header>
  );

  const preparingSampleCard = (
    <Card className="p-6">
      <Loading label="Preparing the example dataset…" />
    </Card>
  );

  // Empty state: no active run and empty queue → the wizard is the primary form.
  if (!hasAnything) {
    return (
      <main className="mx-auto max-w-6xl w-full p-4 sm:p-6 space-y-6 sm:space-y-8">
        {header}
        {preparingSample ? (
          preparingSampleCard
        ) : (
          <RunWizard
            key={wizardKey}
            methods={methods ?? []}
            initialMethodId={wizardDefaults?.methodId}
            initialParams={wizardDefaults?.params}
            initialFileId={wizardDefaults?.fileId}
            prefillNote={wizardDefaults?.note}
            onSubmitDone={() => closeWizard()}
          />
        )}
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl w-full p-4 sm:p-6 space-y-6 sm:space-y-8">
      {header}

      {/* Active turn */}
      {active && active.status === "RUNNING" && active.run_id && (
        <RunProgress
          runId={active.run_id}
          status={active.status}
          progress={active.progress ?? 0}
          message={active.message}
          stage={active.stage}
          stageMessage={active.stage_message}
          cancelRequested={active.cancel_requested}
          methodId={active.method_id}
          startedAt={active.started_at}
          finishedAt={active.finished_at}
        />
      )}

      {active && active.status !== "RUNNING" && active.run_id && (
        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0 text-sm">
              Run ID: <span className="truncate font-mono">{active.run_id}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="shrink-0 rounded border bg-amber-100 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800">
                Waiting
              </span>
              <Button
                variant="destructive"
                size="sm"
                className="shrink-0"
                onClick={() => cancelQueued.mutate(active.run_id!)}
                disabled={cancelQueued.isPending}
              >
                Cancel
              </Button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <SpinnerIllustration className="size-9 shrink-0 text-primary" />
            <div className="min-w-0 text-sm">
              <p className="font-medium">Waiting for a free worker slot</p>
              <p className="text-xs text-muted-foreground">
                Your run is next in line and will start automatically as soon as a worker is available.
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Personal queue */}
      {queue.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-muted-foreground">
            Queued behind your active run ({queuedCount}/{maxQueued})
          </h2>
          <div className="space-y-2">
            {queue.map((run) => (
              <QueueRow
                key={run.id}
                run={run}
                methodLabel={methodsById.get(run.method_id)?.name ?? run.method_id}
                onCancel={() => cancelQueued.mutate(run.id)}
                cancelling={cancelQueued.isPending}
              />
            ))}
          </div>
        </section>
      )}

      {/* Add run */}
      <section className="space-y-3">
        {preparingSample ? (
          preparingSampleCard
        ) : !showAddRun ? (
          <Button
            variant="outline"
            className="gap-1.5"
            onClick={() => setShowAddRun(true)}
            disabled={!canAdd}
            title={canAdd ? undefined : `You can queue at most ${maxQueued} runs.`}
          >
            <Plus className="h-4 w-4" />
            Add run
          </Button>
        ) : (
          <Card className="p-4 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Add a run to your queue</h2>
              <Button variant="ghost" size="sm" onClick={() => setShowAddRun(false)}>
                Cancel
              </Button>
            </div>
            <RunWizard
              key={wizardKey}
              methods={methods ?? []}
              initialMethodId={wizardDefaults?.methodId}
              initialParams={wizardDefaults?.params}
              initialFileId={wizardDefaults?.fileId}
              prefillNote={wizardDefaults?.note}
              onSubmitDone={() => closeWizard()}
            />
          </Card>
        )}
      </section>
    </main>
  );
}

function DashboardPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const runIdFromUrl = searchParams.get("runId");

  const goToResults = (id: string) => {
    router.push(`/dashboard?runId=${encodeURIComponent(id)}`);
  };
  const backToDashboard = () => {
    router.push("/dashboard");
  };

  if (runIdFromUrl) {
    return <RunResultsSurface runId={runIdFromUrl} onBack={backToDashboard} />;
  }
  return <LiveDashboard onViewResults={goToResults} />;
}

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-6xl w-full p-4 sm:p-6">
          <p className="text-muted-foreground">Loading dashboard...</p>
        </main>
      }
    >
      <DashboardPageContent />
    </Suspense>
  );
}
