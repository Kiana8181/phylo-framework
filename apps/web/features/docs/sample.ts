// The worked example that the docs hand out: one real AIRR clone that has been
// run through all four methods, so a reader can download it, see the exact
// parameters and the resulting tree, and re-run it themselves.
//
// The dataset is clone 3128 of the official Dowser example dataset
// (`ExampleAirr`) — 43 sequences, a single clone. It is a single clone because
// GCtree only accepts one clone per run; keeping it to one is what lets the
// *same* file go through all four methods and be compared side by side.
//
// `SAMPLE_PARAMS` is transcribed verbatim from
// `article-tests/tests-results/ExampleAirr_clone_3128/<method>/Run 1/inputs.json`
// (runs 1–3 of each method use identical parameters). The tree images are the
// matching `Run 1/tree.png`. If the harness is re-run and its outputs change,
// update the PNGs in `public/samples/trees/` and this file together.

import { getLoadedMethod } from "./loader";
import { fieldLabel } from "./model";
import type { MethodId } from "./types";

export const SAMPLE_FILENAME = "ExampleAirr_clone_3128.tsv";
export const SAMPLE_HREF = `/samples/${SAMPLE_FILENAME}`;
export const SAMPLE_MIME = "text/tab-separated-values";

/** Sequences in the file, used in the download blurbs. */
export const SAMPLE_SEQUENCE_COUNT = 43;

/** sessionStorage key carrying a "Try it yourself" click from docs to the dashboard. */
export const TRY_SAMPLE_KEY = "phylo_try_sample";

export type TrySampleIntent = {
  methodId: MethodId;
  params: Record<string, unknown>;
};

export const SAMPLE_TREE_SRC: Record<MethodId, string> = {
  dowser: "/samples/trees/dowser.png",
  gctree: "/samples/trees/gctree.png",
  brepphylo: "/samples/trees/brepphylo.png",
  clonaltree: "/samples/trees/clonaltree.png",
};

