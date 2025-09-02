"use client";

import MethodsGrid from "@/components/phylo/MethodsGrid";
import ResultsSummary from "@/components/phylo/ResultsSummary";
import RunParameters from "@/components/phylo/RunParameters";
import RunProgress from "@/components/phylo/RunProgress";
import TreesCarousel from "@/components/phylo/TreesCarousel";
import { useMethods, useMethodSpec } from "@/features/methods/hooks";
import {
  useCreateRun,
  useRunResult,
  useRunStatus,
} from "@/features/runs/hooks";
import { cleanNewick } from "@/lib/newick";
import type { MethodInfo } from "@phylo/contracts";
import { useEffect, useMemo, useState } from "react";

export default function Home() {
  const { data: methods } = useMethods();
  const [selected, setSelected] = useState<MethodInfo | null>(null);
  const { data: spec } = useMethodSpec(selected?.id);

  const [files, setFiles] = useState<File[]>([]);
  const [runId, setRunId] = useState<string | null>(null);

  const createRun = useCreateRun();
  const { data: status } = useRunStatus(runId ?? undefined);
  const resultEnabled = status?.status === "DONE" && !!runId;
  const { data: result } = useRunResult(runId ?? undefined, resultEnabled);

  const cloneRows = useMemo(
    () =>
      result?.clones?.clone_id?.map((id: string, i: number) => ({
        id,
        seqs: result?.clones?.seqs?.[i],
      })) ?? [],
    [result]
  );

  useEffect(() => {
    if (status?.status === "ERROR") setRunId(null);
  }, [status]);

  return (
    <main className="mx-auto max-w-6xl p-6 space-y-8">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
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
        />
      </section>

      {/* Parameters & File Upload */}
      {spec && (
        <RunParameters
          spec={spec}
          files={files}
          onFiles={setFiles}
          onSubmit={async (params) => {
            if (selected?.id === "dowser" && files.length === 0) {
              const { notify } = await import("@/lib/notify");
              notify.error("File required", "Please attach at least one file");
              return;
            }

            const fd = new FormData();
            fd.set("params", JSON.stringify(params));
            files.forEach((f) => fd.append("file", f));

            setRunId(null);
            const res = await createRun.mutateAsync({
              methodId: spec.id,
              formData: fd,
            });
            setRunId(res.run_id);
          }}
        />
      )}

      {/* Progress */}
      {runId && (
        <RunProgress
          runId={runId}
          status={status?.status}
          progress={status?.progress ?? 0}
          message={status?.message}
        />
      )}

      {/* Results */}
      {result && (
        <section className="space-y-6">
          <ResultsSummary stats={result?.stats} cloneRows={cloneRows} />

          <TreesCarousel
            trees={result.trees ?? []}
            figures={result.figures}
            annotations={result.annotations}
            cleanNewick={cleanNewick}
          />

          {/* Raw Newick (optional) */}
          <details className="rounded border p-3 bg-card/50 overflow-x-scroll">
            <summary className="cursor-pointer text-sm font-medium">
              Show Newick text
            </summary>
            <div className="mt-2 space-y-2">
              {(result.trees ?? []).map((nwk: string, i: number) => (
                <pre key={i} className="whitespace-pre-wrap text-xs">
                  {nwk}
                </pre>
              ))}
            </div>
          </details>
        </section>
      )}
    </main>
  );
}
