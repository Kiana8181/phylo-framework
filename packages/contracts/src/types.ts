export type MethodInfo = { id: string; name: string; version: string };

export type MethodSpec = {
  id: string;
  name: string;
  version: string;
  accepts: string[];
  paramSchema: any;
  uiHints?: Record<string, any>;
};

export type CreateRunResponse = { run_id: string };

export type RunParams = Record<string, unknown>;

export type RunDatasetMeta = {
  dataset_name?: string | null;
  dataset_files?: string[];
};

export type RunSummary = {
  id: string;
  method_id: string;
  status: string;
  progress?: number;
  message?: string | null;
  params?: RunParams;
  dataset_name?: string | null;
  dataset_files?: string[];
  created_at: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type FileSummary = {
  id: string;
  original_filename: string;
  file_size: number;
  mime_type?: string | null;
  uploaded_at: string | null;
  run_id: string | null;
  storage_url?: string | null;
};

export type FilesListResponse = {
  files: FileSummary[];
  total_bytes_used: number;
  quota_bytes: number;
};

export type RunStatus = {
  run_id?: string;
  status: "PENDING" | "RUNNING" | "DONE" | "ERROR" | "QUEUED" | "CANCELLED";
  progress?: number;
  message?: string;
  method_id?: string;
  params?: RunParams;
  dataset_name?: string | null;
  dataset_files?: string[];
  started_at?: string | null;
  finished_at?: string | null;
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
};

export type FigurePayload = {
  phylogeny?: string[];
  [key: string]: Array<string | null> | undefined;
} | null;

export type TreeServiceImage = {
  mime: string;
  base64: string;
};

export type TreeNodeAttrs = {
  sequence_id?: string;
  abundance?: number;
  tooltip?: string;
  [key: string]: any;
};

export type LineagePlotNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  isLeaf: boolean;
  parentId?: string;
  abundance?: number;
};

export type LineagePlotEdge = {
  source: string;
  target: string;
};

export type LineagePlot = {
  format: "lineage-plot-v1";
  nodes: LineagePlotNode[];
  edges: LineagePlotEdge[];
  meta?: {
    rootId?: string;
    germlineLabel?: string;
    width?: number;
    height?: number;
    normalizedNewick?: string;
  };
};

export type RunTree = {
  id: string;
  newick: string;
  original_newick?: string;
  clone_id?: string;
  has_lineage_plot: boolean;
  has_service_image: boolean;
  visualizations?: {
    service_image?: TreeServiceImage;
  };
  node_attributes?: Record<string, TreeNodeAttrs>;
  label_to_sequence_id?: Record<string, string>;
  lineage_plot?: LineagePlot;
};

export type RunTreeListItem = {
  treeId: string;
  treeIndex: number;
  hasLineagePlot: boolean;
  hasServiceImage: boolean;
  cloneId?: string | null;
};

export type RunTreesListResponse = {
  trees: RunTreeListItem[];
};

export type RunTreePayload = {
  treeId: string;
  newick: string;
  original_newick?: string | null;
  node_attributes?: Record<string, TreeNodeAttrs> | null;
  lineage_plot?: LineagePlot | null;
  label_to_sequence_id?: Record<string, string> | null;
  service_image?: TreeServiceImage | null;
};

export type RunLogEntry = {
  step?: string;
  ok?: boolean;
  cmd?: string;
  out?: string;
};

export type RunWarning =
  | string
  | {
      code: string;
      message: string;
      treeId?: string;
      details?: any;
    };

export type RunOutputTable = {
  filename: string;
  format: string;
  columns: string[];
  rows: Array<Record<string, any>>;
  total_rows?: number;
  truncated?: boolean;
  [key: string]: any;
};

export type RunTables = {
  repertoire_two_levels_info?: RunOutputTable;
  [key: string]: any;
};

export type RunProvenance = {
  clonotype_submodule?: {
    tag?: string | null;
    commit?: string | null;
    ref?: string | null;
    [key: string]: any;
  };
  muscle?: {
    major?: number | null;
    version_raw?: string | null;
    [key: string]: any;
  };
  container?: {
    image_ref?: string | null;
    image_digest?: string | null;
    [key: string]: any;
  };
  [key: string]: any;
};

export type BrepPhyloRowDiagnostic = {
  row_index: number;
  sequence_id?: string | null;
  clone_id?: string | null;
  reason?: string;
  label?: string | null;
};

export type BrepPhyloMixedGermlineClone = {
  clone_id: string;
  distinct_germlines: string[];
};

export type BrepPhyloDistanceFromGermline = {
  clone_id: string;
  sequence_id: string;
  distance?: number | null;
};

export type BrepPhyloCsrEvent = {
  clone_id: string;
  from_isotype?: string | null;
  to_isotype?: string | null;
  distance_from_germline?: number | null;
  valid?: boolean | null;
};

