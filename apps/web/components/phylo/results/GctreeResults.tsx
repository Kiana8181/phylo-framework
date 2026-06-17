import type { RunResult } from "@phylo/contracts";
import ResultSection from "./shared/ResultSection";
import Facts, { StatusBadge } from "./shared/Facts";

const QUALITY_LABEL: Record<string, string> = {
  gctree_ranked: "Ranked",
  gctree_rerendered_from_pickle: "Re-rendered from pickle",
  failed_gctree_infer_unranked_dnapars_available: "DNAPARS fallback (unranked)",
  failed: "Failed",
};

function humanize(v: string): string {
  return v ? v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "";
}

export default function GctreeResults({ result }: { result: RunResult }) {
  const stats = (result.stats ?? {}) as Record<string, unknown>;
  const params = (result.params ?? {}) as Record<string, unknown>;
  const quality = String(stats.result_quality ?? "");
  const scenario = String(stats.input_scenario ?? params.input_scenario ?? "");

  const tone = quality === "gctree_ranked" ? "success" : quality.startsWith("failed") ? "danger" : "warning";

  return (
    <ResultSection
      title="GCtree inference"
      description="Trees are shown below in GCtree rank order (rank 1 = best). Rendered figures are in Artifacts."
      badge={quality ? <StatusBadge tone={tone}>{QUALITY_LABEL[quality] ?? humanize(quality)}</StatusBadge> : undefined}
    >
      <Facts
        facts={[
          { label: "Input scenario", value: humanize(scenario) },
          { label: "Ranking strategy", value: params.ranking_strategy as string },
          { label: "Trees returned (top N)", value: result.trees?.length ?? (params.top_n as number) },
          { label: "Coding frame", value: params.frame as number },
        ]}
      />
      {quality && quality !== "gctree_ranked" && (
        <p className="mt-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
          {quality.startsWith("failed_gctree_infer")
            ? "GCtree ranking did not complete; an unranked DNAPARS tree is shown for debugging. Treat the ordering as not GCtree-ranked."
            : quality === "gctree_rerendered_from_pickle"
              ? "Trees were re-rendered from a saved GCtree forest pickle rather than re-inferred."
              : "GCtree did not produce a successful result; see logs below."}
        </p>
      )}
    </ResultSection>
  );
}
