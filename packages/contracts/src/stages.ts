// Canonical per-method run-stage sequences used to render the run-stage
// flowchart. Stage identifiers match the backend stage strings; labels are
// human-readable. Unknown/extra stages are tolerated by the UI.

export type StageState = "pending" | "active" | "done" | "error" | "cancelled";

export type StageNode = {
  /** Backend stage identifier (e.g. "BUILDING_TREES"). */
  id: string;
  /** Human-readable label (e.g. "Building trees"). */
  label: string;
};

// Outer orchestration stages owned by the API/worker (common to all methods).
const QUEUED: StageNode = { id: "QUEUED", label: "Queued" };
const STAGING_INPUT: StageNode = { id: "STAGING_INPUT", label: "Staging input" };
const PREPROCESSING: StageNode = { id: "PREPROCESSING", label: "Preprocessing" };
const SUBMITTING_METHOD_JOB: StageNode = { id: "SUBMITTING_METHOD_JOB", label: "Submitting job" };
const RUNNING_METHOD: StageNode = { id: "RUNNING_METHOD", label: "Running method" };
const FETCHING_RESULT: StageNode = { id: "FETCHING_RESULT", label: "Fetching result" };
const COMPLETED: StageNode = { id: "COMPLETED", label: "Completed" };

// Terminal non-success stages (handled separately by the flowchart).
export const TERMINAL_STAGES = ["COMPLETED", "CANCELLED", "ERROR"] as const;
export const CANCELLING_STAGE = "CANCELLING";

// Common outer sequence (default for any method without specific metadata).
export const COMMON_STAGES: StageNode[] = [
  QUEUED,
  STAGING_INPUT,
  PREPROCESSING,
  SUBMITTING_METHOD_JOB,
  RUNNING_METHOD,
  FETCHING_RESULT,
  COMPLETED,
];

// R-based services (Dowser, BrepPhylo) report a coarse RUNNING_METHOD stage,
// but the diagram shows the meaningful method steps when available.
const R_METHOD_STAGES: StageNode[] = [
  QUEUED,
  STAGING_INPUT,
  PREPROCESSING,
  SUBMITTING_METHOD_JOB,
  { id: "BUILDING_TREES", label: "Building trees" },
  { id: "RUNNING_ANALYSIS", label: "Running analysis" },
  { id: "RENDERING_EXPORTS", label: "Rendering exports" },
  FETCHING_RESULT,
  COMPLETED,
];

// Python services (GCtree, ClonalTree).
const PYTHON_METHOD_STAGES: StageNode[] = [
  QUEUED,
  STAGING_INPUT,
  PREPROCESSING,
  SUBMITTING_METHOD_JOB,
  { id: "BUILDING_TREES", label: "Building trees" },
  { id: "RENDERING_EXPORTS", label: "Rendering exports" },
  FETCHING_RESULT,
  COMPLETED,
];

export const METHOD_STAGE_SEQUENCES: Record<string, StageNode[]> = {
  dowser: R_METHOD_STAGES,
  brepphylo: R_METHOD_STAGES,
  gctree: PYTHON_METHOD_STAGES,
  clonaltree: PYTHON_METHOD_STAGES,
};

export function stageSequenceForMethod(methodId?: string | null): StageNode[] {
  if (methodId && METHOD_STAGE_SEQUENCES[methodId]) {
    return METHOD_STAGE_SEQUENCES[methodId];
  }
  return COMMON_STAGES;
}

export function humanizeStage(stageId?: string | null): string {
  if (!stageId) return "";
  const known: Record<string, string> = {
    QUEUED: "Queued",
    STAGING_INPUT: "Staging input",
    PREPROCESSING: "Preprocessing",
    SUBMITTING_METHOD_JOB: "Submitting job",
    RUNNING_METHOD: "Running method",
    VALIDATING_REQUEST: "Validating request",
    READING_INPUT: "Reading input",
    PREPARING_INPUT: "Preparing input",
    FORMATTING_CLONES: "Formatting clones",
    BUILDING_TREES: "Building trees",
    RUNNING_ANALYSIS: "Running analysis",
    RENDERING_EXPORTS: "Rendering exports",
    FETCHING_RESULT: "Fetching result",
    COMPLETED: "Completed",
    CANCELLING: "Cancelling",
    CANCELLED: "Cancelled",
    ERROR: "Error",
  };
  if (known[stageId]) return known[stageId];
  // Fallback: turn SNAKE_CASE into "Snake case".
  const lower = stageId.replace(/_/g, " ").toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}
