// Collapse state: a Set<string> of collapsed node ids. Pure and unit-testable;
// React state lives in TreeView. Collapsing NEVER mutates the TreeModel — only
// this set changes (spec §3.1). `layoutTree` already consumes the set.

import { AUTO_COLLAPSE_MIN_NODES, DEFAULT_COLLAPSE_DEPTH } from "./constants";
import type { TreeModel, TreeNodeModel } from "./types";

/**
 * Default collapse set for a freshly-loaded model. Gated by node count so small
 * trees are NOT auto-collapsed (that would hide most of a small tree and make
 * the common case worse). When `AUTO_COLLAPSE_MIN_NODES === 0` the gate is off
 * and depth-3 collapse always applies.
 */
export function defaultCollapsed(model: TreeModel): Set<string> {
  const collapsed = new Set<string>();
  if (model.nodes.size <= AUTO_COLLAPSE_MIN_NODES) return collapsed;
  for (const id of model.order) {
    const node = model.nodes.get(id);
    if (!node) continue;
    if (node.depth >= DEFAULT_COLLAPSE_DEPTH && node.childIds.length > 0) {
      collapsed.add(id);
    }
  }
  return collapsed;
}

/** Collapse every internal node except the root. */
export function collapseAll(model: TreeModel): Set<string> {
  const collapsed = new Set<string>();
  for (const id of model.order) {
    if (id === model.rootId) continue;
    const node = model.nodes.get(id);
    if (node && node.childIds.length > 0) collapsed.add(id);
  }
  return collapsed;
}

/** Fully expand — clears the set. */
export function expandAll(): Set<string> {
  return new Set<string>();
}

/** Toggle one node's collapsed state, returning a new set (immutable update). */
export function toggleCollapse(collapsed: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(collapsed);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export type ColorKey = { key: string; color: string };

/**
 * Summarise the colours of a collapsed node's subtree (its descendants are not
 * in the layout, so we walk the model). Returns the modal (most frequent) value's
 * colour and whether more than one distinct value is present — used to fill the
 * collapsed glyph and flag it as an aggregate (striped). `keyOf` returns null for
 * nodes with no value (e.g. germline / unknown), which are ignored.
 */
export function subtreeColorSummary(
  model: TreeModel,
  id: string,
  keyOf: (node: TreeNodeModel) => ColorKey | null,
): { modalColor: string; multiple: boolean } | null {
  const counts = new Map<string, { color: string; n: number }>();
  const stack: string[] = [id];
  while (stack.length) {
    const cur = model.nodes.get(stack.pop()!);
    if (!cur) continue;
    const ck = keyOf(cur);
    if (ck) {
      const entry = counts.get(ck.key);
      if (entry) entry.n += 1;
      else counts.set(ck.key, { color: ck.color, n: 1 });
    }
    for (const child of cur.childIds) stack.push(child);
  }
  if (counts.size === 0) return null;
  let modalColor = "";
  let best = -1;
  for (const { color, n } of counts.values()) {
    if (n > best) {
      best = n;
      modalColor = color;
    }
  }
  return { modalColor, multiple: counts.size > 1 };
}
