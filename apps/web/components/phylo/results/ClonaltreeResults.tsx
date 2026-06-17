import { useMemo } from "react";
import type { RunResult, RunProvenance } from "@phylo/contracts";
import ResultSection from "./shared/ResultSection";
import MetricGrid from "./shared/MetricGrid";
import Facts from "./shared/Facts";
import DataTable, { type DataColumn } from "./shared/DataTable";

type CloneRow = { clone_id: string; abundance?: number; seqs?: number };
type RepRow = Record<string, unknown>;

function provenanceFacts(p?: RunProvenance) {
  if (!p) return [];
  return [
    { label: "Clonotype submodule", value: p.clonotype_submodule?.tag ?? p.clonotype_submodule?.commit ?? p.clonotype_submodule?.ref },
    { label: "MUSCLE", value: p.muscle?.version_raw ?? p.muscle?.major },
    { label: "Container", value: p.container?.image_ref ?? p.container?.image_digest },
  ];
}

export default function ClonaltreeResults({ result }: { result: RunResult }) {
  const stats = (result.stats ?? {}) as Record<string, unknown>;
  const params = (result.params ?? {}) as Record<string, unknown>;

  const cloneRows = useMemo<CloneRow[]>(() => {
    const clones = result.clones as { clone_id?: string[]; abundance?: number[]; seqs?: number[] } | null;
    return (clones?.clone_id ?? []).map((id, i) => ({
      clone_id: id,
      abundance: clones?.abundance?.[i],
      seqs: clones?.seqs?.[i],
    }));
  }, [result.clones]);

  const repertoire = result.tables?.repertoire_two_levels_info;
  const repRows = useMemo<RepRow[]>(
    () => (Array.isArray(repertoire?.rows) ? (repertoire?.rows as RepRow[]) : []),
    [repertoire?.rows],
  );
  const repColumns = useMemo<DataColumn<RepRow>[]>(() => {
    const cols =
      (Array.isArray(repertoire?.columns) && repertoire?.columns.length
        ? repertoire?.columns
        : repRows[0]
          ? Object.keys(repRows[0])
          : []) ?? [];
    return cols.map((c) => ({ key: c, header: c, className: "whitespace-nowrap px-3 py-2" }));
  }, [repertoire?.columns, repRows]);

  const cloneColumns: DataColumn<CloneRow>[] = [
    { key: "clone_id", header: "Clone ID" },
    ...(cloneRows.some((r) => r.abundance != null)
      ? [{ key: "abundance", header: "Abundance", value: (r: CloneRow) => String(r.abundance ?? "") }]
      : []),
    { key: "seqs", header: "Sequences", value: (r: CloneRow) => String(r.seqs ?? "") },
  ];

  const provFacts = provenanceFacts(result.provenance);

  return (
    <div className="space-y-4">
      <MetricGrid
        metrics={[
          { label: "Clones", value: stats.n_clones as number },
          { label: "Trees", value: stats.n_trees as number },
          { label: "Sequences", value: stats.total_seqs as number },
        ]}
      />

      <ResultSection title="ClonalTree settings" description="Resolved thresholds and clonotype settings for this run.">
        <Facts
          facts={[
            { label: "Refinement", value: (stats.use_refinement ?? params.use_refinement) ? "On" : "Off" },
            { label: "Clonotype method", value: (stats.clonotype_method ?? params.clonotype_method) as string },
            { label: "Similarity threshold", value: (stats.clonotype_similarity_threshold ?? params.clone_cdr3_similarity) as number },
            { label: "Top clones", value: (stats.top_clones ?? params.top_clones) as number },
            { label: "Clone threshold", value: stats.clone_threshold as number },
            { label: "Abundance threshold", value: stats.abundance_threshold as number },
          ]}
        />
      </ResultSection>

      {cloneRows.length > 0 && (
        <ResultSection title="Clone summary" description="Clones aligned 1:1 with the trees below." flush>
          <DataTable columns={cloneColumns} rows={cloneRows} />
        </ResultSection>
      )}

      {repRows.length > 0 && repColumns.length > 0 && (
        <ResultSection
          title="Repertoire (two-level info)"
          description={repertoire?.filename || "repertoire_two_levels_info.tsv"}
          flush
        >
          <DataTable columns={repColumns} rows={repRows} searchable copyable />
          {repertoire?.truncated && (
            <div className="border-t px-4 py-2 text-xs text-muted-foreground">
              Preview truncated to {repRows.length} rows (total {repertoire?.total_rows ?? repRows.length}).
            </div>
          )}
        </ResultSection>
      )}

      {provFacts.some((f) => f.value != null) && (
        <ResultSection title="Provenance" description="Pinned software versions and container image.">
          <Facts facts={provFacts} />
        </ResultSection>
      )}
    </div>
  );
}
