// I/O specification helpers — derived from the contracts, not authored.
// Output top-level keys come straight from each method's result.schema.json
// (the same schema the API validates results against), so the I/O doc cannot
// drift from what a completed run actually emits.

import { METHOD_IDS, type MethodId } from "./types";

import dowserResult from "@phylo/contracts/methods/dowser/result.schema.json";
import gctreeResult from "@phylo/contracts/methods/gctree/result.schema.json";
import brepphyloResult from "@phylo/contracts/methods/brepphylo/result.schema.json";
import clonaltreeResult from "@phylo/contracts/methods/clonaltree/result.schema.json";

type ResultSchema = { properties?: Record<string, unknown> };

const RESULT_SCHEMAS: Record<MethodId, ResultSchema> = {
  dowser: dowserResult as ResultSchema,
  gctree: gctreeResult as ResultSchema,
  brepphylo: brepphyloResult as ResultSchema,
  clonaltree: clonaltreeResult as ResultSchema,
};

/** Top-level keys a completed run's result JSON can contain, per its result.schema.json. */
export function getResultTopLevelKeys(id: MethodId): string[] {
  return Object.keys(RESULT_SCHEMAS[id].properties ?? {});
}

// Operational/plumbing keys — not biologically meaningful, hidden from the
// biologist-facing outputs list.
const TECHNICAL_OUTPUT_KEYS = new Set([
  "ok",
  "error",
  "step",
  "render",
  "render_meta",
  "tree_model",
  "logs",
  "warnings",
  "artifact_zip_b64",
  "artifact_name",
  "artifact_files",
  "artifacts",
]);

// Biologist-facing descriptions for the derived result keys. This is a friendly
// label overlay over the real result.schema.json keys — it never adds an output
// a method does not emit; keys present in the schema but absent here fall back to
// a humanised name.
const BIOLOGICAL_OUTPUT_LABELS: Record<string, string> = {
  trees: "Lineage trees, one per clone (Newick)",
  trees_detail: "Per-tree detail — tip labels, node table, reconstructed sequences",
  figures: "Rendered lineage-tree figures",
  annotations: "Per-tip annotations for plotting",
  clones: "Clone summary (clone id + sequence count)",
  clone_catalog: "Full clone catalog",
  node_abundances: "Observed abundance per node",
  label_to_sequence_id: "Tip-label ↔ sequence-id map",
  stats: "Run summary statistics",
  input_qc: "Input quality-control summary",
  data_provenance: "Data provenance (transformations applied to your data)",
  provenance: "Data provenance (transformations applied to your data)",
  discrete_trait_analysis:
    "Discrete trait analysis — trait switching along the tree (e.g. isotype, tissue)",
  time_evolution: "Measurable-evolution / time-resolved analysis",
  igphyml: "IgPhyML selection parameters",
  chain_qc: "Heavy / light chain QC",
  tables: "Data tables (e.g. clonotype / repertoire info)",
  analysis: "Analysis — germline distance, class-switch (CSR) events, arborescence",
  diagnostics: "Per-row / per-clone diagnostics (dropped, rejected, unmapped rows)",
};

function humanizeOutputKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * The biologically meaningful outputs a completed run emits, derived from the
 * method's result.schema.json (operational keys filtered out, friendly labels
 * applied). Nothing here is invented — every entry corresponds to a real
 * top-level result key.
 */
export function getBiologicalOutputs(id: MethodId): { key: string; label: string }[] {
  return getResultTopLevelKeys(id)
    .filter((key) => !TECHNICAL_OUTPUT_KEYS.has(key))
    .map((key) => ({ key, label: BIOLOGICAL_OUTPUT_LABELS[key] ?? humanizeOutputKey(key) }));
}

/**
 * The artifact kinds a run can emit. This is the `ArtifactKind` enum from the
 * persistence layer (apps/api/database/models.py → run_artifacts.artifact_kind);
 * it is not expressed as an enum in the contracts JSON, so it is listed here with
 * that single source cited.
 */
export const ARTIFACT_KINDS = [
  "image",
  "newick",
  "table",
  "fasta",
  "json",
  "log",
  "zip",
  "other",
] as const;

export { METHOD_IDS };
