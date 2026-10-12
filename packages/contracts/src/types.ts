export type MethodInfo = {
  id: string;
  name: string;
  version: string;
  tagline?: string;
  category?: string;
  summary?: string;
  capabilities?: string[];
  inputFormats?: string[];
  externalDocUrl?: string;
  externalDocLabel?: string;
};

export type MethodSpec = {
  id: string;
  name: string;
  version: string;
  accepts: string[];
  paramSchema: any;
  uiHints?: Record<string, any>;
};

export type CreateRunResponse = {
  run_id: string;
  /** True when the run did NOT become the active turn (it is waiting in the personal queue). */
  queued: boolean;
  /** 1-based position within the user's personal queue, or null when it became the active turn. */
  queue_position: number | null;
};

/** Live payload for the run-queue dashboard (non-terminal runs only). */
export type DashboardRunsResponse = {
  /** The active-turn run (RUNNING or promoted-QUEUED), or null when the user has none. */
  active: RunStatus | null;
  /** The personal queue behind the active turn, FIFO (dispatch_seq NULL). */
  queue: RunSummary[];
  limits: {
    max_queued: number;
    queued_count: number;
    can_add: boolean;
  };
};

/** Use of one rolling 60-minute limit. */
export type RunQuotaWindow = {
  /** Null when the limit is switched off. */
  limit: number | null;
  used: number;
  remaining: number | null;
  window_seconds: number;
  /** Set only while the limit is reached: when one more run becomes possible (ISO 8601). */
  reset_at: string | null;
  retry_after_seconds: number | null;
};

/** Why a new run would be refused right now. */
export type RunLimitCode = "RUN_QUOTA_EXCEEDED" | "RUN_SUBMISSION_LIMIT_EXCEEDED" | "QUEUE_FULL";

/** GET /runs/quota: where the user stands against the limits on creating runs.
 *  POST /runs applies the same rules. */
export type RunQuotaResponse = {
  can_submit: boolean;
  blocked_by: RunLimitCode | null;
  /** Explanation for the user while blocked. */
  message: string | null;
  /** Seconds until submitting can work again; null when a run has to finish first (full queue). */
  retry_after_seconds: number | null;
  /** Runs that count against the hourly quota (runs that never started do not). */
  hourly: RunQuotaWindow;
  /** Every run created in the window, including cancelled ones. */
  submissions: RunQuotaWindow;
  queue: {
    max_queued: number;
    queued_count: number;
    unfinished: number;
    can_add: boolean;
  };
  server_time: string;
};

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
  stage?: string | null;
  params?: RunParams;
  dataset_name?: string | null;
  dataset_files?: string[];
  created_at: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  /** When the stored results (files, trees, logs) are removed; null when they are kept for ever
   *  or the run has not ended. ISO 8601. */
  expires_at?: string | null;
  /** True once the results have been removed. The run itself stays as history. */
  results_expired?: boolean;
  results_expired_at?: string | null;
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
  /** High-level stage identifier (e.g. STAGING_INPUT, BUILDING_TREES, CANCELLING). */
  stage?: string | null;
  /** User-facing message tied to the current stage. */
  stage_message?: string | null;
  /** True once cancellation has been requested (worker is winding down). */
  cancel_requested?: boolean;
  method_id?: string;
  params?: RunParams;
  dataset_name?: string | null;
  dataset_files?: string[];
  input_file_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
  /** When the stored results (files, trees, logs) are removed; null when they are kept for ever
   *  or the run has not ended. ISO 8601. */
  expires_at?: string | null;
  /** True once the results have been removed. The run itself stays as history. */
  results_expired?: boolean;
  results_expired_at?: string | null;
};

/** GET /uploads/limits: what the user may still upload. */
export type UploadLimitsResponse = {
  /** Largest single file accepted. */
  max_upload_bytes: number;
  quota_bytes: number;
  used_bytes: number;
  remaining_bytes: number;
};

