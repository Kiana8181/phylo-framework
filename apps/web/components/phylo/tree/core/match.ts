// Sequence-Trace identifier matching. Pure and unit-testable.
//
// The query is matched EXACTLY against a node's identifier fields, so `IGH001`
// does not match `IGH0011`. Trimming and case-folding are the only forgiving
// allowances — everything else is strict equality.
//
// Pipe-delimited identifiers (`id1|id2|id3`) are treated as a list of aliases:
// the query matches either the whole identifier or any one of its `|`-separated
// parts. Partial parts still don't match (`id` does not find `id1|id2`).
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
 * Whether `candidate` equals `needle` as a whole, or in one of its
 * `|`-separated parts. Both are already normalized by the caller.
 */
function matches(candidate: string, needle: string): boolean {
  if (!candidate) return false;
  if (candidate === needle) return true;
  if (!candidate.includes("|")) return false;
  return candidate.split("|").some((part) => part.trim() === needle);
}

/**
 * Ids of nodes whose identifier equals `query`.
 *
 * Compared per node: the raw Newick label, the resolved display label (which is
 * the visible identifier when `displayIdField` selects another field), and the
 * `sequence_id` attribute (tested explicitly, because when `displayIdField`
 * points elsewhere the resolved display label will not return it). Each is
 * compared whole and by its `|`-separated parts.
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
      matches(norm(node.label), needle) ||
      matches(norm(displayLabel), needle) ||
      matches(norm(node.attrs?.sequence_id), needle)
    ) {
      ids.add(id);
    }
  }

  return ids;
}
