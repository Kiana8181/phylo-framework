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

export type RunStatus = {
  status: "PENDING" | "RUNNING" | "DONE" | "ERROR";
  progress?: number;
  message?: string;
};

export type FigurePayload = {
  png_base64?: string[];
} | null;

export type RunResult = {
  ok: boolean;
  trees: string[];
  clones: any;
  stats: any;
  annotations: Array<Array<Record<string, any>> | null>;
  figures: FigurePayload;
  warnings?: string[];
  render?: string | null;
};