export type BrepPhyloArborescenceEdge = {
  startID?: string | number;
  endID?: string | number;
  weight?: number | null;
  startLabel?: string;
  endLabel?: string;
};

export type BrepPhyloArborescence = {
  clone_id: string;
  edges: BrepPhyloArborescenceEdge[];
};

export type BrepPhyloIsotypeSwitchValidity = {
  clone_id: string;
  sequence_id_from?: string;
  sequence_id_to?: string;
  from_isotype?: string;
  to_isotype?: string;
  valid?: boolean | null;
};

export type BrepPhyloPerCloneStatus = {
  clone_id: string;
  n_seqs: number;
  analyzed: boolean;
  status?: "analyzed" | "skipped" | "failed";
  skip_reason?: string | null;
};

export type BrepPhyloSkippedClone = {
  clone_id: string;
  reason: string;
};

export type BrepPhyloBatchSummary = {
  clones_analyzed?: number;
  clones_skipped?: number;
  csr_total?: number;
  distance_rows?: number;
};

export type BrepPhyloAnalysis = {
  batch_summary?: BrepPhyloBatchSummary;
  distance_from_germline?: BrepPhyloDistanceFromGermline[];
  csr_events?: BrepPhyloCsrEvent[];
  csr_summary?: Record<string, unknown>[];
  csr_summary_fallback?: Record<string, number>;
  arborescence?: BrepPhyloArborescence[];
  isotype_switch_validity?: BrepPhyloIsotypeSwitchValidity[];
  per_clone_status?: BrepPhyloPerCloneStatus[];
  skipped_clones?: BrepPhyloSkippedClone[];
};

export type BrepPhyloDiagnostics = {
  dropped_rows?: BrepPhyloRowDiagnostic[];
  rejected_rows?: BrepPhyloRowDiagnostic[];
  unmapped_input_rows?: BrepPhyloRowDiagnostic[];
  unmapped_tree_tips?: Array<{ clone_id: string; final_tip_label: string }>;
  mixed_germline_clones?: BrepPhyloMixedGermlineClone[];
  latex_available?: boolean | null;
};

export type BrepPhyloArtifactZip = {
  clone_bundle_zip?: string | null;
};

export type BrepPhyloStats = {
  method?: string;
  tree_type_requested?: string | null;
  tree_type?: string;
  input_sequence_mode?: string;
  species?: string;
  species_effective?: string | null;
  algorithm?: string | null;
  plot_type?: string;
  plot_format?: string;
  min_clone_size?: number;
  gather_plots?: boolean;
  enable_csr_analysis?: boolean;
  n_clones?: number;
  n_trees?: number;
  tree_inference_seconds?: number | null;
  analysis_seconds?: number | null;
  isotype_column?: string | null;
  label_column?: string | null;
  sequence_column?: string;
  clone_id_column?: string;
  germline_id_column?: string;
  which_clones?: string[] | null;
  ignore_clones?: string[] | null;
  total_seqs?: number;
};

/** Optional tip-colouring metadata (e.g. Dowser); not used by BrepPhylo after colour controls were removed. */
export type TreeTipColorStats = {
  tip_color_by?: string | null;
  tip_states_capped?: boolean;
  unknown_value?: string;
};

export type DowserAnalysisMode =
  | "tree_only"
  | "tree_with_internal_sequences"
  | "discrete_trait_analysis"
  | "time_evolution";

export type DowserTreeBuild = "pratchet" | "pml" | "dnapars" | "dnaml" | "igphyml" | "raxml";

export type DowserTipLabelMap = {
  sequence_id: string;
  display_label: string;
};

export type DowserNode = {
  clone_id?: string;
  node?: number;
  node_id?: string;
  sequence?: string;
  sequence_alignment?: string;
  locus?: string;
  is_internal?: boolean;
  is_observed?: boolean;
  parent?: string;
  children?: string[];
  branch_length?: number;
  trait_state?: string;
};

export type DowserTreeDetail = {
  clone_id?: string;
  canonical_newick?: string;
  display_newick?: string | null;
  lineage_newick?: string | null;
  tip_label_map?: DowserTipLabelMap[];
  nodes?: DowserNode[];
  all_sequences?: Array<Record<string, unknown>>;
  show_node_numbers?: boolean;
};

export type DowserDtaResult = {
  trait_field?: string;
  trait_model?: string;
  permutations?: number;
  tip_switch?: number;
  switches?: Array<Record<string, unknown>>;
  ps?: { summary?: Array<Record<string, unknown>>; raw?: Array<Record<string, unknown>> };
  sp?: { summary?: Array<Record<string, unknown>>; raw?: Array<Record<string, unknown>> };
  sc?: { summary?: Array<Record<string, unknown>>; raw?: Array<Record<string, unknown>> };
  interpretation_warning?: string;
};

export type DowserTimeEvolution = {
  time_field?: string;
  permutations?: number;
  results?: Array<Record<string, unknown>>;
  plots?: unknown[];
  interpretation_warning?: string;
};

