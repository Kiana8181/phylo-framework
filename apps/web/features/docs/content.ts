// Authored documentation overlay.
//
// Conceptual method summaries are sourced from each method's official external
// documentation (linked per method). The "maps to method parameter" entries are
// included ONLY where a clear, verifiable relationship exists — most are taken
// from the native flag/function already named in the field's in-code
// `description` (param.schema.json). Fields without a clear mapping are left
// blank by design; wrapper-only fields (column mapping, the doMapping toggle)
// are auto-marked "N/A (wrapper-specific)" by the model.
//
// The set of fields, allowed values, defaults and conditional logic is NOT
// authored here — it is auto-generated from the contracts JSON (see model.ts).

import type { MethodContent, MethodId } from "./types";

/** Shared package value propositions — reused by the docs overview and the landing page. */
export type ValueProp = {
  id: string;
  title: string;
  body: string;
  href?: string;
  linkLabel?: string;
};

export const VALUE_PROPS: ValueProp[] = [
  {
    id: "unified-ui",
    title: "One friendly interface for four methods",
    body:
      "The raw tools have no user-friendly environment and are awkward to install and run. Phylo Runner wraps Dowser, GCtree, BrepPhylo and ClonalTree behind a single guided form.",
    href: "/dashboard",
    linkLabel: "Open the dashboard",
  },
  {
    id: "any-input",
    title: "One dataset, every method",
    body:
      "Upload TSV or CSV once and run all four methods — including GCtree, which natively accepts no tabular input — through behind-the-scenes conversion with no data loss.",
    href: "/dashboard",
    linkLabel: "Start a run",
  },
  {
    id: "column-mapping",
    title: "Column mapping, no re-upload",
    body:
      "Each method expects specific input column names. Map your columns to a method's expected inputs without editing your data and without re-uploading it.",
  },
  {
    id: "upload-once",
    title: "Upload once, reuse everywhere",
    body:
      "Re-use the same uploaded dataset across as many runs as you like — there is no need to re-upload between runs.",
    href: "/dashboard/files",
    linkLabel: "Manage files",
  },
  {
    id: "param-transfer",
    title: "Carry parameters forward",
    body:
      "Send a previous run's settings into the next run and change a single value, instead of refilling the whole form by hand.",
    href: "/dashboard",
    linkLabel: "Open the dashboard",
  },
  {
    id: "sequence-tracing",
    title: "Trace sequences across runs",
    body:
      "When the same data is run multiple times, locate where a specific sequence sits in each run and compare the trees side by side.",
    href: "/dashboard/comparison",
    linkLabel: "Open Sequence Trace",
  },
  {
    id: "results",
    title: "Saved, revisitable results",
    body:
      "View each run's trees in multiple formats alongside the generated outputs. Results are saved and can be revisited; download images and the complete method output.",
    href: "/dashboard/history",
    linkLabel: "Browse run history",
  },
  {
    id: "server",
    title: "Runs on the server",
    body:
      "Methods execute server-side, so your local machine's resources aren't consumed while trees are built.",
  },
  {
    id: "node-detail",
    title: "Click any node for details",
    body: "In every tree, click a node to see that node's complete information.",
  },
];