export type UploadInitResponse = {
  upload_id: string;
  content_url: string;
  status: string;
};

export type UploadedFileResponse = {
  upload_id: string;
  file_id: string;
  original_filename: string;
  file_size: number;
  mime_type?: string | null;
  storage_url?: string | null;
};

export type UploadSessionStatus = "INITIATED" | "UPLOADING" | "COMPLETED" | "CANCELLED" | "ERROR";

export type ArtifactKind = "image" | "newick" | "table" | "fasta" | "json" | "log" | "zip" | "other";

/** A generated run output stored in object storage. Binaries are fetched
 *  lazily via download_url / preview_url — never embedded as base64. */
export type RunArtifact = {
  id: string;
  filename: string;
  content_type?: string | null;
  size_bytes: number;
  checksum_sha256?: string | null;
  artifact_kind: ArtifactKind;
  artifact_role?: string | null;
  is_previewable: boolean;
  tree_id?: string | null;
  download_url: string;
  preview_url?: string | null;
};

export type RunArtifactsResponse = {
  artifacts: RunArtifact[];
};

/** Lightweight dataset metadata attached to a run (history-safe; no binary). */
export type RunDatasetDescriptor = {
  id: string;
  original_filename: string;
  file_size?: number | null;
  checksum_sha256?: string | null;
  mime_type?: string | null;
  uploaded_at?: string | null;
  storage_state: "active" | "deleted";
  is_deleted: boolean;
  deleted_at?: string | null;
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
  /** Artifact id of this tree's method-rendered image (served via preview_url). */
  image_artifact_id?: string | null;
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
  /**
   * Download-only Newick relabeled with the user's original sequence_ids
   * (gctree only; null for other methods and legacy runs). Never parsed for
   * layout — used solely for the "Newick (original IDs)" download.
   */
  display_newick?: string | null;
  /** Artifact id of this tree's method-rendered image (served via preview_url). */
  image_artifact_id?: string | null;
};

export type RunLogEntry = {
  step?: string;
  ok?: boolean;
  cmd?: string;
  out?: string;
};

