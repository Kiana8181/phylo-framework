"use client";

import { useMemo } from "react";
import type { RunResult } from "@phylo/contracts";
import { readTreeTipColorStats } from "@phylo/contracts";
import { cleanNewick } from "@/lib/newick";
import TreesCarousel from "@/components/phylo/TreesCarousel";
import RunArtifactsSection from "@/components/phylo/RunArtifactsSection";
import GctreeResults from "./GctreeResults";
import DowserResults from "./DowserResults";
import ClonaltreeResults from "./ClonaltreeResults";
import BrepphyloResults from "./BrepphyloResults";
import MetricGrid from "./shared/MetricGrid";
import WarningsCallout from "./shared/WarningsCallout";
import LogsSection from "./shared/LogsSection";

/** Renders the results page: the per-method sections + the shared general
 *  section (trees, warnings, logs, artifacts). */
export default function ResultsView({
  runId,
  methodId,
  result,
}: {
  runId?: string | null;
  methodId?: string | null;
  result: RunResult;
}) {
  const method = (methodId ?? result.method_id ?? "").toLowerCase();

  const { colorBy, unknownValue } = readTreeTipColorStats(result.stats);
  const showInternalNodesDefault = useMemo(() => {
    const mode = (result.stats as Record<string, unknown> | undefined)?.analysis_mode;
    return mode === "tree_with_internal_sequences";
  }, [result.stats]);

  const stats = (result.stats ?? {}) as Record<string, unknown>;

  const methodSection =
    method === "gctree" ? (
      <GctreeResults result={result} />
    ) : method === "dowser" ? (
      <DowserResults result={result} />
    ) : method === "clonaltree" ? (
      <ClonaltreeResults result={result} />
    ) : method === "brepphylo" ? (
      <BrepphyloResults result={result} />
    ) : (
      <MetricGrid
        metrics={[
          { label: "Clones", value: stats.n_clones as number },
          { label: "Trees", value: stats.n_trees as number },
          { label: "Sequences", value: stats.total_seqs as number },
        ]}
      />
    );

  return (
    <section className="space-y-4">
      <h3 className="text-lg font-medium">Results</h3>

      {methodSection}

      <WarningsCallout warnings={result.warnings} />

      <TreesCarousel
        runId={runId}
        trees={result.trees ?? []}
        cleanNewick={cleanNewick}
        colorBy={colorBy}
        unknownValue={unknownValue}
        showInternalNodesDefault={showInternalNodesDefault}
      />

      <LogsSection logs={result.logs} />

      <RunArtifactsSection runId={runId} />
    </section>
  );
}
