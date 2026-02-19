"use client";

import MethodsGrid from "@/components/phylo/MethodsGrid";
import ResultsSummary from "@/components/phylo/ResultsSummary";
import RunParameters from "@/components/phylo/RunParameters";
import RunProgress from "@/components/phylo/RunProgress";
import TreesCarousel from "@/components/phylo/TreesCarousel";
import { useMethods, useMethodSpec } from "@/features/methods/hooks";
import { RunsApi } from "@/features/runs/api";
import { useRunResult, useRunStatus } from "@/features/runs/hooks";
import { cleanNewick } from "@/lib/newick";
import type { MethodInfo } from "@phylo/contracts";
import Image from "next/image";
import { useSearchParams, useRouter } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";

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

function DashboardPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { data: methods } = useMethods();
  const [selected, setSelected] = useState<MethodInfo | null>(null);
  const { data: spec } = useMethodSpec(selected?.id);

  const [files, setFiles] = useState<File[]>([]);
  const [runId, setRunIdState] = useState<string | null>(null);

  const RUN_STORAGE_KEY = "phylo_current_run_id";

  const setRunId = (id: string | null) => {
    setRunIdState(id);
    if (typeof window !== "undefined") {
      if (id) window.localStorage.setItem(RUN_STORAGE_KEY, id);
      else window.localStorage.removeItem(RUN_STORAGE_KEY);
      
      // Update URL query param
      const url = new URL(window.location.href);
      if (id) {
        url.searchParams.set("runId", id);
      } else {
        url.searchParams.delete("runId");
      }
      router.replace(url.pathname + url.search, { scroll: false });
    }
  };

  // When opening from history (e.g. /dashboard?runId=xxx), load that run
  const runIdFromUrl = searchParams.get("runId");
  useEffect(() => {
    if (!runIdFromUrl) return;
    setRunIdState(runIdFromUrl);
  }, [runIdFromUrl]);

  useEffect(() => {
    let cancelled = false;
    const restoreFromStorage = () => {
      if (cancelled || typeof window === "undefined") return;
      const stored = window.localStorage.getItem(RUN_STORAGE_KEY);
      if (stored) setRunIdState(stored);
    };
    // If URL has runId, it was already set above; otherwise try API then storage
    if (!runIdFromUrl) {
      RunsApi.getCurrentRun()
        .then((data) => {
          if (cancelled) return;
          if (data?.run_id) setRunIdState(data.run_id);
          else restoreFromStorage();
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
  const resultEnabled = status?.status === "DONE" && !!runId;
  const { data: result } = useRunResult(runId ?? undefined, resultEnabled);

  const runInProgress = !!runId && status?.status !== "DONE" && status?.status !== "ERROR";

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
    const figs = (result as any)?.figures;
    if (!figs || typeof figs !== "object") return [] as Array<{ key: string; items: string[] }>;

    const out: Array<{ key: string; items: string[] }> = [];
    for (const [key, value] of Object.entries(figs)) {
      if (key === "phylogeny") continue;
      if (!Array.isArray(value)) continue;
      const items = value
        .map(_figureToDataUrl)
        .filter((src): src is string => Boolean(src));
      if (!items.length) continue;
      out.push({ key, items });
    }
    return out;
  }, [result]);

  return (
    <main className="mx-auto max-w-6xl w-full p-4 sm:p-6 space-y-6 sm:space-y-8">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl truncate">
            Phylo Runner
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Select a method, set parameters, upload your data, and generate
            trees.
          </p>
        </div>
      </header>

      {/* Methods */}
      <section className="space-y-3">
        <h2 className="text-lg font-medium">Methods</h2>
        <MethodsGrid
          methods={methods ?? []}
          selectedId={selected?.id ?? null}
          onSelect={(m) => {
            setSelected(m);
            setRunId(null);
          }}
          disabled={runInProgress}
        />
      </section>

      {/* Parameters & File Upload */}
      {spec && (
        <RunParameters
          spec={spec}
          files={files}
          onFiles={setFiles}
          onSubmitDone={(id) => setRunId(id)}
          runInProgress={runInProgress}
        />
      )}

      {/* Progress */}
      {runId && (
        <RunProgress
          runId={runId}
          status={status?.status}
          progress={status?.progress ?? 0}
          message={status?.message}
          statusError={statusError ? statusErr : undefined}
          onDismiss={status?.status === "ERROR" || statusError ? () => setRunId(null) : undefined}
        />
      )}

      {/* Results */}
      {result && (
        <section className="space-y-6">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-xl font-semibold">Results</h2>
            {status?.status === "DONE" && (
              <Button
                variant="default"
                onClick={() => {
                  setRunId(null);
                  setFiles([]);
                  setSelected(null);
                }}
              >
                Start another run
              </Button>
            )}
          </div>
          <ResultsSummary
            stats={result?.stats}
            cloneRows={cloneRows}
            artifact_zip_b64={result?.artifact_zip_b64}
            artifact_name={result?.artifact_name || ""}
          />

          {/* backend warnings */}
          {Array.isArray((result as any)?.warnings) &&
            (result as any).warnings.length > 0 && (
              <div className="rounded border p-3 bg-yellow-50 text-yellow-900 dark:bg-yellow-950/30 dark:text-yellow-200 text-sm space-y-1">
                {(result as any).warnings.map((w: any, i: number) => {
                  if (typeof w === "string") {
                    return <div key={i}>• {w}</div>;
                  }
                  const code = String(w?.code ?? "").trim();
                  const msg = String(w?.message ?? "").trim();
                  const treeId = String(w?.treeId ?? "").trim();
                  const prefix = code ? `[${code}] ` : "";
                  const suffix = treeId ? ` (tree: ${treeId})` : "";
                  return (
                    <div key={i}>
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
                  <summary className="cursor-pointer text-sm font-medium">
                    {_labelFromFigureKey(section.key)}
                  </summary>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    {section.items.map((src, i) =>
                      src.startsWith("data:application/pdf") ? (
                        <object
                          key={`${section.key}-${i}`}
                          data={src}
                          type="application/pdf"
                          className="w-full h-80 rounded border bg-white"
                        />
                      ) : (
                        <Image
                          key={`${section.key}-${i}`}
                          src={src}
                          alt={`${section.key}-${i + 1}`}
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

          {/* Raw Newick (optional) */}
          <details className="rounded border p-3 bg-card/50 overflow-x-scroll">
            <summary className="cursor-pointer text-sm font-medium">
              Show Newick text
            </summary>
            <div className="mt-2 space-y-2">
              {(result.trees ?? []).map((tree: any, i: number) => (
                <pre key={i} className="whitespace-pre-wrap text-xs">
                  {typeof tree === "string"
                    ? tree
                    : tree?.original_newick || tree?.newick || ""}
                </pre>
              ))}
            </div>
          </details>

          {/* Backend Logs (optional) */}
          {Array.isArray(result.logs) && result.logs.length > 0 && (
            <details className="rounded border p-3 bg-card/50">
              <summary className="cursor-pointer text-sm font-medium">
                Show model logs
              </summary>
              <div className="mt-2 max-h-64 overflow-y-auto space-y-3 text-xs font-mono">
                {result.logs.map((L, i) => (
                  <div
                    key={i}
                    className="border-b last:border-0 pb-2 last:pb-0"
                  >
                    <div className="flex justify-between gap-2 text-[11px]">
                      <span className="font-semibold">
                        {L.step || `Step ${i + 1}`}
                      </span>
                      {typeof L.ok === "boolean" && (
                        <span
                          className={L.ok ? "text-emerald-500" : "text-red-500"}
                        >
                          {L.ok ? "OK" : "FAIL"}
                        </span>
                      )}
                    </div>

                    {L.cmd && (
                      <div className="mt-1 text-[11px] text-muted-foreground">
                        <span className="font-semibold">cmd: </span>
                        <code className="break-all">{L.cmd}</code>
                      </div>
                    )}

                    {L.out && (
                      <pre className="mt-1 whitespace-pre-wrap">{L.out}</pre>
                    )}
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
