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
          "A pre-built bundle described by a manifest.json — used to run GCtree ranking, re-render a saved forest, or apply isotype annotation directly, skipping the FASTA/dnapars steps. See “ZIP bundle format” below for the exact layout and the mandatory / optional files for each scenario.",
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
    zipBundle: {
      intro: [
        "Because GCtree natively takes several different inputs (an aligned FASTA, a dnapars outfile + abundances, or a saved forest pickle), a ZIP upload is not just a folder of files — it is a self-describing bundle. A manifest.json at the top declares which scenario the bundle is for and maps each named role to a filename, so the framework knows exactly how to run GCtree without guessing.",
        "This is the input to use when you already have the intermediate artifacts and want to re-rank, re-render, or apply isotype annotation without re-running the parsimony search from scratch.",
      ],
      layout: [
        "The archive must contain exactly one manifest.json, either at the archive root or inside a single top-level folder that also holds the data files (a common folder wrapper from zipping a directory is fine). Multiple manifest.json files, or none, are rejected.",
        "manifest.json has two keys: \"scenario\" (one of the four values below) and \"files\" (an object mapping each role name to a filename, resolved relative to the manifest's own folder).",
        "Every filename listed under \"files\" must actually exist in the archive next to the manifest; a missing file for any declared role fails the upload. Extra files not referenced by the manifest are ignored. macOS __MACOSX / dotfile entries are skipped automatically.",
      ],
      manifestExample: `{
  "scenario": "dnapars_outfile_with_abundance",
  "files": {
    "dnapars_outfile": "outfile",
    "abundances_csv": "abundances.csv",
    "idmapfile": "idmap.txt",
    "isotype_mapfile": "isotypemap.csv",
    "idmapfile_isotype": "idmap_isotype.txt"
  }
}`,
      scenarios: [
        {
          scenario: "aligned_fasta_with_root",
          when: "You have an aligned FASTA (including the root/germline sequence) and want the framework to run dnapars and GCtree ranking for you.",
          required: [
            {
              role: "aligned_fasta",
              description: "Aligned sequences with the root/germline included; the starting point for parsimony inference.",
            },
          ],
          optional: [],
        },
        {
          scenario: "airr_or_changeo_table_adapter",
          when: "Same as above, but your sequences originate from an AIRR / Change-O table that has already been converted to an aligned FASTA for the bundle.",
          required: [
            {
              role: "aligned_fasta",
              description: "The aligned FASTA (with root) produced from the tabular data.",
            },
          ],
          optional: [],
        },
        {
          scenario: "dnapars_outfile_with_abundance",
          when: "You already ran PHYLIP/dnapars and want GCtree to rank the equally-parsimonious trees using your abundances — no re-inference.",
          required: [
            {
              role: "dnapars_outfile",
              description: "The raw dnapars `outfile` containing the parsimony trees.",
            },
            {
              role: "abundances_csv",
              description: "Per-genotype abundances: two columns per line (sequence label, abundance ≥ 0), comma- or tab-separated, no header required.",
            },
          ],
          optional: [],
        },
        {
          scenario: "gctree_forest_pickle",
          when: "You have a previously computed GCtree forest and only want to re-rank, re-render, or annotate it (e.g. change the figure format or add isotypes).",
          required: [
            {
              role: "gctree_forest_pickle",
              description: "The saved GCtree forest pickle (.p) to re-load.",
            },
          ],
          optional: [],
        },
      ],
      fileFormats: [
        {
          role: "idmapfile",
          description: "Optional in any scenario. Maps dnapars/tree tip labels to your original sequence IDs — two columns per line (label, sequence_id), separated by whitespace, comma, or tab. Used to label nodes and as the default idmap for isotype annotation.",
        },
        {
          role: "positionmapfile / positionmapfile2",
          description: "Optional site-position maps passed to GCtree's mutation annotation (`--positionmapfile` / `--positionmapfile2`); the `2` variant is for the second chain in paired-chain workflows.",
        },
        {
          role: "isotype_mapfile",
          description: "Required to apply isotype annotation. Maps each observed sequence ID to its isotype; consumed by the `gctree isotype` utility when the Apply isotype option is on.",
        },
        {
          role: "idmapfile_isotype",
          description: "Optional idmap used specifically for isotype annotation. If omitted, the run falls back to `idmapfile`, and then to the idmap GCtree generates internally.",
        },
      ],
    },
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
