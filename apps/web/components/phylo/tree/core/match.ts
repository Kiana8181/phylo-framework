// Sequence-Trace identifier matching. Pure and unit-testable.
//
// The query is matched EXACTLY (whole-string) against a node's identifier
// fields, so `IGH001` does not match `IGH0011`. Trimming and case-folding are
// the only forgiving allowances — everything else is strict equality.
//
// Only identifier fields are compared. Composite multi-line "key: value"
// attribute text is deliberately not matched: a whole-string equality test
// against such a block could never succeed.

import { resolveNodeDisplayLabel } from "./lineageDisplay";
import { resolveTipDisplayLabel } from "./phyloDisplay";
import type { TreeModel } from "./types";

export type MatchOptions = {
  /** Lineage view matches any node; phylogeny view matches leaves only. */
  isLineage: boolean;
  displayIdField?: string | null;
  showInternalNodes?: boolean;
  showNodeNumbers?: boolean;
};

/** Normalize a query or candidate to its comparison form. */
function norm(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

/**
 * Ids of nodes whose identifier equals `query`.
 *
 * Compared per node: the raw Newick label, the resolved display label (which is
 * the visible identifier when `displayIdField` selects another field), and the
 * `sequence_id` attribute (tested explicitly, because when `displayIdField`
 * points elsewhere the resolved display label will not return it).
 *
 * Returns an empty set for an empty query, and for a query equal to no
 * identifier — in both cases the caller shows nothing for that tree.
 */
export function computeMatchIds(
  model: TreeModel,
  query: string,
  opts: MatchOptions,
): Set<string> {
  const ids = new Set<string>();
  const needle = norm(query);
  if (!needle) return ids;

  const { isLineage, displayIdField, showInternalNodes = false, showNodeNumbers = false } = opts;

  for (const [id, node] of model.nodes) {
    if (!isLineage && !node.isLeaf) continue;

    const displayLabel = isLineage
      ? resolveNodeDisplayLabel(node, displayIdField, showInternalNodes, showNodeNumbers)
      : resolveTipDisplayLabel(node.label, node.attrs, displayIdField ?? null);

    if (
      norm(node.label) === needle ||
      norm(displayLabel) === needle ||
      norm(node.attrs?.sequence_id) === needle
    ) {
      ids.add(id);
    }
  }

  return ids;
}
