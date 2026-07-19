// Sequence-Trace focus + context (Phase 5). Pure and unit-testable. Given the
// set of matched node ids, compute the root→match path and each match's subtree,
// and derive a RENDER-ONLY collapse set that reveals the path while collapsing the
// off-path siblings. The user's own collapse set is never mutated — so clearing
// the search restores it by construction.

import type { TreeModel } from "./types";

export type TraceResult = {
  /** Union of every match's root→match chain (inclusive). */
  pathIds: Set<string>;
  /** Union of every match's descendants (inclusive of the match). */
  subtreeIds: Set<string>;
};

export function computeTrace(model: TreeModel, matchIds: ReadonlySet<string>): TraceResult {
  const pathIds = new Set<string>();
  const subtreeIds = new Set<string>();

  for (const id of matchIds) {
    if (!model.nodes.has(id)) continue;

    // Root → match chain via parentId (guard against cycles just in case).
    let cur: string | null = id;
    while (cur != null && !pathIds.has(cur)) {
      pathIds.add(cur);
      cur = model.nodes.get(cur)?.parentId ?? null;
    }

    // The match's subtree (descendants, inclusive).
    const stack = [id];
    while (stack.length) {
      const node = model.nodes.get(stack.pop()!);
      if (!node || subtreeIds.has(node.id)) continue;
      subtreeIds.add(node.id);
      for (const childId of node.childIds) stack.push(childId);
    }
  }

  return { pathIds, subtreeIds };
}

/**
 * Layer the trace over the user's collapse set: force-expand the path (a match
 * must never hide inside a triangle) and collapse the off-path siblings (internal
 * children of a path node that fall outside path ∪ subtree). Returns a NEW set;
 * the passed-in `userCollapsed` is not modified.
 */
export function deriveTraceCollapsed(
  model: TreeModel,
  userCollapsed: ReadonlySet<string>,
  pathIds: ReadonlySet<string>,
  subtreeIds: ReadonlySet<string>,
): Set<string> {
  const result = new Set(userCollapsed);

  // Force-expand every node on the path.
  for (const id of pathIds) result.delete(id);

  // Collapse off-path siblings (context reduction).
  for (const id of pathIds) {
    const node = model.nodes.get(id);
    if (!node) continue;
    for (const childId of node.childIds) {
      if (pathIds.has(childId) || subtreeIds.has(childId)) continue;
      const child = model.nodes.get(childId);
      if (child && child.childIds.length > 0) result.add(childId);
    }
  }

  return result;
}