export type RunErrorDetails = {
  ok?: boolean;
  logs?: RunLogEntry[];
  error?: string | null;
  artifacts?: Array<Record<string, unknown>>;
  manifest_version?: number;
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

/** Build-time identity of the framework itself. */
export type VersionInfoFramework = {
  version?: string | null;
  git_commit?: string | null;
  git_branch?: string | null;
  git_dirty?: boolean | null;
};

/** Build-time identity of the one method service that ran. */
export type VersionInfoService = {
  image_name?: string | null;
  image_digest?: string | null;
  base_image?: string | null;
  /** Pins declared as `ARG` in the service Dockerfile, e.g. BREPPHYLO_COMMIT. */
  build_args?: Record<string, string>;
  /** Pinned tool versions parsed from the service's build definition. */
  tool_versions?: Record<string, string>;
};

/**
 * Environment identity recorded with a run.
 *
 * Written by `scripts/generate-version-info.mjs` at build/deploy time and
 * copied into the result when the run is persisted. Optional throughout: runs
 * recorded before this feature carry no `version_info`, and any field the
 * deployment could not determine is `null` with a reason in `unavailable`.
 */
export type VersionInfo = {
  schema_version?: number | null;
  method_id?: string;
  captured_at?: string | null;
  framework?: VersionInfoFramework | null;
  service?: VersionInfoService | null;
  /** What the service reported about itself while running. */
  service_reported?: RunProvenance | null;
  reference_data?: string | null;
  /** Field path -> why it could not be captured. */
  unavailable?: Record<string, string>;
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

function asCount(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.length;
  return undefined;
}

function normalizeDowserInputQc(raw: Record<string, unknown> | null | undefined): DowserInputQc | undefined {
  if (!raw || typeof raw !== "object") return undefined;

  const nInputRows = asCount(raw.n_input_rows ?? raw.n_rows_original);
  const nWorkingRows = asCount(
    raw.n_working_rows ?? raw.n_rows_after_trait_exclusion ?? raw.n_rows_after_derived_fields,
  );
  const nClonesInput = asCount(raw.n_clones_input ?? raw.n_clones_original);
  const nClonesWorking = asCount(raw.n_clones_working ?? raw.n_clones_after_trait_exclusion);
  const nExcludedTraitMissing = asCount(raw.n_excluded_trait_missing ?? raw.excluded_missing_trait);
  const nLengthMismatch = asCount(raw.n_length_mismatch ?? raw.length_mismatch);
  const nDuplicateSequenceId = asCount(raw.n_duplicate_sequence_id ?? raw.duplicate_sequence_ids);

  const normalized: DowserInputQc = {};
  if (nInputRows != null) normalized.n_input_rows = nInputRows;
  if (nWorkingRows != null) normalized.n_working_rows = nWorkingRows;
  if (nClonesInput != null) normalized.n_clones_input = nClonesInput;
  if (nClonesWorking != null) normalized.n_clones_working = nClonesWorking;
  if (nExcludedTraitMissing != null) normalized.n_excluded_trait_missing = nExcludedTraitMissing;
  if (nLengthMismatch != null) normalized.n_length_mismatch = nLengthMismatch;
  if (nDuplicateSequenceId != null) normalized.n_duplicate_sequence_id = nDuplicateSequenceId;

  const nMissingSeq = asCount(raw.n_missing_sequence_alignment);
  if (nMissingSeq != null) normalized.n_missing_sequence_alignment = nMissingSeq;
  const nMissingGerm = asCount(raw.n_missing_germline_alignment);
  if (nMissingGerm != null) normalized.n_missing_germline_alignment = nMissingGerm;

  return Object.keys(normalized).length ? normalized : undefined;
}

export type DowserStats = TreeTipColorStats & {
  analysis_mode?: DowserAnalysisMode;
  tree_build?: DowserTreeBuild;
  canonical_ids?: string;
  n_clones?: number;
  n_trees?: number;
  total_seqs?: number;
  label_field?: string;
  tip_size_by?: string;
};

export function readTreeTipSizeBy(
  stats: (BrepPhyloStats & TreeTipColorStats & DowserStats) | Record<string, unknown> | null | undefined,
): string | undefined {
  if (!stats || typeof stats !== "object") return undefined;
  const field = (stats as DowserStats).tip_size_by;
  return typeof field === "string" && field.length > 0 ? field : undefined;
}

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
    inputQc: normalizeDowserInputQc(r.input_qc as Record<string, unknown> | undefined),
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
  tables?: RunTables;
  provenance?: RunProvenance;
  version_info?: VersionInfo;
  warnings?: RunWarning[];
  logs?: RunLogEntry[];
  error?: string | RunErrorDetails | null;
  trees_detail?: DowserTreeDetail[];
  discrete_trait_analysis?: DowserDtaResult;
  time_evolution?: DowserTimeEvolution;
  igphyml?: DowserIgPhyML;
  chain_qc?: DowserChainQc;
  input_qc?: DowserInputQc;
  data_provenance?: Record<string, unknown>;
} & {
  run_id?: string;
  method_id?: string;
  params?: RunParams;
  dataset_name?: string | null;
  dataset_files?: string[];
  input_file_id?: string | null;
  dataset?: RunDatasetDescriptor | null;
  artifact_count?: number;
  started_at?: string | null;
  finished_at?: string | null;
  /** When the stored results (files, trees, logs) are removed; null when they are kept for ever
   *  or the run has not ended. ISO 8601. */
  expires_at?: string | null;
  /** True once the results have been removed. The run itself stays as history. */
  results_expired?: boolean;
  results_expired_at?: string | null;
};