const METHOD_CONTENT: Record<MethodId, MethodContent> = {
  dowser: {
    id: "dowser",
    displayName: "Dowser",
    tagline: "B-cell receptor phylogenetics in the Immcantation framework",
    externalDocUrl: "https://dowser.readthedocs.io/en/stable/",
    externalDocLabel: "dowser.readthedocs.io",
    summary: [
      "Dowser is an R package in the Immcantation framework for reconstructing and analysing B-cell receptor (BCR) phylogenies. It builds lineage trees from BCR sequences, reconstructs germline and intermediate (internal-node) sequences, and statistically tests for evidence of B-cell evolution, migration and differentiation.",
      "It accepts AIRR-formatted data and Change-O clone tables, supports several tree-building algorithms — maximum parsimony, maximum likelihood, and the immunoglobulin-specific IgPhyML — and can analyse paired heavy/light chains.",
    ],
    capabilities: [
      "Multiple tree builders: pratchet, pml, dnapars, dnaml, IgPhyML and RAxML",
      "Germline and intermediate (internal-node) sequence reconstruction",
      "Discrete trait analysis (migration, differentiation, isotype switching)",
      "Measurable-evolution / time-resolved analysis",
      "Paired heavy/light chain support",
      "Publication-quality lineage visualisations",
    ],
    inputTypes: [
      {
        type: "TSV",
        handling:
          "AIRR / Change-O clone table (tab-separated), used directly as the clone table. Enable column mapping if your headers differ from the canonical AIRR keys.",
      },
      {
        type: "CSV",
        handling:
          "The same AIRR / Change-O clone table in comma-separated form; converted to the canonical table before the R service runs.",
      },
      {
        type: "RDA / RDS",
        handling: "Saved R data objects containing the clone/AIRR data, loaded directly by the R service.",
        needsVerification: true,
      },
    ],
    fieldMappings: {
      tree_build:
        "Selects Dowser's tree-building algorithm — the enum values are Dowser's own `build` options (pratchet, pml, dnapars, dnaml, igphyml, raxml).",
      minseq: "Dowser `formatClones` minimum sequences per clone.",
      collapse_identical_sequences: "Dowser `formatClones` collapse-identical-sequences option.",
      mod3: "Dowser `formatClones` `mod3` (pad sequence lengths to multiples of three).",
      filterstop: "Dowser `formatClones` `filterstop` (drop sequences with in-frame stop codons).",
      use_regions: "Dowser `formatClones` region assignment (uses CDR/FWR region columns).",
      trait_fields: "Passed to Dowser `formatClones` as `traits`.",
      run_test_ps: "Runs Dowser `testPS` (parsimony-score association test).",
      run_test_sp: "Runs Dowser `testSP` (switch-proportion test).",
      run_test_sc: "Runs Dowser `testSC` (switch-count test).",
      partition_model: "IgPhyML partition model (single, cf, hl, hlf, hlc, hlcf).",
      modelfile: "Custom Dowser parsimony trait model-file content.",
    },
    conditionalNotes: [
      "Raw FASTA is not accepted — Dowser expects sequences already processed through AIRR / Change-O / IgBLAST / IMGT.",
      "The Discrete Trait Analysis fields appear only in that analysis mode; the IgPhyML partition options appear only when the tree builder is IgPhyML; the paired heavy/light options appear only in HL chain mode.",
    ],
  },

  gctree: {
    id: "gctree",
    displayName: "GCtree",
    tagline: "Abundance-aware maximum-parsimony B-cell lineage trees",
    externalDocUrl: "https://matsen.group/gctree/",
    externalDocLabel: "matsen.group/gctree",
    summary: [
      "GCtree is a command-line utility and Python package that uses sequence abundance information in phylogenetic inference. It reconstructs genotype-collapsed B-cell lineage trees by combining PHYLIP/dnapars maximum-parsimony analysis with a branching-process ranking that breaks ties between equally parsimonious trees using observed clonal abundances.",
      "It natively expects an aligned FASTA with a root/germline plus abundance information (or a dnapars outfile and abundance bundle, or a previously computed GCtree forest pickle for re-ranking/re-rendering).",
    ],
    capabilities: [
      "Phylogenetic inference that incorporates sequence abundance",
      "PHYLIP/dnapars parsimony combined with branching-process ranking",
      "Genotype-collapsed lineage-tree representation",
      "Re-ranking and re-rendering from a saved forest pickle",
      "Isotype annotation and customisable tree rendering / output formats",
    ],
    inputTypes: [
      {
        type: "Aligned FASTA",
        handling:
          "Aligned sequences with a root/germline ID; converted to PHYLIP and run through dnapars, then ranked by GCtree.",
      },
      {
        type: "CSV / TSV",
        handling:
          "Tabular AIRR/Change-O-style input. The framework converts the aligned-sequence column to FASTA before inference — enabling GCtree on tabular data it cannot natively read.",
      },
      {
        type: "ZIP",
        handling:
          "A dnapars outfile + abundances bundle (with manifest.json and optional idmap / position maps), used to run GCtree ranking directly.",
      },
    ],
    fieldMappings: {
      frame: "GCtree CLI `--frame` (reading frame for amino-acid mutation annotation).",
      frame2: "GCtree CLI `--frame2` (second-chain frame, paired-chain workflows).",
      chain_split: "GCtree CLI `--chain_split`.",
      ranking_strategy: "GCtree ranking expression (B = branching-process log-loss, A = alleles, R = reversions).",
      quick: "`--quick` passed to mkconfig/dnapars for a faster parsimony search.",
      jumble: "`--jumble N` passed to mkconfig (DNAPARS random input orderings).",
      img_type: "GCtree CLI `--img_type` (output figure format).",
      outbase: "GCtree CLI `--outbase` (output basename).",
      idlabel: "GCtree CLI `--idlabel` (label nodes with sequence IDs; writes inferred-sequence FASTA).",
      show_nucleotide_mutations: "GCtree CLI `--show_nucleotide_mutations`.",
      summarize_forest: "GCtree CLI `--summarize_forest`.",
      tree_stats: "GCtree CLI `--tree_stats`.",
      top_n: "Number of top-ranked trees extracted from GCtree output.",
      apply_isotype: "Invokes GCtree's isotype-annotation utility (idmap + isotype map bundle).",
    },
    conditionalNotes: [
      "The column-mapping toggle and fields appear only for CSV/TSV input (the FASTA-conversion path).",
      "Root sequence ID, quick search and jumble apply only to the FASTA-derived scenarios; the extra coloring mode appears only when coloring settings are enabled.",
    ],
  },

  brepphylo: {
    id: "brepphylo",
    displayName: "BrepPhylo",
    tagline: "B-cell repertoire lineage trees with class-switch analysis",
    externalDocUrl:
      "https://htmlpreview.github.io/?https://github.com/Fraternalilab/BrepPhylo/blob/main/vignettes/phylogenetic.html",
    externalDocLabel: "BrepPhylo vignette",
    summary: [
      "BrepPhylo is an R package that reconstructs evolutionary lineages of B-cell clonotypes from high-throughput immunoglobulin sequencing data. It wraps established phylogenetic tools so researchers can build lineage trees, identify Class-Switch Recombination (CSR) events, and generate interpretable outputs.",
      "It accepts AIRR / rearrangement tables, supports simple-parsimony, DNAPARS and IgPhyML tree construction, uses species-specific germline V(D)J references, and can process either raw sequences (with alignment) or IMGT-gapped alignments.",
    ],
    capabilities: [
      "Tree construction via simple parsimony, DNAPARS or IgPhyML",
      "Class-Switch Recombination (CSR) / arborescence analysis",
      "Species-specific germline reference handling (with custom germline sets)",
      "Handles both raw sequences (MSA) and IMGT-gapped alignments",
      "Per-clone and gathered phylogeny plots in several styles",
    ],
    inputTypes: [
      {
        type: "TSV",
        handling:
          "AIRR / rearrangement table (tab-separated). Columns for sequence, clone ID and germline allele are selected by name; clones below the size threshold are dropped.",
      },
      {
        type: "CSV",
        handling: "The same rearrangement table in comma-separated form.",
      },
    ],
    fieldMappings: {
      tree_type: "BrepPhylo `treeConstruction$type` (simple, dnapars or igphyml).",
      collapse_and_replace: "DNAPARS collapse-identical-then-re-expand option (tree_type = dnapars).",
      igphyml_accuracy: "IgPhyML accuracy preset (basic, high, extreme).",
      make_alignment_pdf: "BrepPhylo `makeAlignmentPDFConstruction` (per-clone alignment PDF; needs LaTeX).",
      algorithm: "Multiple-sequence aligner used for raw sequences (ClustalOmega or ClustalW).",
      species: "Selects the BrepPhylo germline reference set for the organism.",
      germline_set_text: "Custom IMGT-format germline V-gene FASTA (used when species = custom).",
    },
    conditionalNotes: [
      "The collapse option appears only for DNAPARS; the IgPhyML accuracy preset only for IgPhyML.",
      "The alignment algorithm appears only for raw-sequence input; the custom germline textarea only when species = custom; the isotype column only when CSR analysis is enabled.",
      "Restrict-to-clone-IDs and ignore-clone-IDs are mutually exclusive.",
    ],
  },

  clonaltree: {
    id: "clonaltree",
    displayName: "ClonalTree",
    tagline: "Minimum-spanning-tree B-cell lineage reconstruction",
    externalDocUrl: "https://github.com/julibinho/ClonalTree/",
    externalDocLabel: "github.com/julibinho/ClonalTree",
    summary: [
      "ClonalTree reconstructs B-cell receptor lineage trees from clonally related sequences. It uses a minimum-spanning-tree algorithm combined with genotype abundance information to infer parsimonious trees representing the evolutionary relationships within a clone.",
      "In this framework it runs an AIRR/IMGT processing pipeline — formatting and labelling, initial clustering, optional refinement, two-level clonotype grouping, and clonal-tree construction — and outputs trees in Newick format plus parent/cost tables.",
    ],
    capabilities: [
      "Minimum-spanning-tree lineage reconstruction with abundance weighting",
      "AIRR/IMGT formatting, clustering and refinement pipeline",
      "Configurable distance methods (V, J, CDR3) and clonotype grouping (L1–L5)",
      "Optional tree revision",
      "Newick output plus parent-relationship / cost tables",
    ],
    inputTypes: [
      {
        type: "TSV",
        handling:
          "AIRR / IMGT HighV-QUEST table (tab-separated), fed into the formatting and clustering pipeline. Enable column mapping if headers differ from the canonical keys.",
      },
      {
        type: "CSV",
        handling: "Comma-separated table; converted to TSV when possible before the pipeline runs.",
      },
    ],
    fieldMappings: {
      abundance_threshold: "ClonalTree `format_labeling_imgt_airr.py -t` (minimum count retained during formatting).",
      clone_cdr3_similarity: "ClonalTree `initial_clustering.py -t` (initial CDR3 clustering threshold).",
      top_clones: "ClonalTree `top_clones.py -s` / `NUMBER_TOP_CLONE` (number of top clones analysed).",
      use_refinement: "Runs ClonalTree `refinement.py` before clonotype grouping.",
      v_distance: "Refinement V-distance mode (1 = Binary, 2 = Levenshtein, 3 = GIANA, 4 = K-mers).",
      j_distance: "Refinement J-distance mode (1 = Binary, 2 = Levenshtein, 3 = GIANA, 4 = K-mers).",
      cdr3_distance: "Refinement CDR3-distance mode (1 = Binary, 2 = Levenshtein, 3 = GIANA, 4 = K-mers).",
      combine_distance: "Refinement combine mode (1 = Mean, 2 = Weighted Mean, 3 = Harmonic Mean).",
      merge_singleton: "Refinement `MERGE_SINGLETON` setting.",
      clonotype_method: "Two-level clonotype definition method (L1–L5).",
      tree_use_abundance: "ClonalTree `clonal_tree.py -a` (abundance weighting).",
      tree_revision: "ClonalTree `clonal_tree.py -r` (tree revision).",
    },
    conditionalNotes: [
      "The column-mapping fields appear only when the mapping toggle is on; several alignment-column mappings additionally require the refinement step to be enabled.",
      "The clonotype similarity threshold is used by the L4 and L5 grouping methods.",
    ],
  },
};

export function getMethodContent(id: MethodId): MethodContent {
  return METHOD_CONTENT[id];
}
