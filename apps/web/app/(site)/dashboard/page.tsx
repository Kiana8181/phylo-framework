"use client";

import ResultsSummary from "@/components/phylo/ResultsSummary";
import RunErrorState from "@/components/phylo/RunErrorState";
import RunProgress from "@/components/phylo/RunProgress";
import TreesCarousel from "@/components/phylo/TreesCarousel";
import RunWizard from "@/components/phylo/wizard/RunWizard";
import RunParamsPanel from "@/components/runs/RunParamsPanel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useContractSpec, useMethods } from "@/features/methods/hooks";
import { RunsApi } from "@/features/runs/api";
import { useRunResult, useRunStatus } from "@/features/runs/hooks";
import { cleanNewick } from "@/lib/newick";
import { formatRunDuration } from "@/lib/runDuration";
import { readDowserResult, readTreeTipColorStats, readTreeTipSizeBy, type MethodInfo, type RunWarning } from "@phylo/contracts";
import { useQuery } from "@tanstack/react-query";
import { GitCompare } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

type DashboardMode = "create" | "running" | "results" | "failed";

/** Prior-run config carried into the wizard via "use as defaults for next run". */
type WizardDefaults = {
  methodId: string;
  params: Record<string, unknown>;
  fileId?: string | null;
};

function _datasetLabel(datasetName?: string | null, datasetFiles?: string[] | null): string {
  if (datasetName && datasetName.trim()) return datasetName;
  if (datasetFiles && datasetFiles.length > 0) return datasetFiles.join(", ");
  return "Dataset unavailable";
}

function DashboardPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { data: methods } = useMethods();

  const [runId, setRunIdState] = useState<string | null>(null);
  const [dashboardMode, setDashboardMode] = useState<DashboardMode>("create");
  const [wizardDefaults, setWizardDefaults] = useState<WizardDefaults | null>(null);
  const previousStatusRef = useRef<string | null>(null);

  const RUN_STORAGE_KEY = "phylo_current_run_id";

  const setRunId = (id: string | null) => {
    setRunIdState(id);
    if (typeof window !== "undefined") {
      if (id) window.localStorage.setItem(RUN_STORAGE_KEY, id);
      else window.localStorage.removeItem(RUN_STORAGE_KEY);

      const url = new URL(window.location.href);
      if (id) {
        url.searchParams.set("runId", id);
      } else {
        url.searchParams.delete("runId");
      }
      router.replace(url.pathname + url.search, { scroll: false });
    }
  };

  const resetToCreateMode = () => {
    previousStatusRef.current = null;
    setWizardDefaults(null);
    setRunId(null);
    setDashboardMode("create");
  };

  // When opening from history (e.g. /dashboard?runId=xxx), load that run.
  const runIdFromUrl = searchParams.get("runId");
  useEffect(() => {
    if (!runIdFromUrl) return;
    setRunIdState(runIdFromUrl);
    setDashboardMode("running");
  }, [runIdFromUrl]);

  useEffect(() => {
    let cancelled = false;
    const restoreFromStorage = () => {
      if (cancelled || typeof window === "undefined") return;
      const stored = window.localStorage.getItem(RUN_STORAGE_KEY);
      if (stored) {
        setRunIdState(stored);
        setDashboardMode("running");
      }
    };

    if (!runIdFromUrl) {
      RunsApi.getCurrentRun()
        .then((data) => {
          if (cancelled) return;
          if (data?.run_id) {
            setRunIdState(data.run_id);
            setDashboardMode("running");
          } else {
            restoreFromStorage();
          }
        })
        .catch(() => {
          restoreFromStorage();
        });
    }

    return () => {
      cancelled = true;
    };
  }, [runIdFromUrl]);

  useEffect(() => {
    if (runId && typeof window !== "undefined") {
      window.localStorage.setItem(RUN_STORAGE_KEY, runId);
    }
  }, [runId]);

  const { data: status, isError: statusError, error: statusErr } = useRunStatus(runId ?? undefined);

  useEffect(() => {
    previousStatusRef.current = null;
  }, [runId]);

  // Transition mode on run lifecycle changes so the form is replaced automatically.
  useEffect(() => {
    if (!runId) {
      setDashboardMode("create");
      return;
    }

    const currentStatus = status?.status;
    if (!currentStatus) {
      setDashboardMode((prev) => (prev === "create" ? "running" : prev));
      return;
    }

    const prevStatus = previousStatusRef.current;
    const wasActive = prevStatus === "PENDING" || prevStatus === "QUEUED" || prevStatus === "RUNNING";
    const nowDone = currentStatus === "DONE";
    const nowFailed = currentStatus === "ERROR" || currentStatus === "CANCELLED";

    if ((wasActive && nowDone) || nowDone) {
      setDashboardMode("results");
    } else if ((wasActive && nowFailed) || nowFailed) {
      setDashboardMode("failed");
    } else {
      setDashboardMode("running");
    }

    previousStatusRef.current = currentStatus;
  }, [runId, status?.status]);

  const resultEnabled = !!runId && (dashboardMode === "results" || dashboardMode === "failed");
  const { data: result } = useRunResult(runId ?? undefined, resultEnabled);

  const { data: sameDatasetRuns } = useQuery({
    queryKey: ["runSameDataset", runId],
    queryFn: () => RunsApi.sameDataset(runId!),
    enabled: !!runId && dashboardMode === "results",
  });

  const runMethodKey = status?.method_id ?? result?.method_id ?? null;
  const { contractSpec: runContractSpec } = useContractSpec(runMethodKey ?? undefined);

  const methodsById = useMemo(() => {
    const map = new Map<string, MethodInfo>();
    (methods ?? []).forEach((method) => map.set(method.id, method));
    return map;
  }, [methods]);

  const modelLabel = runMethodKey
    ? (methodsById.get(runMethodKey)?.name ?? runContractSpec?.methodLabel ?? runMethodKey)
    : "—";

  const runDatasetName = result?.dataset_name ?? status?.dataset_name ?? null;
  const runDatasetFiles = result?.dataset_files ?? status?.dataset_files ?? [];
  const runDatasetLabel = _datasetLabel(runDatasetName, runDatasetFiles);
  const runParams = (result?.params ?? status?.params ?? {}) as Record<string, unknown>;

  const handleUseAsDefaults = () => {
    if (!runMethodKey) return;
    previousStatusRef.current = null;
    setWizardDefaults({
      methodId: runMethodKey,
      params: runParams,
      fileId: status?.input_file_id ?? result?.input_file_id ?? null,
    });
    setRunId(null);
    setDashboardMode("create");
  };

  const runStartedAt = status?.started_at ?? result?.started_at ?? null;
  const runFinishedAt = status?.finished_at ?? result?.finished_at ?? null;
  const runDurationLabel = formatRunDuration(runStartedAt, runFinishedAt);

  const cloneRows = useMemo(
    () =>
      result?.clones?.clone_id?.map((id: string, i: number) => ({
        id,
        seqs: result?.clones?.seqs?.[i] ?? 0,
      })) ?? [],
    [result],
  );

  const { colorBy: svgColorBy, unknownValue: svgUnknown } = readTreeTipColorStats(result?.stats);
  const svgTipSizeBy = readTreeTipSizeBy(result?.stats);
  const dowserResult = useMemo(() => readDowserResult(result), [result]);
  const showInternalNodesDefault = useMemo(() => {
    const mode = (result?.stats as Record<string, unknown> | undefined)?.analysis_mode;
    return mode === "tree_with_internal_sequences";
  }, [result?.stats]);

  const warnings = useMemo<RunWarning[]>(() => {
    const runWarnings = result?.warnings;
    return Array.isArray(runWarnings) ? runWarnings : [];
  }, [result?.warnings]);

  return (
    <main className="mx-auto max-w-6xl w-full p-4 sm:p-6 space-y-6 sm:space-y-8">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl truncate">Phylo Runner</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Select a method, set parameters, upload your data, and generate trees.
          </p>
        </div>
      </header>

      {dashboardMode === "create" && (
        <RunWizard
          methods={methods ?? []}
          initialMethodId={wizardDefaults?.methodId}
          initialParams={wizardDefaults?.params}
          initialFileId={wizardDefaults?.fileId}
          onStartOver={resetToCreateMode}
          onSubmitDone={(id) => {
            setRunId(id);
            setDashboardMode("running");
          }}
        />
      )}

      {runId && dashboardMode === "running" && (
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
          onDismiss={statusError ? () => resetToCreateMode() : undefined}
        />
      )}

      {dashboardMode === "failed" && runId && (
        <RunErrorState
          runId={runId}
          status={status?.status}
          methodLabel={modelLabel}
          datasetLabel={runDatasetLabel}
          errorCode={status?.error?.code}
          errorMessage={status?.error?.message ?? status?.message ?? result?.error}
          logs={result?.logs}
          onDismiss={resetToCreateMode}
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

      {result && runId && dashboardMode === "results" && (
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
                <Button variant="default" size="sm" onClick={resetToCreateMode}>
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
              The input dataset{" "}
              <span className="font-medium">{result.dataset.original_filename}</span> has been
              deleted. This run&apos;s results are preserved, but to run it again you must
              re-upload the file.
            </div>
          )}

          <ResultsSummary
            runId={runId}
            stats={result?.stats}
            cloneRows={cloneRows}
            repertoireTable={result?.tables?.repertoire_two_levels_info}
            analysis={result?.analysis}
            diagnostics={result?.diagnostics}
            dowserDta={dowserResult.dta}
            dowserTimeEvolution={dowserResult.timeEvolution}
            dowserInputQc={dowserResult.inputQc}
            dowserChainQc={dowserResult.chainQc}
          />

          {warnings.length > 0 && (
            <div className="rounded border p-3 bg-yellow-50 text-yellow-900 dark:bg-yellow-950/30 dark:text-yellow-200 text-sm space-y-1">
              {warnings.map((warning, idx) => {
                if (typeof warning === "string") {
                  return <div key={`warn-${idx}`}>• {warning}</div>;
                }
                const code = String(warning.code ?? "").trim();
                const msg = String(warning.message ?? "").trim();
                const treeId = String(warning.treeId ?? "").trim();
                const prefix = code ? `[${code}] ` : "";
                const suffix = treeId ? ` (tree: ${treeId})` : "";
                return (
                  <div key={`warn-${idx}`}>
                    • {prefix}
                    {msg || "Warning"}
                    {suffix}
                  </div>
                );
              })}
            </div>
          )}

          <TreesCarousel
            runId={runId}
            trees={result.trees ?? []}
            cleanNewick={cleanNewick}
            colorBy={svgColorBy}
            unknownValue={svgUnknown}
            tipSizeBy={svgTipSizeBy}
            showInternalNodesDefault={showInternalNodesDefault}
          />

          {Array.isArray(result.logs) && result.logs.length > 0 && (
            <details className="rounded border p-3 bg-card/50">
              <summary className="cursor-pointer text-sm font-medium">Show model logs</summary>
              <div className="mt-2 max-h-64 overflow-y-auto space-y-3 text-xs font-mono">
                {result.logs.map((log, index) => (
                  <div key={`log-${index}`} className="border-b last:border-0 pb-2 last:pb-0">
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
        </section>
      )}
    </main>
  );
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