export const SAMPLE_PARAMS: Record<MethodId, Record<string, unknown>> = {
  dowser: {
    doMapping: false,
    analysis_mode: "tree_with_internal_sequences",
    tree_build: "dnapars",
    minseq: 3,
    nproc: 1,
    seed: 42,
    collapse_identical_sequences: true,
    mod3: false,
    filterstop: false,
    use_regions: false,
    collapse_internal_nodes: true,
    check_divergence: true,
    label_field: "sequence_id",
    unknown_value: "unknown",
    tipsize: 2,
    tip_size_by: "duplicate_count",
    max_tip_categories: 30,
    return_internal_sequences: true,
    show_node_numbers: true,
    export_all_sequences_fasta: true,
    chain_mode: "H",
    column_map: {
      locus: "",
      j_call: "",
      v_call: "",
      cell_id: "",
      clone_id: "",
      junction: "",
      sequence_id: "",
      j_region_end: "",
      v_region_end: "",
      j_region_start: "",
      v_region_start: "",
      junction_length: "",
      sequence_alignment: "",
      germline_alignment_d_mask: "",
    },
  },
  gctree: {
    input_scenario: "airr_or_changeo_table_adapter",
    doMapping: false,
    germline_row_present: "no",
    root_sequence_id: "GL",
    root_sequence_alignment:
      "GAGGTGCAGCTGGTGGAGTCTGGGGGA...GGCTTGGTACAGCCAGGGCGGTCCCTGAGACTCTCCTGTACAGCTTCTGGATTCACCTTT............GGTGATTATGCTATGAGCTGGTTCCGCCAGGCTCCAGGGAAGGGGCTGGAGTGGGTAGGTTTCATTAGAAGCAAAGCTTATGGTGGGACAACAGAATACGCCGCGTCTGTGAAA...GGCAGATTCACCATCTCAAGAGATGATTCCAAAAGCATCGCCTATCTGCAAATGAACAGCCTGAAAACCGAGGACACAGCCGTGTATTACTGTACTAGAGANNNNNNNNNNNNNNNNNNNNNAGCTGGTACNAACTGGTTCGACCCCTGGGGCCAGGGAACCCTGGTCACCGTCTCCTCAG",
    frame: 1,
    chain_split: 0,
    top_n: 3,
    ranking_strategy: "B,A",
    quick: true,
    jumble: 0,
    img_type: "png",
    outbase: "gctree.out",
    idlabel: true,
    show_nucleotide_mutations: false,
    summarize_forest: false,
    tree_stats: false,
    apply_coloring_settings: false,
    apply_isotype: false,
    column_map: {
      sequence_id: "",
      sequence_alignment: "",
    },
  },
  brepphylo: {
    sequence_column: "sequence_alignment",
    clone_id_column: "clone_id",
    germline_id_column: "v_call",
    label_column: "sequence_id",
    input_sequence_mode: "aligned_imgt_gapped",
    tree_type: "dnapars",
    collapse_and_replace: true,
    make_alignment_pdf: false,
    min_clone_size: 3,
    species: "Homo_sapiens",
    plot_type: "phylogram",
    plot_format: "png",
    gather_plots: true,
    enable_csr_analysis: false,
  },
  clonaltree: {
    doMapping: false,
    run_name: "ExampleAirr_clone_3128",
    abundance_threshold: 0,
    clone_cdr3_similarity: 0.7,
    top_clones: 1,
    clonotypes_per_clone: "all",
    use_input_alignment: true,
    use_refinement: false,
    v_distance: 1,
    j_distance: 2,
    cdr3_distance: 2,
    combine_distance: 1,
    merge_singleton: true,
    clonotype_method: "L3",
    clonotype_similarity_threshold: 0.8,
    tree_use_abundance: true,
    tree_revision: true,
    column_map: {
      np1: "",
      np2: "",
      cdr1: "",
      cdr2: "",
      cdr3: "",
      fwr1: "",
      fwr2: "",
      fwr3: "",
      fwr4: "",
      d_call: "",
      j_call: "",
      v_call: "",
      cdr3_aa: "",
      cdr1_end: "",
      cdr2_end: "",
      cdr3_end: "",
      sequence: "",
      cdr1_start: "",
      cdr2_start: "",
      cdr3_start: "",
      d_identity: "",
      j_identity: "",
      productive: "",
      v_identity: "",
      junction_aa: "",
      sequence_id: "",
      d_sequence_end: "",
      d_sequence_start: "",
      v_sequence_start: "",
      sequence_alignment: "",
      d_germline_alignment: "",
      j_germline_alignment: "",
      j_sequence_alignment: "",
      v_germline_alignment: "",
      v_sequence_alignment: "",
      j_sequence_alignment_aa: "",
      v_sequence_alignment_aa: "",
      germline_alignment_d_mask: "",
    },
  },
};

/** One row of the "parameters used" table. */
export type SampleParamRow = {
  /** Field path as the form knows it, e.g. `tree_build` or `column_map.v_call`. */
  path: string;
  label: string;
  value: string;
  /** True for values too long to sit on one line (e.g. the GCtree root sequence). */
  long: boolean;
};

/** Values above this render in a scrollable monospace cell instead of inline. */
const LONG_VALUE_CHARS = 80;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/**
 * The sample run's parameters, flattened and ready to render.
 *
 * Blank values are dropped — with `doMapping` off every `column_map.*` entry is
 * an empty string, and listing forty of them would bury the parameters that
 * actually shaped the run. Labels come from the method's `param.schema.json`
 * via `fieldLabel`, the same JSON the live form renders, so they cannot drift.
 */
export function visibleParamEntries(id: MethodId): SampleParamRow[] {
  const { paramSchema } = getLoadedMethod(id);
  const rows: SampleParamRow[] = [];

  const walk = (node: Record<string, unknown>, prefix: string) => {
    for (const [key, value] of Object.entries(node)) {
      const path = prefix ? `${prefix}.${key}` : key;
      if (isPlainObject(value)) {
        walk(value, path);
        continue;
      }
      if (value === "" || value === null || value === undefined) continue;
      const text = formatValue(value);
      rows.push({
        path,
        label: fieldLabel(paramSchema, path),
        value: text,
        long: text.length > LONG_VALUE_CHARS,
      });
    }
  };

  walk(SAMPLE_PARAMS[id], "");
  return rows;
}
