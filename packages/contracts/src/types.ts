// Shared domain types mirrored across apps.
// Keep minimal and stable.

export type MethodInfo = { id: string; name: string; version: string };

export type MethodSpec = {
  id: string;
  name: string;
  version: string;
  accepts: string[];
  paramSchema: any; // JSON Schema object (rendered by FormBuilder)
  uiHints?: Record<string, any>;
};

export type CreateRunResponse = { run_id: string };

export type RunStatus = {
  status: "PENDING" | "RUNNING" | "DONE" | "ERROR";
  progress?: number;
  message?: string;
};

export type RunResult = {
  ok: boolean;
  trees: string[];
  clones: any;
  stats: any;
  annotations: any;
  figures: any;
  render?: string | null;
};
