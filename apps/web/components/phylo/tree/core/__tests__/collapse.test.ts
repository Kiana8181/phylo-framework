import { describe, it, expect } from "vitest";
import type { LineagePlot } from "@phylo/contracts";
import { fromLineagePlot } from "../fromLineagePlot";
import { defaultCollapsed, collapseAll, expandAll, toggleCollapse } from "../collapse";
import { AUTO_COLLAPSE_MIN_NODES, DEFAULT_COLLAPSE_DEPTH } from "../constants";

/** A linear chain of `n` nodes (root → … → leaf); depths 0..n-1. */
function caterpillar(n: number): LineagePlot {
  const nodes = [];
  const edges = [];
  for (let i = 0; i < n; i++) {
    nodes.push({ id: `n${i}`, label: `n${i}`, x: i, y: i, isLeaf: i === n - 1, abundance: 1 });
    if (i > 0) edges.push({ source: `n${i - 1}`, target: `n${i}` });
  }
  return { format: "lineage-plot-v1", nodes, edges };
}

describe("defaultCollapsed gate", () => {
  it("does NOT auto-collapse a model at/under AUTO_COLLAPSE_MIN_NODES", () => {
    const model = fromLineagePlot(caterpillar(AUTO_COLLAPSE_MIN_NODES - 50));
    expect(defaultCollapsed(model).size).toBe(0);
  });

  it("collapses depth>=DEFAULT_COLLAPSE_DEPTH nodes when over the gate", () => {
    const model = fromLineagePlot(caterpillar(AUTO_COLLAPSE_MIN_NODES + 50));
    const collapsed = defaultCollapsed(model);
    expect(collapsed.size).toBeGreaterThan(0);
    // Every collapsed id is at depth >= 3 and has children.
    for (const id of collapsed) {
      const n = model.nodes.get(id)!;
      expect(n.depth).toBeGreaterThanOrEqual(DEFAULT_COLLAPSE_DEPTH);
      expect(n.childIds.length).toBeGreaterThan(0);
    }
    // A depth-3 internal node is collapsed; depth-2 is not.
    expect(collapsed.has("n3")).toBe(true);
    expect(collapsed.has("n2")).toBe(false);
  });
});

describe("collapseAll / expandAll / toggle", () => {
  const model = fromLineagePlot(caterpillar(6));

  it("collapseAll collapses every internal node except the root", () => {
    const all = collapseAll(model);
    expect(all.has(model.rootId)).toBe(false);
    // n1..n4 are internal (n5 is the leaf).
    for (const id of ["n1", "n2", "n3", "n4"]) expect(all.has(id)).toBe(true);
    expect(all.has("n5")).toBe(false);
  });

  it("expandAll is empty", () => {
    expect(expandAll().size).toBe(0);
  });

  it("toggleCollapse round-trips and never mutates the input set", () => {
    const start = new Set<string>();
    const added = toggleCollapse(start, "n2");
    expect(added.has("n2")).toBe(true);
    expect(start.has("n2")).toBe(false); // immutable
    const removed = toggleCollapse(added, "n2");
    expect(removed.has("n2")).toBe(false);
  });
});
