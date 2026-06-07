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

/** Strip characters that could break Mermaid node-label syntax. */
export function sanitizeLabel(label: string): string {
  return label
    .replace(/["`<>{}|]/g, " ")
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 40);
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
  const ids = sequence.map((n) => n.id);

  const isTerminal = (s?: string | null) =>
    !!s && (TERMINAL_STAGES as readonly string[]).includes(s);
  const cancelling = stage === CANCELLING_STAGE || status === "CANCELLED";
  const errored = status === "ERROR";
  const done = status === "DONE";

  // A method may report a stage not in the canonical sequence; insert it so the
  // diagram never crashes and the active step is still visible.
  const activeStage = stage ?? null;
  if (
    activeStage &&
    !isTerminal(activeStage) &&
    activeStage !== CANCELLING_STAGE &&
    !ids.includes(activeStage)
  ) {
    const afterSubmit = ids.indexOf("SUBMITTING_METHOD_JOB");
    const insertAt = afterSubmit >= 0 ? afterSubmit + 1 : Math.max(0, sequence.length - 1);
    sequence.splice(insertAt, 0, {
      id: activeStage,
      label: humanizeStage(activeStage),
    });
    ids.splice(insertAt, 0, activeStage);
  }

  let activeIndex = activeStage ? ids.indexOf(activeStage) : -1;
  if (done) activeIndex = ids.indexOf("COMPLETED");

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
