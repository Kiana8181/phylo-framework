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

export type RunResult = {
  ok: boolean;
  trees: Array<RunTree | string>;
  clones: any;
  stats: any;
  annotations?: Array<Array<Record<string, any>> | null>;
  figures?: FigurePayload;
  warnings?: RunWarning[];
  render?: string | null;
  logs?: RunLogEntry[];
  artifact_zip_b64?: any;
  artifact_name?: string;
} & {
  run_id?: string;
  method_id?: string;
  params?: RunParams;
  dataset_name?: string | null;
  dataset_files?: string[];
};