export type DowserIgPhyML = {
  exec?: string | null;
  motifs?: string | null;
  partition_model?: string;
  parameters?: Record<string, unknown>;
  warnings?: string[];
};

export type DowserChainQc = {
  chain_mode?: string;
  n_input_rows?: number;
  n_after_resolve?: number;
  n_dropped?: number;
  heavy_locus?: string;
  light_loci?: string[];
};

export type DowserArtifact = {
  name?: string;
  path?: string;
  kind?: string;
};

export type DowserInputQc = {
  n_input_rows?: number;
  n_working_rows?: number;
  n_clones_input?: number;
  n_clones_working?: number;
  n_duplicate_sequence_id?: number;
  n_excluded_trait_missing?: number;
  n_missing_sequence_alignment?: number;
  n_missing_germline_alignment?: number;
  n_length_mismatch?: number;
  excluded_records?: Array<Record<string, unknown>>;
};

export type DowserStats = TreeTipColorStats & {
  analysis_mode?: DowserAnalysisMode;
  tree_build?: DowserTreeBuild;
  canonical_ids?: string;
  n_clones?: number;
  n_trees?: number;
  total_seqs?: number;
  label_field?: string;
};

export function readTreeTipColorStats(
  stats: (BrepPhyloStats & TreeTipColorStats & DowserStats) | Record<string, unknown> | null | undefined,
): { colorBy?: string; unknownValue: string } {
  if (!stats || typeof stats !== "object") {
    return { unknownValue: "unknown" };
  }
  const s = stats as TreeTipColorStats;
  if (s.tip_states_capped) {
    return { unknownValue: s.unknown_value ?? "unknown" };
  }
  const colorBy =
    typeof s.tip_color_by === "string" && s.tip_color_by.length > 0 ? s.tip_color_by : undefined;
  return { colorBy, unknownValue: s.unknown_value ?? "unknown" };
}

export function readDowserResult(result: RunResult | Record<string, unknown> | null | undefined) {
  if (!result || typeof result !== "object") {
    return {
      treesDetail: [] as DowserTreeDetail[],
      dta: undefined as DowserDtaResult | undefined,
      timeEvolution: undefined as DowserTimeEvolution | undefined,
      igphyml: undefined as DowserIgPhyML | undefined,
      chainQc: undefined as DowserChainQc | undefined,
      inputQc: undefined as DowserInputQc | undefined,
      dataProvenance: undefined as Record<string, unknown> | undefined,
      artifacts: [] as DowserArtifact[],
      isDowser: false,
    };
  }
  const r = result as RunResult & {
    trees_detail?: DowserTreeDetail[];
    discrete_trait_analysis?: DowserDtaResult;
    time_evolution?: DowserTimeEvolution;
    igphyml?: DowserIgPhyML;
    chain_qc?: DowserChainQc;
    input_qc?: DowserInputQc;
    data_provenance?: Record<string, unknown>;
    artifacts?: DowserArtifact[];
  };
  const stats = r.stats as DowserStats | undefined;
  const isDowser = Boolean(
    stats?.analysis_mode || stats?.tree_build || r.trees_detail || r.discrete_trait_analysis,
  );
  return {
    treesDetail: r.trees_detail ?? [],
    dta: r.discrete_trait_analysis,
    timeEvolution: r.time_evolution,
    igphyml: r.igphyml,
    chainQc: r.chain_qc,
    inputQc: r.input_qc,
    dataProvenance: r.data_provenance,
    artifacts: r.artifacts ?? [],
    isDowser,
  };
}

export type RunResult = {
  ok: boolean;
  trees: Array<RunTree | string>;
  clones: { clone_id?: string[]; seqs?: number[] } | null;
  clone_catalog?: Record<string, unknown>;
  stats: BrepPhyloStats | DowserStats | Record<string, unknown>;
  node_abundances?: Array<Record<string, number>>;
  annotations?: Array<Array<Record<string, unknown>> | null>;
  analysis?: BrepPhyloAnalysis;
  diagnostics?: BrepPhyloDiagnostics;
  figures?: FigurePayload;
  tables?: RunTables;
  provenance?: RunProvenance;
  warnings?: RunWarning[];
  render?: string | null;
  logs?: RunLogEntry[];
  artifact_zip_b64?: string | BrepPhyloArtifactZip | null;
  artifact_name?: string;
  error?: string | null;
  trees_detail?: DowserTreeDetail[];
  discrete_trait_analysis?: DowserDtaResult;
  time_evolution?: DowserTimeEvolution;
  igphyml?: DowserIgPhyML;
  chain_qc?: DowserChainQc;
  input_qc?: DowserInputQc;
  data_provenance?: Record<string, unknown>;
  artifacts?: DowserArtifact[];
} & {
  run_id?: string;
  method_id?: string;
  params?: RunParams;
  dataset_name?: string | null;
  dataset_files?: string[];
  started_at?: string | null;
  finished_at?: string | null;
};
