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

export type RunSummary = {
  id: string;
  method_id: string;
  status: string;
  progress?: number;
  message?: string | null;
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
  status: "PENDING" | "RUNNING" | "DONE" | "ERROR";
  progress?: number;
  message?: string;
};

export type FigurePayload = {
  phylogeny?: string[];
} | null;

export type RunLogEntry = {
  step?: string;
  ok?: boolean;
  cmd?: string;
  out?: string;
};

export type RunResult = {
  ok: boolean;
  trees: string[];
  clones: any;
  stats: any;
  annotations: Array<Array<Record<string, any>> | null>;
  figures: FigurePayload;
  warnings?: string[];
  render?: string | null;
  logs?: RunLogEntry[];
  artifact_zip_b64?: any;
  artifact_name?: string;
};
