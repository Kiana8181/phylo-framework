// Pure helpers for the run-stage flowchart. Kept separate from the React
// component so the stage-state derivation can be unit tested without a DOM.

import {
  stageSequenceForMethod,
  humanizeStage,
  TERMINAL_STAGES,
  CANCELLING_STAGE,
  type StageNode,
  type StageState,
} from "@phylo/contracts";

export type RenderNode = StageNode & { state: StageState };

/** Index of the display node that owns a backend stage id — matching either the
 *  node id directly or one of its collapse `aliases`. Returns -1 if none. */
function ownerIndex(sequence: StageNode[], stageId: string): number {
  return sequence.findIndex(
    (node) => node.id === stageId || (node.aliases?.includes(stageId) ?? false),
  );
}

/**
 * Derive the per-node state list from the real run status/stage. No timers:
 * the diagram is a pure function of persisted run data.
 */
export function computeNodes(
  methodId: string | null | undefined,
  status: string | undefined,
  stage: string | null | undefined,
): RenderNode[] {
  const sequence = [...stageSequenceForMethod(methodId)];

  const isTerminal = (s?: string | null) =>
    !!s && (TERMINAL_STAGES as readonly string[]).includes(s);
  const cancelling = stage === CANCELLING_STAGE || status === "CANCELLED";
  const errored = status === "ERROR";
  const done = status === "DONE";

  // A method may report a stage not in the canonical sequence; insert it so the
  // diagram never crashes and the active step is still visible.
  let activeStage = stage ?? null;
  // API run is RUNNING but method job still reports QUEUED before child starts.
  if (status === "RUNNING" && activeStage === "QUEUED") {
    activeStage = "RUNNING_METHOD";
  }
  if (
    activeStage &&
    !isTerminal(activeStage) &&
    activeStage !== CANCELLING_STAGE &&
    ownerIndex(sequence, activeStage) < 0
  ) {
    const afterPreparing = sequence.findIndex((n) => n.id === "PREPARING");
    const insertAt = afterPreparing >= 0 ? afterPreparing + 1 : Math.max(0, sequence.length - 1);
    sequence.splice(insertAt, 0, {
      id: activeStage,
      label: humanizeStage(activeStage),
    });
  }

  let activeIndex = activeStage ? ownerIndex(sequence, activeStage) : -1;
  if (done) activeIndex = sequence.findIndex((n) => n.id === "COMPLETED");

  const nodes: RenderNode[] = sequence.map((node, i) => {
    let state: StageState = "pending";
    if (done) {
      state = "done";
    } else if (activeIndex < 0) {
      state = "pending";
    } else if (i < activeIndex) {
      state = "done";
    } else if (i === activeIndex) {
      if (errored) state = "error";
      else if (cancelling) state = "cancelled";
      else state = "active";
    }
    return { ...node, state };
  });

  // Append an explicit terminal node so failure/cancellation never looks like
  // successful completion.
  if (errored && !nodes.some((n) => n.state === "error")) {
    nodes.push({ id: "ERROR", label: "Error", state: "error" });
  } else if (cancelling && !nodes.some((n) => n.state === "cancelled")) {
    nodes.push({ id: "CANCELLED", label: "Cancelled", state: "cancelled" });
  }

  return nodes;
}
