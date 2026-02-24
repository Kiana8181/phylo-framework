"use client";

import MethodsGrid from "@/components/phylo/MethodsGrid";
import ResultsSummary from "@/components/phylo/ResultsSummary";
import RunParameters from "@/components/phylo/RunParameters";
import RunProgress from "@/components/phylo/RunProgress";
import TreesCarousel from "@/components/phylo/TreesCarousel";
import RunParamsDropdown from "@/components/runs/RunParamsDropdown";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useContractSpec, useMethods, useMethodSpec } from "@/features/methods/hooks";
import { RunsApi } from "@/features/runs/api";
import { useRunResult, useRunStatus } from "@/features/runs/hooks";
import { cleanNewick } from "@/lib/newick";
import type { MethodInfo, RunTree, RunWarning } from "@phylo/contracts";
import { useQuery } from "@tanstack/react-query";
import { GitCompare } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

type DashboardMode = "create" | "running" | "results" | "failed";

function _figureToDataUrl(raw: unknown): string | null {
  const txt = String(raw ?? "").trim();
  if (!txt) return null;
  if (/^data:/i.test(txt)) return txt;
  return `data:image/png;base64,${txt}`;
}

function _labelFromFigureKey(key: string): string {
  const x = key.replace(/[_\-]+/g, " ").trim();
  if (!x) return "Other Outputs";
  return x.replace(/\b\w/g, (c) => c.toUpperCase());
}

function _datasetLabel(datasetName?: string | null, datasetFiles?: string[] | null): string {
  if (datasetName && datasetName.trim()) return datasetName;
  if (datasetFiles && datasetFiles.length > 0) return datasetFiles.join(", ");
  return "Dataset unavailable";
}

function DashboardPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { data: methods } = useMethods();

  const [selected, setSelected] = useState<MethodInfo | null>(null);
  const { data: createSpec } = useMethodSpec(selected?.id);

  const [files, setFiles] = useState<File[]>([]);
  const [runId, setRunIdState] = useState<string | null>(null);
  const [dashboardMode, setDashboardMode] = useState<DashboardMode>("create");
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
    setRunId(null);
    setFiles([]);
    setSelected(null);
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
    const wasActive =
      prevStatus === "PENDING" || prevStatus === "QUEUED" || prevStatus === "RUNNING";
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

  const runMethodKey = status?.method_id ?? result?.method_id ?? selected?.id ?? null;
  const { contractSpec: runContractSpec } = useContractSpec(runMethodKey ?? undefined);

  const methodsById = useMemo(() => {
    const map = new Map<string, MethodInfo>();
    (methods ?? []).forEach((method) => map.set(method.id, method));
    return map;
  }, [methods]);

  const selectedMethodId = dashboardMode === "create" ? selected?.id ?? null : runMethodKey;
  const modelLabel = runMethodKey
    ? methodsById.get(runMethodKey)?.name ?? runContractSpec?.methodLabel ?? runMethodKey
    : "—";

  const runDatasetName = result?.dataset_name ?? status?.dataset_name ?? null;
  const runDatasetFiles = result?.dataset_files ?? status?.dataset_files ?? [];
  const runDatasetLabel = _datasetLabel(runDatasetName, runDatasetFiles);
  const runParams = (result?.params ?? status?.params ?? {}) as Record<string, unknown>;

  const cloneRows = useMemo(
    () =>
      result?.clones?.clone_id?.map((id: string, i: number) => ({
        id,
        seqs: result?.clones?.seqs?.[i],
      })) ?? [],
    [result]
  );

  const svgColorBy: string | undefined = result?.stats?.tip_states_capped
    ? undefined
    : result?.stats?.tip_color_by;
  const svgUnknown = result?.stats?.unknown_value ?? "unknown";

  const methodFigureSections = useMemo(() => {
    const figs = result?.figures;
    if (!figs || typeof figs !== "object") return [] as Array<{ key: string; items: string[] }>;

    const out: Array<{ key: string; items: string[] }> = [];
    for (const [key, value] of Object.entries(figs)) {
      if (key === "phylogeny") continue;
      if (!Array.isArray(value)) continue;
      const items = value.map(_figureToDataUrl).filter((src): src is string => Boolean(src));
      if (!items.length) continue;
      out.push({ key, items });
    }
    return out;
  }, [result]);

  const warnings = useMemo<RunWarning[]>(() => {
    return Array.isArray(result?.warnings) ? result.warnings : [];
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

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Methods</h2>
        <MethodsGrid
          methods={methods ?? []}
          selectedId={selectedMethodId}
          onSelect={(m) => {
            setSelected(m);
            setRunId(null);
            setFiles([]);
            setDashboardMode("create");
          }}
          disabled={dashboardMode !== "create"}
        />
      </section>

      {dashboardMode === "create" && createSpec && (
        <RunParameters
          spec={createSpec}
          files={files}
          onFiles={setFiles}
          onSubmitDone={(id) => {
            setRunId(id);
            setDashboardMode("running");
          }}
          runInProgress={false}
        />
      )}

      {runId && (dashboardMode === "running" || dashboardMode === "failed") && (
        <RunProgress
          runId={runId}
          status={status?.status}
          progress={status?.progress ?? 0}
          message={status?.message}
          statusError={statusError ? statusErr : undefined}
          onDismiss={
            status?.status === "ERROR" || status?.status === "CANCELLED" || statusError
              ? () => resetToCreateMode()
              : undefined
          }
        />
      )}

      {dashboardMode === "failed" && runId && (
        <Card className="p-4 space-y-4">
          <div className="space-y-1">
            <h2 className="text-xl font-semibold">Run failed</h2>
            <p className="text-sm text-muted-foreground">
              This run ended with a failure. Start another run to return to the editable form.
            </p>
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
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Status</p>
              <p className="text-sm">{status?.status ?? "ERROR"}</p>
            </div>
          </div>
          <div className="flex items-center justify-between gap-2 flex-wrap">
            {runMethodKey && (
              <RunParamsDropdown
                methodKey={runMethodKey}
                runId={runId}
                runParams={runParams}
                contractSpec={runContractSpec}
                datasetName={runDatasetName}
                datasetFiles={runDatasetFiles}
              />
            )}
            <Button onClick={resetToCreateMode}>Start another run</Button>
          </div>
          {Array.isArray(result?.logs) && result.logs.length > 0 && (
            <details className="rounded border p-3 bg-card/50">
              <summary className="cursor-pointer text-sm font-medium">Show model logs</summary>
              <div className="mt-2 max-h-64 overflow-y-auto space-y-3 text-xs font-mono">
                {result.logs.map((log, index) => (
                  <div key={`failed-log-${index}`} className="border-b last:border-0 pb-2 last:pb-0">
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
              <RunParamsDropdown
                methodKey={runMethodKey}
                runId={runId}
                runParams={runParams}
                contractSpec={runContractSpec}
                datasetName={runDatasetName}
                datasetFiles={runDatasetFiles}
                sameDatasetRuns={(sameDatasetRuns ?? []).map((candidate) => ({
                  id: candidate.id,
                  methodId: candidate.method_id,
                  datasetName: candidate.dataset_name,
                }))}
              />
            )}
          </Card>

          <ResultsSummary
            stats={result?.stats}
            cloneRows={cloneRows}
            artifact_zip_b64={result?.artifact_zip_b64}
            artifact_name={result?.artifact_name || ""}
            repertoireTable={result?.tables?.repertoire_two_levels_info}
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
            figures={result.figures}
            annotations={result.annotations}
            cleanNewick={cleanNewick}
            colorBy={svgColorBy}
            unknownValue={svgUnknown}
          />

          {methodFigureSections.length > 0 && (
            <section className="space-y-3">
              <h3 className="text-lg font-medium">Method Charts</h3>
              {methodFigureSections.map((section) => (
                <details key={section.key} className="rounded border p-3 bg-card/50">
                  <summary className="cursor-pointer text-sm font-medium">{_labelFromFigureKey(section.key)}</summary>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    {section.items.map((src, index) =>
                      src.startsWith("data:application/pdf") ? (
                        <object
                          key={`${section.key}-${index}`}
                          data={src}
                          type="application/pdf"
                          className="w-full h-80 rounded border bg-white"
                        />
                      ) : (
                        <Image
                          key={`${section.key}-${index}`}
                          src={src}
                          alt={`${section.key}-${index + 1}`}
                          width={1200}
                          height={800}
                          unoptimized
                          className="w-full rounded border bg-white"
                        />
                      )
                    )}
                  </div>
                </details>
              ))}
            </section>
          )}

          <details className="rounded border p-3 bg-card/50 overflow-x-scroll">
            <summary className="cursor-pointer text-sm font-medium">Show Newick text</summary>
            <div className="mt-2 space-y-2">
              {(result.trees ?? []).map((tree, index) => {
                const treeObj: RunTree | null = typeof tree === "string" ? null : tree;
                const newickText = typeof tree === "string" ? tree : treeObj?.original_newick || treeObj?.newick || "";
                return (
                  <pre key={`newick-${index}`} className="whitespace-pre-wrap text-xs">
                    {newickText}
                  </pre>
                );
              })}
            </div>
          </details>

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
